"""
每日对账模块
在交易日结束后进行账户对账和数据一致性检查
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Tuple
from zoneinfo import ZoneInfo


class DailyReconciliation:
    """每日对账类"""
    
    def __init__(self, db, market_client, logger=None, auto_fix=True):
        """
        初始化对账模块
        
        Args:
            db: DatabaseManager 实例
            market_client: FutuClient 实例
            logger: 日志记录器
            auto_fix: 是否自动修复差异（默认True，以Futu数据为准）
        """
        self.db = db
        self.market_client = market_client
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self.auto_fix = auto_fix
        
        # 对账过程中收集的问题和修复操作
        self.issues = []
        self.fix_actions = []
    
    def reconcile_daily(self, trading_date: date = None) -> Dict:
        """
        执行每日对账
        
        Args:
            trading_date: 对账日期（美东时间），默认为今日
            
        Returns:
            Dict: 对账结果
        """
        if trading_date is None:
            trading_date = datetime.now(ZoneInfo('America/New_York')).date()
        
        trading_date_str = trading_date.isoformat()
        reconciliation_time = datetime.now(ZoneInfo('America/New_York')).isoformat()
        
        # 重置问题和修复操作列表
        self.issues = []
        self.fix_actions = []
        
        self.logger.info("=" * 80)
        self.logger.info(f"开始每日对账 [{trading_date_str}]")
        self.logger.info("=" * 80)
        
        result = {
            'trading_date': trading_date_str,
            'reconciliation_time': reconciliation_time,
            'timestamp': reconciliation_time,
            'checks': {}
        }
        
        # 1. 持仓对账
        position_check = self._check_positions()
        result['checks']['positions'] = position_check
        
        # 2. 订单对账
        order_check = self._check_orders(trading_date_str)
        result['checks']['orders'] = order_check
        
        # 3. 资金对账
        account_check = self._check_account()
        result['checks']['account'] = account_check
        
        # 4. 每日统计
        daily_stats = self._get_daily_stats(trading_date_str)
        result['daily_stats'] = daily_stats
        
        # 判断对账是否通过
        result['passed'] = all([
            position_check['passed'],
            order_check['passed'],
            account_check['passed']
        ])
        
        # 添加问题和修复操作到结果
        result['issues_summary'] = self.issues
        result['fix_actions'] = self.fix_actions
        
        # 保存对账结果到数据库
        self._save_reconciliation_result(result)
        
        # 输出对账总结
        self._print_reconciliation_summary(result)
        
        # 输出每日交易报告
        self._print_daily_trading_report(trading_date_str)
        
        return result
    
    def _check_positions(self) -> Dict:
        """
        持仓对账：比对数据库持仓和Futu账户持仓
        
        Returns:
            Dict: 对账结果
        """
        self.logger.info("\n【1. 持仓对账】")
        
        try:
            # 获取数据库持仓（开仓状态）
            db_positions = self.db.get_all_open_positions()
            db_symbols = {pos['symbol']: pos for pos in db_positions}
            
            # 获取Futu账户持仓
            futu_positions = self.market_client.get_positions()
            futu_symbols = {pos['symbol']: pos for pos in futu_positions} if futu_positions else {}
            
            # 比对
            db_only = set(db_symbols.keys()) - set(futu_symbols.keys())
            futu_only = set(futu_symbols.keys()) - set(db_symbols.keys())
            common = set(db_symbols.keys()) & set(futu_symbols.keys())
            
            differences = []
            
            # 检查共同持仓的数量差异
            for symbol in common:
                db_qty = db_symbols[symbol]['shares']
                futu_qty = futu_symbols[symbol]['position']
                
                if db_qty != futu_qty:
                    diff = {
                        'symbol': symbol,
                        'db_qty': db_qty,
                        'futu_qty': futu_qty,
                        'diff': futu_qty - db_qty
                    }
                    differences.append(diff)
                    
                    # 记录问题
                    issue = {
                        'type': 'position_quantity_mismatch',
                        'symbol': symbol,
                        'db_qty': db_qty,
                        'futu_qty': futu_qty,
                        'diff': diff['diff']
                    }
                    self.issues.append(issue)
                    
                    self.logger.warning(
                        f"  ⚠️  持仓数量不一致: {symbol} "
                        f"数据库={db_qty}, Futu={futu_qty}, 差异={diff['diff']}"
                    )
                    
                    # 自动修复：以Futu数据为准
                    if self.auto_fix:
                        self._fix_position_quantity(symbol, db_qty, futu_qty)
            
            # 检查仅存在于一方的持仓
            if db_only:
                for symbol in db_only:
                    issue = {
                        'type': 'position_only_in_db',
                        'symbol': symbol,
                        'description': 'Futu中已无持仓，但数据库仍显示持仓'
                    }
                    self.issues.append(issue)
                
                self.logger.warning(f"  ⚠️  仅数据库有持仓: {db_only}")
                # 自动修复：Futu中已无持仓，数据库中标记为已平仓
                if self.auto_fix:
                    for symbol in db_only:
                        self._fix_missing_position_in_futu(symbol)
            
            if futu_only:
                for symbol in futu_only:
                    issue = {
                        'type': 'position_only_in_futu',
                        'symbol': symbol,
                        'description': 'Futu中有持仓，但数据库中无记录（可能为非策略持仓）'
                    }
                    self.issues.append(issue)
                
                self.logger.warning(f"  ⚠️  仅Futu有持仓（可能非策略持仓）: {futu_only}")
                # 注意：仅Futu有的持仓可能是手动开的，不自动添加到数据库
                # 避免将非策略持仓纳入管理
            
            passed = len(db_only) == 0 and len(futu_only) == 0 and len(differences) == 0
            
            if passed:
                self.logger.info(f"  ✓ 持仓对账通过: 共 {len(common)} 个持仓一致")
            elif self.auto_fix and (len(db_only) > 0 or len(differences) > 0):
                self.logger.info(f"  ✓ 持仓差异已自动修复（以Futu为准）")
            
            return {
                'passed': passed,
                'db_positions_count': len(db_symbols),
                'futu_positions_count': len(futu_symbols),
                'common_count': len(common),
                'db_only': list(db_only),
                'futu_only': list(futu_only),
                'quantity_differences': differences
            }
            
        except Exception as e:
            self.logger.error(f"  ✗ 持仓对账失败: {e}", exc_info=True)
            return {
                'passed': False,
                'error': str(e)
            }
    
    def _check_orders(self, trading_date: str) -> Dict:
        """
        订单对账：检查当日订单状态
        
        Args:
            trading_date: 交易日期
            
        Returns:
            Dict: 对账结果
        """
        self.logger.info("\n【2. 订单对账】")
        
        try:
            # 获取当日所有订单（从数据库）
            today_orders = self.db.get_orders_by_date(trading_date)
            
            pending_orders = [o for o in today_orders if o['status'] == 'PENDING']
            filled_orders = [o for o in today_orders if o['status'] == 'FILLED']
            failed_orders = [o for o in today_orders if o['status'] == 'FAILED']
            
            self.logger.info(f"  总订单数: {len(today_orders)}")
            self.logger.info(f"    - 已成交: {len(filled_orders)}")
            self.logger.info(f"    - 待成交: {len(pending_orders)}")
            self.logger.info(f"    - 已失败: {len(failed_orders)}")
            
            # 检查未成交订单（可能需要人工处理）
            if pending_orders:
                self.logger.warning(f"  ⚠️  存在 {len(pending_orders)} 个未成交订单:")
                for order in pending_orders:
                    self.logger.warning(
                        f"    - {order['symbol']} {order['order_type']} "
                        f"{order['shares']}股 @${order['price']:.2f} "
                        f"[{order['order_id']}]"
                    )
            
            passed = True  # 订单对账主要是信息展示，不影响通过状态
            
            return {
                'passed': passed,
                'total_orders': len(today_orders),
                'filled_orders': len(filled_orders),
                'pending_orders': len(pending_orders),
                'failed_orders': len(failed_orders),
                'pending_order_list': [
                    {
                        'order_id': o['order_id'],
                        'symbol': o['symbol'],
                        'order_type': o['order_type'],
                        'shares': o['shares']
                    } for o in pending_orders
                ]
            }
            
        except Exception as e:
            self.logger.error(f"  ✗ 订单对账失败: {e}", exc_info=True)
            return {
                'passed': False,
                'error': str(e)
            }
    
    def _check_account(self) -> Dict:
        """
        资金对账：获取账户信息
        
        Returns:
            Dict: 对账结果
        """
        self.logger.info("\n【3. 资金对账】")
        
        try:
            acc_info = self.market_client.get_account_info()
            
            if not acc_info:
                self.logger.error("  ✗ 无法获取账户信息")
                return {
                    'passed': False,
                    'error': '无法获取账户信息'
                }
            
            total_assets = acc_info.get('total_assets', 0)
            cash = acc_info.get('cash', 0)
            market_value = acc_info.get('market_value', 0)
            
            self.logger.info(f"  总资产: ${total_assets:,.2f}")
            self.logger.info(f"  现金: ${cash:,.2f} ({cash/total_assets*100:.1f}%)")
            self.logger.info(f"  持仓市值: ${market_value:,.2f} ({market_value/total_assets*100:.1f}%)")
            
            # 检查现金是否为负（异常情况）
            if cash < 0:
                self.logger.warning(f"  ⚠️  现金为负值: ${cash:,.2f}")
            
            return {
                'passed': cash >= 0,
                'total_assets': total_assets,
                'cash': cash,
                'market_value': market_value,
                'cash_ratio': cash / total_assets if total_assets > 0 else 0,
                'position_ratio': market_value / total_assets if total_assets > 0 else 0
            }
            
        except Exception as e:
            self.logger.error(f"  ✗ 资金对账失败: {e}", exc_info=True)
            return {
                'passed': False,
                'error': str(e)
            }
    
    def _get_daily_stats(self, trading_date: str) -> Dict:
        """
        获取每日统计
        
        Args:
            trading_date: 交易日期
            
        Returns:
            Dict: 统计数据
        """
        self.logger.info("\n【4. 每日统计】")
        
        try:
            stats = self.db.get_daily_stats(trading_date)
            
            buy_orders = stats.get('buy_orders', 0)
            sell_orders = stats.get('sell_orders', 0)
            open_positions = stats.get('open_positions', 0)
            
            self.logger.info(f"  买入订单: {buy_orders} 笔")
            self.logger.info(f"  卖出订单: {sell_orders} 笔")
            self.logger.info(f"  当前持仓: {open_positions} 个")
            
            return stats
            
        except Exception as e:
            self.logger.warning(f"  ⚠️  获取统计失败: {e}")
            return {}
    
    def _save_reconciliation_result(self, result: Dict):
        """
        保存对账结果到数据库
        
        Args:
            result: 对账结果
        """
        try:
            # 准备保存到数据库的数据
            save_data = {
                'trading_date': result['trading_date'],
                'reconciliation_time': result.get('reconciliation_time', result['timestamp']),
                'passed': result['passed'],
                'position_check': result['checks'].get('positions', {}),
                'order_check': result['checks'].get('orders', {}),
                'account_check': result['checks'].get('account', {}),
                'daily_stats': result.get('daily_stats', {}),
                'issues_summary': result.get('issues_summary', []),
                'fix_actions': result.get('fix_actions', [])
            }
            
            # 保存到数据库
            record_id = self.db.save_reconciliation_result(save_data)
            self.logger.debug(f"对账结果已保存到数据库 [ID: {record_id}]")
            
        except Exception as e:
            self.logger.error(f"保存对账结果失败: {e}", exc_info=True)
    
    def _print_reconciliation_summary(self, result: Dict):
        """
        打印对账总结
        
        Args:
            result: 对账结果
        """
        self.logger.info("\n" + "=" * 80)
        self.logger.info("对账总结")
        self.logger.info("=" * 80)
        
        if result['passed']:
            self.logger.info("✅ 对账通过 - 所有检查项正常")
        else:
            self.logger.warning("⚠️  对账发现异常 - 请检查以上警告信息")
        
        checks = result['checks']
        
        # 持仓检查
        if 'positions' in checks:
            pos = checks['positions']
            if pos['passed']:
                self.logger.info(f"  ✓ 持仓: {pos.get('common_count', 0)} 个一致")
            else:
                self.logger.warning(f"  ✗ 持仓: 存在差异")
        
        # 订单检查
        if 'orders' in checks:
            orders = checks['orders']
            pending = orders.get('pending_orders', 0)
            if pending > 0:
                self.logger.warning(f"  ⚠️  订单: {pending} 个待成交")
            else:
                self.logger.info(f"  ✓ 订单: 无待成交订单")
        
        # 资金检查
        if 'account' in checks:
            acc = checks['account']
            if acc['passed']:
                self.logger.info(
                    f"  ✓ 资金: ${acc.get('total_assets', 0):,.2f} "
                    f"(现金 {acc.get('cash_ratio', 0):.1%})"
                )
            else:
                self.logger.warning(f"  ✗ 资金: 异常")
        
        self.logger.info("=" * 80 + "\n")
    
    def _fix_position_quantity(self, symbol: str, db_qty: int, futu_qty: int):
        """
        修复持仓数量差异（以Futu为准）
        
        Args:
            symbol: 股票代码
            db_qty: 数据库中的数量
            futu_qty: Futu中的数量
        """
        try:
            if futu_qty == 0:
                # Futu中已无持仓，标记为已平仓
                self.db.close_position(symbol)
                action = {
                    'action': 'close_position',
                    'symbol': symbol,
                    'reason': 'Futu中已无持仓',
                    'old_qty': db_qty,
                    'new_qty': 0
                }
                self.fix_actions.append(action)
                self.logger.info(f"    🔧 已修复: {symbol} 在数据库中标记为已平仓")
            else:
                # 更新持仓数量
                self.db.update_position(symbol, {'shares': futu_qty})
                action = {
                    'action': 'update_position_quantity',
                    'symbol': symbol,
                    'old_qty': db_qty,
                    'new_qty': futu_qty
                }
                self.fix_actions.append(action)
                self.logger.info(
                    f"    🔧 已修复: {symbol} 持仓数量 {db_qty} → {futu_qty}"
                )
        except Exception as e:
            self.logger.error(f"    ✗ 修复 {symbol} 持仓失败: {e}")
    
    def _fix_missing_position_in_futu(self, symbol: str):
        """
        修复Futu中不存在的持仓（数据库标记为已平仓）
        
        Args:
            symbol: 股票代码
        """
        try:
            # 查询数据库中的持仓信息
            db_position = self.db.get_position(symbol)
            
            if db_position and db_position['status'] == 'OPEN':
                # 在数据库中标记为已平仓
                self.db.close_position(symbol)
                
                action = {
                    'action': 'close_position',
                    'symbol': symbol,
                    'reason': 'Futu中已无此持仓',
                    'old_qty': db_position['shares'],
                    'new_qty': 0
                }
                self.fix_actions.append(action)
                
                self.logger.info(
                    f"    🔧 已修复: {symbol} 在Futu中已无持仓，"
                    f"数据库中标记为已平仓（原持仓 {db_position['shares']} 股）"
                )
        except Exception as e:
            self.logger.error(f"    ✗ 修复 {symbol} 失败: {e}")
    
    def _print_daily_trading_report(self, trading_date: str):
        """
        打印每日交易报告
        
        Args:
            trading_date: 交易日期
        """
        self.logger.info("\n" + "=" * 80)
        self.logger.info(f"每日交易报告 [{trading_date}]")
        self.logger.info("=" * 80)
        
        try:
            # 获取当日所有订单
            today_orders = self.db.get_orders_by_date(trading_date)
            
            # 分类订单
            buy_orders = [o for o in today_orders if o['order_type'] == 'BUY']
            sell_orders = [o for o in today_orders if o['order_type'] == 'SELL']
            
            # 1. 买入统计
            self._print_buy_summary(buy_orders)
            
            # 2. 卖出统计
            self._print_sell_summary(sell_orders)
            
            # 3. 持仓统计
            self._print_position_summary()
            
            # 4. 浮盈浮亏统计
            self._print_pnl_summary()
            
            self.logger.info("=" * 80 + "\n")
            
        except Exception as e:
            self.logger.error(f"生成每日交易报告失败: {e}", exc_info=True)
    
    def _print_buy_summary(self, buy_orders: List[Dict]):
        """
        打印买入统计
        
        Args:
            buy_orders: 买入订单列表
        """
        self.logger.info("\n【买入统计】")
        
        if not buy_orders:
            self.logger.info("  无买入记录")
            return
        
        # 统计成交的买入订单
        filled_buys = [o for o in buy_orders if o['status'] == 'FILLED']
        
        total_buy_amount = sum(o['price'] * o['shares'] for o in filled_buys)
        total_shares = sum(o['shares'] for o in filled_buys)
        
        self.logger.info(f"  买入笔数: {len(filled_buys)} 笔")
        self.logger.info(f"  买入总额: ${total_buy_amount:,.2f}")
        self.logger.info(f"  买入总股数: {total_shares:,} 股")
        
        if filled_buys:
            self.logger.info(f"\n  买入明细:")
            for order in filled_buys:
                amount = order['price'] * order['shares']
                self.logger.info(
                    f"    {order['symbol']:6s} {order['shares']:4d}股 "
                    f"@${order['price']:7.2f} = ${amount:10,.2f} "
                    f"[{order['order_time'][:19]}]"
                )
    
    def _print_sell_summary(self, sell_orders: List[Dict]):
        """
        打印卖出统计
        
        Args:
            sell_orders: 卖出订单列表
        """
        self.logger.info("\n【卖出统计】")
        
        if not sell_orders:
            self.logger.info("  无卖出记录")
            return
        
        # 统计成交的卖出订单
        filled_sells = [o for o in sell_orders if o['status'] == 'FILLED']
        
        total_sell_amount = sum(o['price'] * o['shares'] for o in filled_sells)
        total_shares = sum(o['shares'] for o in filled_sells)
        
        self.logger.info(f"  卖出笔数: {len(filled_sells)} 笔")
        self.logger.info(f"  卖出总额: ${total_sell_amount:,.2f}")
        self.logger.info(f"  卖出总股数: {total_shares:,} 股")
        
        if filled_sells:
            self.logger.info(f"\n  卖出明细:")
            for order in filled_sells:
                amount = order['price'] * order['shares']
                reason = order.get('reason', 'unknown')
                self.logger.info(
                    f"    {order['symbol']:6s} {order['shares']:4d}股 "
                    f"@${order['price']:7.2f} = ${amount:10,.2f} "
                    f"[{reason}] [{order['order_time'][:19]}]"
                )
    
    def _print_position_summary(self):
        """打印持仓统计"""
        self.logger.info("\n【持仓统计】")
        
        try:
            positions = self.db.get_all_open_positions()
            
            if not positions:
                self.logger.info("  无持仓")
                return
            
            # 获取Futu实时价格和市值
            futu_positions = self.market_client.get_positions()
            futu_price_map = {
                pos['symbol']: {
                    'current_price': pos['market_price'],
                    'market_value': pos['market_value']
                }
                for pos in futu_positions
            } if futu_positions else {}
            
            total_cost = 0
            total_market_value = 0
            
            self.logger.info(f"  持仓数: {len(positions)} 个")
            self.logger.info(f"\n  持仓明细:")
            self.logger.info(
                f"    {'股票':6s} {'股数':>6s} {'成本价':>9s} {'现价':>9s} "
                f"{'成本':>12s} {'市值':>12s} {'盈亏':>10s} {'比例':>8s}"
            )
            self.logger.info("    " + "-" * 76)
            
            for pos in positions:
                symbol = pos['symbol']
                shares = pos['shares']
                entry_price = pos['entry_price']
                cost = entry_price * shares
                
                # 获取实时价格
                if symbol in futu_price_map:
                    current_price = futu_price_map[symbol]['current_price']
                    market_value = futu_price_map[symbol]['market_value']
                else:
                    # 如果Futu中没有，使用成本价（可能刚平仓）
                    current_price = entry_price
                    market_value = cost
                
                pnl = market_value - cost
                pnl_ratio = (pnl / cost) if cost > 0 else 0
                
                total_cost += cost
                total_market_value += market_value
                
                pnl_sign = '+' if pnl >= 0 else ''
                
                self.logger.info(
                    f"    {symbol:6s} {shares:6d} "
                    f"${entry_price:8.2f} ${current_price:8.2f} "
                    f"${cost:11,.2f} ${market_value:11,.2f} "
                    f"{pnl_sign}${pnl:9,.2f} {pnl_sign}{pnl_ratio:7.1%}"
                )
            
            # 汇总
            total_pnl = total_market_value - total_cost
            total_pnl_ratio = (total_pnl / total_cost) if total_cost > 0 else 0
            pnl_sign = '+' if total_pnl >= 0 else ''
            
            self.logger.info("    " + "-" * 76)
            self.logger.info(
                f"    {'合计':6s} {' ':6s} {' ':9s} {' ':9s} "
                f"${total_cost:11,.2f} ${total_market_value:11,.2f} "
                f"{pnl_sign}${total_pnl:9,.2f} {pnl_sign}{total_pnl_ratio:7.1%}"
            )
            
        except Exception as e:
            self.logger.error(f"  获取持仓统计失败: {e}")
    
    def _print_pnl_summary(self):
        """
        打印浮盈浮亏统计（未实现盈亏）
        """
        self.logger.info("\n【浮盈浮亏统计】")
        
        try:
            # 获取所有开仓持仓
            positions = self.db.get_all_open_positions()
            
            if not positions:
                self.logger.info("  无持仓，无浮盈浮亏")
                return
            
            # 获取Futu实时价格
            futu_positions = self.market_client.get_positions()
            futu_price_map = {
                pos['symbol']: pos['market_price']
                for pos in futu_positions
            } if futu_positions else {}
            
            total_cost = 0
            total_market_value = 0
            pnl_details = []
            
            for pos in positions:
                symbol = pos['symbol']
                shares = pos['shares']
                entry_price = pos['entry_price']
                cost = entry_price * shares
                
                # 获取实时价格
                if symbol in futu_price_map:
                    current_price = futu_price_map[symbol]
                else:
                    # 如果Futu中没有，使用成本价
                    current_price = entry_price
                
                market_value = current_price * shares
                pnl = market_value - cost
                pnl_ratio = (pnl / cost) if cost > 0 else 0
                
                total_cost += cost
                total_market_value += market_value
                
                pnl_details.append({
                    'symbol': symbol,
                    'shares': shares,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'cost': cost,
                    'market_value': market_value,
                    'pnl': pnl,
                    'pnl_ratio': pnl_ratio
                })
            
            # 按盈亏金额排序（从高到低）
            pnl_details.sort(key=lambda x: x['pnl'], reverse=True)
            
            # 打印浮盈浮亏明细
            self.logger.info(f"\n  浮盈浮亏明细:")
            self.logger.info(
                f"    {'股票':6s} {'股数':>6s} {'成本价':>9s} {'现价':>9s} "
                f"{'成本':>12s} {'市值':>12s} {'浮盈':>11s} {'比例':>8s}"
            )
            self.logger.info("    " + "-" * 80)
            
            for detail in pnl_details:
                pnl_sign = '+' if detail['pnl'] >= 0 else ''
                
                self.logger.info(
                    f"    {detail['symbol']:6s} {detail['shares']:6d} "
                    f"${detail['entry_price']:8.2f} ${detail['current_price']:8.2f} "
                    f"${detail['cost']:11,.2f} ${detail['market_value']:11,.2f} "
                    f"{pnl_sign}${detail['pnl']:10,.2f} {pnl_sign}{detail['pnl_ratio']:7.1%}"
                )
            
            # 汇总
            total_pnl = total_market_value - total_cost
            avg_pnl_ratio = (total_pnl / total_cost) if total_cost > 0 else 0
            pnl_sign = '+' if total_pnl >= 0 else ''
            
            self.logger.info("    " + "-" * 80)
            self.logger.info(
                f"    {'合计':6s} {' ':6s} {' ':9s} {' ':9s} "
                f"${total_cost:11,.2f} ${total_market_value:11,.2f} "
                f"{pnl_sign}${total_pnl:10,.2f} {pnl_sign}{avg_pnl_ratio:7.1%}"
            )
            
            # 盈亏统计
            win_count = sum(1 for d in pnl_details if d['pnl'] > 0)
            loss_count = sum(1 for d in pnl_details if d['pnl'] < 0)
            
            self.logger.info(f"\n  总浮盈浮亏: {pnl_sign}${total_pnl:,.2f} ({pnl_sign}{avg_pnl_ratio:.2%})")
            self.logger.info(f"  浮盈持仓: {win_count} 个")
            self.logger.info(f"  浮亏持仓: {loss_count} 个")
            if len(pnl_details) > 0:
                self.logger.info(f"  盈利占比: {win_count / len(pnl_details):.1%}")
            
        except Exception as e:
            self.logger.error(f"  计算浮盈浮亏失败: {e}", exc_info=True)


if __name__ == "__main__":
    # 测试代码
    import sys
    from pathlib import Path
    
    # 添加项目路径
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    
    from database.models import DatabaseManager
    from market.futu_client import FutuClient
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 初始化
    db = DatabaseManager('/Users/niningxi/Desktop/future/op_trade_data/trading.db')
    
    # 模拟market_client（实际使用时需要真实的FutuClient）
    class MockMarketClient:
        def get_positions(self):
            return []
        
        def get_account_info(self):
            return {
                'total_assets': 100000.0,
                'cash': 50000.0,
                'market_value': 50000.0
            }
    
    market_client = MockMarketClient()
    
    # 执行对账
    reconciliation = DailyReconciliation(db, market_client)
    result = reconciliation.reconcile_daily()
    
    print(f"\n对账{'通过' if result['passed'] else '失败'}")

