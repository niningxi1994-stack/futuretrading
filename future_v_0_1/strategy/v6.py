import logging
from datetime import date, datetime, time, timedelta
from typing import Optional, Dict
from zoneinfo import ZoneInfo

try:
    from .strategy import StrategyBase, StrategyContext, EntryDecision, ExitDecision
except ImportError:
    from strategy import StrategyBase, StrategyContext, EntryDecision, ExitDecision


class StrategyV6(StrategyBase):
    def __init__(self, context: StrategyContext):
        super().__init__(context)
        
        # 读取 strategy 配置
        strategy_cfg = self.cfg.get('strategy', {})
        
        # 过滤器配置
        filter_cfg = strategy_cfg.get('filter', {})
        self.min_premium_usd = filter_cfg.get('min_premium_usd', 100000)
        self.entry_time_et = filter_cfg.get('entry_time_et', '15:30:00')
        self.max_trade_time = filter_cfg.get('max_trade_time', 5)
        self.max_position = filter_cfg.get('max_position', 0.99)
        
        # 止盈止损
        self.take_profit = strategy_cfg.get('take_profit', 0.15)
        self.stop_loss = strategy_cfg.get('stop_loss', 0.05)
        
        # 持仓天数
        self.holding_days = strategy_cfg.get('holding_days', 6)
        
        # 黑名单天数
        self.blacklist_days = strategy_cfg.get('blacklist_days', 15)
        
        # 仓位计算
        position_compute_cfg = strategy_cfg.get('position_compute', {})
        self.max_premium_usd = position_compute_cfg.get('max_premium_usd', 800000)
        self.max_per_position = position_compute_cfg.get('max_per_position', 0.3)
        
        # 运行时状态
        self.daily_trade_count = 0
        # 黑名单：记录过去N个交易日买入过的股票，key=symbol, value=买入时间
        # 用途：避免短期内重复交易同一标的
        self.blacklist: Dict[str, datetime] = {}
        
        # 打印配置信息
        self.logger.info(
            f"StrategyV6 初始化: 权利金>=${self.min_premium_usd/1000:.0f}K, "
            f"入场>={self.entry_time_et}, 日限{self.max_trade_time}次, "
            f"总仓<={self.max_position:.0%}, 单仓<={self.max_per_position:.0%}, "
            f"止盈{self.take_profit:+.0%}, 止损{self.stop_loss:+.0%}, "
            f"持{self.holding_days}日, 黑名单{self.blacklist_days}日"
        )

    def on_start(self):
        pass

    def on_shutdown(self):
        pass

    def on_day_open(self, trading_date_et: date):
        pass
    
    def on_day_close(self, trading_date_et: date):
        pass
    
    def on_signal(self, ev, market_client=None):
        """
        处理信号事件，生成开仓决策
        
        Args:
            ev: 信号事件
            market_client: 市场数据客户端实例（可选）
            
        Returns:
            EntryDecision 或 None
        """
        # 时间过滤
        entry_time = datetime.strptime(self.entry_time_et, '%H:%M:%S').time()
        if ev.event_time_et.time() < entry_time:
            self.logger.debug(f"过滤: {ev.symbol} 时间过早 {ev.event_time_et.time()}")
            return None
        
        if ev.premium_usd < self.min_premium_usd:
            self.logger.debug(f"过滤: {ev.symbol} 权利金过低 ${ev.premium_usd:,.0f}")
            return None
        
        # 黑名单过滤（避免短期重复交易）
        if ev.symbol in self.blacklist:
            last_buy_time = self.blacklist[ev.symbol]
            self.logger.info(
                f"过滤: {ev.symbol} 在黑名单中 (上次买入: {last_buy_time.strftime('%Y-%m-%d %H:%M:%S')})"
            )
            return None
        
        if self.daily_trade_count >= self.max_trade_time:
            self.logger.info(f"过滤: {ev.symbol} 今日已达交易上限 {self.daily_trade_count}/{self.max_trade_time}")
            return None
        
        # 检查市场客户端是否可用
        if not market_client:
            self.logger.error("市场数据客户端未提供，无法处理信号")
            return None
        
        # 计算仓位比例
        pos_ratio = min(ev.premium_usd / self.max_premium_usd, self.max_per_position)
        self.logger.debug(f"计算仓位比例: {pos_ratio:.2%}")

        # 获取账户信息
        acc_info = market_client.get_account_info()
        if not acc_info:
            self.logger.error("获取账户信息失败")
            return None
            
        total_assets = acc_info['total_assets']
        cash = acc_info['cash']
        self.logger.debug(f"账户: 总资产=${total_assets:,.0f}, 现金=${cash:,.0f}")
        
        # 获取股票价格
        price_info = market_client.get_stock_price(ev.symbol)
        if not price_info:
            self.logger.error(f"获取 {ev.symbol} 价格失败")
            return None
            
        current_price = price_info['last_price']
        
        # 计算股数
        qty = int(total_assets * pos_ratio / current_price)
        self.logger.debug(f"计算: {qty}股 = ${total_assets:,.0f} × {pos_ratio:.1%} / ${current_price:.2f}")
        
        # 检查总仓位是否超过限制
        positions = market_client.get_positions()
        if positions:
            total_position_value = sum(pos['market_value'] for pos in positions if pos.get('market_value'))
            current_position_ratio = total_position_value / total_assets
            new_position_value = current_price * qty
            new_total_ratio = (total_position_value + new_position_value) / total_assets
            
            self.logger.debug(f"仓位: 当前{current_position_ratio:.1%} → 新增后{new_total_ratio:.1%}")
            
            if new_total_ratio > self.max_position:
                self.logger.info(
                    f"过滤: {ev.symbol} 总仓位将超限 {new_total_ratio:.1%} > {self.max_position:.0%}"
                )
                return None
        
        # 检查现金是否充足
        required_cash = current_price * qty
        if cash < required_cash:
            self.logger.info(f"过滤: {ev.symbol} 现金不足 需要${required_cash:,.0f} > 可用${cash:,.0f}")
            return None

        price_limit = current_price
        client_id = f'{ev.symbol}_{ev.event_time_et.strftime("%Y%m%d%H%M%S")}'
        time_et_now = datetime.now(ZoneInfo('America/New_York'))

        self.logger.info(
            f"✓ 开仓决策: {ev.symbol} {qty}股 @${price_limit:.2f} "
            f"(仓位{pos_ratio:.1%}, 权利金${ev.premium_usd:,.0f})"
        )

        return EntryDecision(
            symbol=ev.symbol,
            shares=qty,
            price_limit=price_limit,
            t_exec_et=time_et_now,
            pos_ratio=pos_ratio,
            client_id=client_id,
            meta={
                'event_id': ev.event_id,
                'premium_usd': ev.premium_usd,
                'current_price': current_price
            }
        )

    def on_position_check(self, market_client=None, entry_time_map=None):
        """
        检查持仓，生成平仓决策
        
        Args:
            market_client: 市场数据客户端实例（可选）
            entry_time_map: 持仓开仓时间映射 {symbol: entry_time_str}（可选）
            
        Returns:
            List[ExitDecision]: 平仓决策列表
        """
        if not market_client:
            self.logger.error("市场数据客户端未提供，无法检查持仓")
            return []
        
        positions = market_client.get_positions()
        if not positions:
            return []
        
        if entry_time_map is None:
            entry_time_map = {}
        
        exit_decisions = []
        for pos in positions:
            # print(pos)
            symbol = pos['symbol']
            cost_price = pos['cost_price']
            current_price = pos['market_price']
            total_position = pos['position']
            
            # 确定可卖数量
            can_sell_qty = pos['can_sell_qty']
            
            if can_sell_qty <= 0:
                # 主动查询未成交订单，诊断问题原因
                self.logger.debug(f"{symbol} 可卖数量=0，查询未成交订单...")
                
                try:
                    # 查询该股票的未成交卖单
                    pending_orders = market_client.get_order_list(
                        status_filter='PENDING',
                        symbol_filter=symbol
                    )
                    
                    if pending_orders:
                        # 找到未成交的卖单
                        pending_sells = [o for o in pending_orders if o['side'] == 'SELL']
                        
                        if pending_sells:
                            # 情况1：有未成交卖单，股票被锁定（正常）
                            total_pending_qty = sum(o['qty'] for o in pending_sells)
                            self.logger.debug(
                                f"{symbol} 已有未成交卖单 {len(pending_sells)}个, "
                                f"锁定{total_pending_qty}股"
                            )
                            continue
                    
                    # 情况2：没有未成交卖单，但可卖数量为0（异常）
                    self.logger.warning(
                        f"{symbol} 可卖数量=0 但无未成交卖单（可能T+1限制或API异常）"
                    )
                    continue
                    
                except Exception as e:
                    self.logger.error(f"查询 {symbol} 订单失败: {e}")
                    continue
            
            # 检查持仓天数
            if symbol in entry_time_map:
                try:
                    entry_time_str = entry_time_map[symbol]
                    # 解析开仓时间（ISO格式）
                    entry_time_dt = datetime.fromisoformat(entry_time_str)
                    
                    # 确保是美东时间
                    if entry_time_dt.tzinfo is None:
                        # 如果没有时区信息，假设已经是美东时间（系统统一使用美东时间）
                        entry_time_et = entry_time_dt.replace(tzinfo=ZoneInfo('America/New_York'))
                    else:
                        # 如果有时区信息，转换为美东时间
                        entry_time_et = entry_time_dt.astimezone(ZoneInfo('America/New_York'))
                    
                    # 检查是否超过持仓天数
                    if self._check_holding_days(entry_time_et, market_client):
                        # 获取当前美东时间
                        current_et = datetime.now(ZoneInfo('America/New_York'))
                        
                        # 只在当日15:00或之后平仓
                        exit_time = time(15, 0, 0)  # 15:00:00
                        if current_et.time() < exit_time:
                            self.logger.debug(
                                f"{symbol} 持仓已到期，但当前时间 {current_et.time()} 早于15:00，等待平仓"
                            )
                            continue  # 等待15:00后再平仓
                        
                        # 计算实际持仓天数
                        entry_date = entry_time_et.date()
                        current_date = current_et.date()
                        trading_days_held = self._count_trading_days(
                            entry_date, 
                            current_date, 
                            market_client
                        )
                        
                        pnl_ratio = (current_price - cost_price) / cost_price
                        self.logger.info(
                            f"✓ 平仓决策[持仓到期]: {symbol} {can_sell_qty}股 @${current_price:.2f} "
                            f"(成本${cost_price:.2f}, 持仓{trading_days_held}日, 盈亏{pnl_ratio:+.1%})"
                        )
                        exit_decisions.append(ExitDecision(
                            symbol=pos['symbol'],
                            shares=can_sell_qty,
                            price_limit=current_price,
                            reason='holding_days_exceeded',
                            client_id=f"{pos['symbol']}_HD_{current_et.strftime('%Y%m%d%H%M%S')}",
                            meta={
                                'holding_days': trading_days_held,
                                'pnl_ratio': pnl_ratio
                            }
                        ))
                        # 持仓到期后不再检查止损止盈，直接继续下一个持仓
                        continue
                        
                except Exception as e:
                    self.logger.warning(f"解析 {symbol} 开仓时间失败: {e}")
            
            # 止损检查
            if self._check_stop_loss(cost_price, current_price):
                pnl_ratio = (current_price - cost_price) / cost_price
                self.logger.info(
                    f"✓ 平仓决策[止损]: {symbol} {can_sell_qty}股 @${current_price:.2f} "
                    f"(成本${cost_price:.2f}, 亏损{pnl_ratio:.1%})"
                )
                exit_decisions.append(ExitDecision(
                    symbol=pos['symbol'],
                    shares=can_sell_qty,
                    price_limit=current_price,
                    reason='stop_loss',
                    client_id=f"{pos['symbol']}_SL_{datetime.now(ZoneInfo('America/New_York')).strftime('%Y%m%d%H%M%S')}",
                    meta={'stop_loss': pnl_ratio}
                ))
            
            # 止盈检查
            if self._check_take_profit(cost_price, current_price):
                pnl_ratio = (current_price - cost_price) / cost_price
                self.logger.info(
                    f"✓ 平仓决策[止盈]: {symbol} {can_sell_qty}股 @${current_price:.2f} "
                    f"(成本${cost_price:.2f}, 盈利{pnl_ratio:.1%})"
                )
                exit_decisions.append(ExitDecision(
                    symbol=pos['symbol'],
                    shares=can_sell_qty,
                    price_limit=current_price,
                    reason='take_profit',
                    client_id=f"{pos['symbol']}_TP_{datetime.now(ZoneInfo('America/New_York')).strftime('%Y%m%d%H%M%S')}",
                    meta={'take_profit': pnl_ratio}
                ))
        return exit_decisions
    
    def _check_stop_loss(self, cost_price, current_price):
        """检查是否触发止损"""
        return current_price < cost_price * (1 - self.stop_loss)
    
    def _check_take_profit(self, cost_price, current_price):
        """检查是否触发止盈"""
        return current_price > cost_price * (1 + self.take_profit)
    
    def _check_holding_days(self, open_time_et, market_client=None):
        """
        检查是否到达持仓天数（交易日）
        
        Args:
            open_time_et: 开仓时间（美东时间）
            market_client: 市场数据客户端（可选，用于查询交易日）
            
        Returns:
            bool: 是否超过持仓天数
        """
        open_date = open_time_et.date()
        current_date = datetime.now(ZoneInfo('America/New_York')).date()
        
        # 计算持有的交易日数
        trading_days_held = self._count_trading_days(
            open_date, 
            current_date, 
            market_client
        )
        
        return trading_days_held >= self.holding_days
    
    def _count_trading_days(self, start_date, end_date, market_client=None):
        """
        计算两个日期之间的交易日数量（包括 start_date 和 end_date）
        
        优先使用 Futu API 查询交易日，如果失败则使用本地计算（排除周末）
        
        Args:
            start_date: 开始日期（date 对象，包括该日）
            end_date: 结束日期（date 对象，包括该日）
            market_client: 市场数据客户端（可选）
            
        Returns:
            int: 交易日数量
        """
        if start_date > end_date:
            return 0
        
        # 尝试使用 Futu API
        if market_client:
            try:
                # 注意：需要调整日期范围，因为 API 可能不包括 start_date
                # 这里我们先查询包含 start_date 的范围
                count = market_client.count_trading_days_between(
                    start_date=(start_date - timedelta(days=1)).strftime('%Y-%m-%d'),
                    end_date=end_date.strftime('%Y-%m-%d'),
                    market='US'
                )
                
                if count is not None:
                    self.logger.debug(f"使用 Futu API 计算交易日: {count} 天")
                    return count
                else:
                    self.logger.warning("Futu API 查询交易日失败，使用本地计算")
            except Exception as e:
                self.logger.warning(f"Futu API 查询交易日异常: {e}，使用本地计算")
        
        # 如果没有 market_client 或 API 调用失败，使用本地计算
        # 只排除周末，不考虑节假日（保守策略）
        trading_days = 0
        current = start_date  # 包括开仓当天
        
        while current <= end_date:
            # 只检查是否为工作日（周一=0, 周日=6）
            if current.weekday() < 5:  # 周一到周五
                trading_days += 1
            
            current += timedelta(days=1)
        
        self.logger.debug(f"本地计算交易日（仅排除周末）: {trading_days} 天")
        return trading_days
    
    def on_order_filled(self, res):
        pass
    
    def on_order_rejected(self, res, reason: str):
        pass

if __name__ == '__main__':
    import yaml
    import os
    from pathlib import Path
    from zoneinfo import ZoneInfo
    from strategy import SignalEvent
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 确定配置文件路径（环境变量 > 默认路径）
    if os.environ.get('TRADING_CONFIG_PATH'):
        config_path = Path(os.environ['TRADING_CONFIG_PATH'])
    else:
        config_path = Path(__file__).parent.parent.parent / 'config.yaml'
    
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        print(f"可通过环境变量指定: export TRADING_CONFIG_PATH=/path/to/config.yaml")
        import sys
        sys.exit(1)
    
    print(f"读取配置文件: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    print("\n策略配置:")
    print(f"  策略名称: {config['strategy']['name']}")
    print(f"  最小权利金: ${config['strategy']['filter']['min_premium_usd']:,}")
    print(f"  入场时间: {config['strategy']['filter']['entry_time_et']}")
    print(f"  最大交易次数/日: {config['strategy']['filter']['max_trade_time']}")
    print(f"  最大总仓位: {config['strategy']['filter']['max_position']:.2%}")
    print(f"  单笔最大仓位: {config['strategy']['position_compute']['max_per_position']:.2%}")
    print(f"  止盈: +{config['strategy']['take_profit']:.2%}")
    print(f"  止损: -{config['strategy']['stop_loss']:.2%}")
    print(f"  持仓天数: {config['strategy']['holding_days']}")
    print()
    
    # 创建市场数据客户端
    print("\n[4] 连接市场数据客户端")
    market_client = None
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from market.futu_client import FutuClient
        
        market_client = FutuClient(
            host='127.0.0.1',
            port=11111,
            trd_env='SIMULATE',
            trd_market='US',
            acc_id=16428245  # 替换为你的账户ID
        )
        
        if market_client.connect():
            print("  ✓ 市场数据客户端连接成功")
        else:
            print("  ✗ 市场数据客户端连接失败")
            market_client = None
    except Exception as e:
        print(f"  ⚠ 无法连接市场数据客户端: {e}")
        market_client = None
    
    # 创建策略上下文
    context = StrategyContext(
        cfg=config,
        logger=logging.getLogger('StrategyV6')
    )
    
    # 创建策略实例
    strategy = StrategyV6(context)
    
    # 测试
    #strategy.on_start()
    #strategy.on_day_open(date.today())
    #strategy.on_shutdown()
    
    # 测试持仓检查
    print("\n[5] 测试持仓检查")
    print("="*80)
    if market_client:
        exit_decisions = strategy.on_position_check(market_client)
        if exit_decisions:
            print(f"✓ 生成 {len(exit_decisions)} 个平仓决策:")
            for decision in exit_decisions:
                print(f"  - {decision.symbol}: {decision.shares} 股")
                print(f"    原因: {decision.reason}")
                print(f"    价格: ${decision.price_limit:.2f}")
                print(f"    订单ID: {decision.client_id}")
                if 'stop_loss' in decision.meta:
                    print(f"    止损比例: {decision.meta['stop_loss']:.2%}")
                if 'take_profit' in decision.meta:
                    print(f"    止盈比例: {decision.meta['take_profit']:.2%}")
        else:
            print("✗ 无平仓决策")
    else:
        print("⚠ 市场数据客户端未连接，跳过测试")
    print("="*80)
    
    # 断开连接
    if market_client:
        market_client.disconnect()
        print("\n✓ 市场数据客户端已断开连接")