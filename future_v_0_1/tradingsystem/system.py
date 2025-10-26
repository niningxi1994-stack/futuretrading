"""
交易系统主类
"""

import time
import sys
import logging
from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo
from typing import Dict

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.config import SystemConfig
from optionparser.parser import OptionMonitor
from strategy.strategy import StrategyContext, SignalEvent
from market.futu_client import FutuClient
from database.models import DatabaseManager
from tradingsystem.reconciliation import DailyReconciliation


def normalize_symbol(symbol: str, market: str = 'US') -> str:
    """
    标准化股票代码，确保包含市场前缀
    
    Args:
        symbol: 股票代码
        market: 市场代码（默认US）
        
    Returns:
        str: 标准化后的股票代码（如 US.AAPL）
    """
    if '.' not in symbol:
        return f'{market}.{symbol}'
    return symbol


def get_et_date() -> date:
    """
    获取美东时间的日期
    
    Returns:
        date: 美东时间的日期对象
    """
    et_now = datetime.now(ZoneInfo('America/New_York'))
    return et_now.date()


class TradingSystem:
    """交易系统主控"""
    
    def __init__(self, config: SystemConfig, market_client: FutuClient, db_path: str = None):
        """
        初始化交易系统
        
        Args:
            config: 系统配置对象
            market_client: 市场数据客户端
            db_path: 数据库路径（可选，默认使用 persistant_dir/trading.db）
        """
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # 初始化数据库（与 persistant_dir 保持一致）
        if db_path is None:
            # 数据库文件放在 persistant_dir 目录下
            db_path = str(Path(config.option_monitor.persistant_dir) / 'trading.db')
        self.db = DatabaseManager(db_path)
        self.logger.info(f"数据库路径: {db_path}")
        
        # 初始化期权监控器
        self.option_monitor = OptionMonitor(
            watch_dir=config.option_monitor.watch_dir,
            persistant_dir=config.option_monitor.persistant_dir,
            db=self.db  # 传递数据库实例
        )
        
        # 初始化策略（根据配置动态加载）
        self.strategy_name = config.raw_config.get('strategy', {}).get('name', 'v6')
        
        # 动态导入策略模块
        if self.strategy_name == 'v6':
            from strategy.v6 import StrategyV6 as StrategyClass
        elif self.strategy_name == 'v7':
            from strategy.v7 import StrategyV7 as StrategyClass
        else:
            self.logger.error(f"未知策略: {self.strategy_name}，使用默认 v6")
            from strategy.v6 import StrategyV6 as StrategyClass
            self.strategy_name = 'v6'
        
        # 使用配置对象中保存的原始配置字典
        strategy_context = StrategyContext(
            cfg=config.raw_config,  # 使用完整配置字典
            logger=logging.getLogger(f'Strategy{self.strategy_name.upper()}')
        )
        self.strategy = StrategyClass(strategy_context)
        self.logger.info(f"策略已加载: {self.strategy_name.upper()}")
        
        # 市场数据客户端
        self.market_client = market_client
        
        # 检查间隔
        self.check_interval = config.system.check_interval
        
        # 初始化对账模块
        strategy_config = {
            'holding_days': config.raw_config.get('strategy', {}).get('holding_days', 6),
            'holding_days_exit_time': config.raw_config.get('strategy', {}).get('holding_days_exit_time', '15:00:00')
        }
        self.reconciliation = DailyReconciliation(
            db=self.db,
            market_client=self.market_client,
            logger=logging.getLogger('Reconciliation'),
            auto_fix=config.system.reconciliation.auto_fix,
            strategy_config=strategy_config
        )
        
        # 对账时间配置
        self.reconciliation_time = config.system.reconciliation.time
        
        # 初始化持仓最高价字典（用于动态止损）
        self.position_highest_prices: Dict[str, float] = {}
        
        # 恢复系统状态
        self._recover_state()
        
        # 在恢复状态后，处理历史数据（此时 processed_files 已从数据库恢复）
        self.logger.info("开始处理历史期权数据...")
        historical_options = self.option_monitor.parse_history_data()
        
        # 将历史期权数据入库（但不生成买入订单，由策略的历史信号过滤器处理）
        if historical_options:
            self.logger.info(f"开始入库 {len(historical_options)} 条历史期权数据...")
            success_count = 0
            for option_data in historical_options:
                try:
                    self._process_signal(option_data)
                    success_count += 1
                except Exception as e:
                    self.logger.error(f"处理历史期权数据失败: {option_data.symbol} {e}")
            
            self.logger.info(f"历史期权数据入库完成: 成功 {success_count}/{len(historical_options)} 条")
        
        self.logger.info(
            f"系统初始化完成 [策略: {self.strategy_name}, 监控: {config.option_monitor.watch_dir}, "
            f"间隔: {self.check_interval}s]"
        )
    
    def _recover_state(self):
        """
        系统启动时恢复状态
        
        恢复内容：
        1. 策略状态（今日交易次数）
        2. 黑名单（过去N个交易日所有买入过的股票，避免短期重复交易）
        3. 已处理文件列表
        4. 持仓信息校验
        """
        # 1. 恢复策略状态（使用美东时间）
        today = get_et_date().isoformat()
        strategy_state = self.db.get_strategy_state(today)
        
        if strategy_state:
            self.strategy.daily_trade_count = strategy_state['daily_trade_count']
        else:
            self._save_strategy_state()
        
        # 2. 从数据库重建黑名单（过去N个交易日所有买入的股票）
        blacklist_days = self.strategy.blacklist_days
        bought_symbols = self.db.get_bought_symbols_last_n_days(days=blacklist_days)
        
        if bought_symbols:
            self.strategy.blacklist = {}
            for record in bought_symbols:
                symbol = record['symbol']
                order_time_str = record['latest_order_time']
                try:
                    order_time = datetime.fromisoformat(order_time_str)
                    self.strategy.blacklist[symbol] = order_time
                except Exception as e:
                    self.logger.warning(f"解析黑名单时间失败 {symbol}: {e}")
            
            self.logger.debug(f"黑名单详情: {list(self.strategy.blacklist.keys())}")
        else:
            self.strategy.blacklist = {}
        
        # 3. 恢复已处理文件列表
        processed_files = self.db.get_processed_files()
        self.option_monitor.processed_files = set(processed_files)
        
        # 4. 恢复持仓最高价
        db_positions = self.db.get_all_open_positions()
        for pos in db_positions:
            symbol = pos['symbol']
            highest_price = pos.get('highest_price')
            entry_price = pos.get('entry_price', 0)
            
            # 初始化最高价为 max(entry_price, highest_price from DB)
            if highest_price and highest_price > 0:
                self.position_highest_prices[symbol] = highest_price
            else:
                # 如果数据库没有记录，使用开仓价
                self.position_highest_prices[symbol] = entry_price
            
            self.logger.debug(f"恢复 {symbol} 最高价: ${self.position_highest_prices[symbol]:.2f}")
        
        # 校验持仓信息
        db_positions = self.db.get_all_open_positions()
        futu_positions = self.market_client.get_positions()
        
        # 详细持仓信息记录到 DEBUG
        if db_positions:
            position_summary = [f"{p['symbol']}({p['shares']}股)" for p in db_positions]
            self.logger.debug(f"数据库持仓: {position_summary}")
        
        # 对账检查（只有差异时才输出 WARNING）
        if futu_positions:
            futu_symbols = {p['symbol'] for p in futu_positions}
            db_symbols = {p['symbol'] for p in db_positions}
            
            missing_in_db = futu_symbols - db_symbols
            if missing_in_db:
                self.logger.warning(f"持仓对账差异: Futu有但数据库无 {missing_in_db}（可能非策略持仓）")
            
            missing_in_futu = db_symbols - futu_symbols
            if missing_in_futu:
                self.logger.warning(f"持仓对账差异: 数据库有但Futu无 {missing_in_futu}（可能已手动平仓）")
        
        # 一行总结
        self.logger.info(
            f"系统状态恢复完成: 交易次数={self.strategy.daily_trade_count}, "
            f"黑名单={len(self.strategy.blacklist)}, "
            f"已处理文件={len(processed_files)}, "
            f"持仓={len(db_positions)}"
        )
    
    def _save_strategy_state(self):
        """保存策略状态到数据库（使用美东时间）"""
        today = get_et_date().isoformat()
        
        # 将 blacklist 中的 datetime 对象转换为 ISO 格式字符串（JSON 可序列化）
        blacklist_serializable = {
            symbol: dt.isoformat() if isinstance(dt, datetime) else dt
            for symbol, dt in self.strategy.blacklist.items()
        }
        
        state_data = {
            'strategy_name': f'Strategy{self.strategy_name.upper()}',
            'daily_trade_count': self.strategy.daily_trade_count,
            'daily_position_ratio': 0.0,  # 已废弃，保留字段兼容性
            'blacklist': blacklist_serializable
        }
        self.db.save_strategy_state(today, state_data)
    
    def monitor(self):
        """
        主监控循环
        
        流程：
        1. 监控新的期权交易数据
        2. 将数据传递给策略判断是否买入
        3. 执行买入操作
        4. 检查持仓，执行卖出操作
        5. 每日17:00执行对账
        """
        self.strategy.on_start()
        last_date = get_et_date()
        self.strategy.on_day_open(last_date)
        
        et_tz = ZoneInfo('America/New_York')
        self.logger.info(f"开始监控 [美东日期: {last_date}]")
        
        # 对账标志位：记录今日是否已对账
        # 启动时检查是否已过17:00
        current_et = datetime.now(et_tz)
        reconciled_today = False
        
        # 如果系统在对账时间后启动，立即执行对账
        reconciliation_time = datetime.strptime(self.reconciliation_time, '%H:%M:%S').time()
        if current_et.time() >= reconciliation_time:
            self.logger.info(
                f"系统启动时间 {current_et.strftime('%H:%M:%S')} 已过对账时间 {self.reconciliation_time}，立即执行对账"
            )
            try:
                reconciliation_result = self.reconciliation.reconcile_daily(last_date)
                if not reconciliation_result['passed']:
                    self.logger.warning("日终对账发现异常，请人工复核！")
                reconciled_today = True
                self.logger.info("今日对账已完成")
            except Exception as e:
                self.logger.error(f"日终对账失败: {e}", exc_info=True)
        
        try:
            while True:
                current_et = datetime.now(et_tz)
                current_date = current_et.date()
                
                # 检查是否换日（使用美东时间判断）
                if current_date != last_date:
                    self.logger.info(
                        f"换日检测: {last_date} → {current_date} "
                        f"[ET: {current_et.strftime('%Y-%m-%d %H:%M:%S %Z')}]"
                    )
                    
                    # 结束上一个交易日
                    self.strategy.on_day_close(last_date)
                    
                    # 开始新交易日
                    self.strategy.on_day_open(current_date)
                    
                    # 重置策略状态
                    self.strategy.daily_trade_count = 0
                    self._save_strategy_state()
                    
                    # 重置对账标志位
                    reconciled_today = False
                    
                    last_date = current_date
                
                # 检查是否到达对账时间
                if not reconciled_today and current_et.time() >= reconciliation_time:
                    self.logger.info(
                        f"到达对账时间 {self.reconciliation_time} [ET: {current_et.strftime('%Y-%m-%d %H:%M:%S')}]"
                    )
                    
                    # 执行当日对账
                    try:
                        self.logger.info(f"开始对 {current_date} 进行日终对账...")
                        reconciliation_result = self.reconciliation.reconcile_daily(current_date)
                        if not reconciliation_result['passed']:
                            self.logger.warning("日终对账发现异常，请人工复核！")
                        
                        # 标记为已对账
                        reconciled_today = True
                        self.logger.info("今日对账已完成")
                        
                    except Exception as e:
                        self.logger.error(f"日终对账失败: {e}", exc_info=True)
                
                # 1. 监控新的期权交易数据
                new_options = self.option_monitor.monitor_one_round()
                
                if new_options:
                    # 汇总新信号的股票代码
                    symbols = [opt.symbol for opt in new_options]
                    unique_symbols = sorted(set(symbols))
                    
                    self.logger.info(
                        f"收到新信号: {len(new_options)}条 "
                        f"涉及股票: {', '.join(unique_symbols)}"
                    )
                    
                    # 2. 处理每条新数据，判断是否买入
                    for option_data in new_options:
                        self._process_signal(option_data)
                
                # 3. 检查持仓，判断是否卖出
                self._check_positions()
                
                # 等待下一轮
                self.logger.debug(f"等待 {self.check_interval} 秒...")
                time.sleep(self.check_interval)
                
        except KeyboardInterrupt:
            self.logger.info("\n收到停止信号，正在关闭系统...")
            self.strategy.on_day_close(get_et_date())
            self.strategy.on_shutdown()
        except Exception as e:
            self.logger.error(f"系统运行异常: {e}", exc_info=True)
            raise
    
    def _process_signal(self, option_data):
        """
        处理期权信号
        
        Args:
            option_data: 期权交易数据（OptionData 对象）
        """
        try:
            self.logger.info(f"[_process_signal] 开始处理信号: symbol={option_data.symbol}, premium=${option_data.premium:,.0f}, time={option_data.time}")
            
            # 标准化股票代码（美股市场）
            standardized_symbol = normalize_symbol(option_data.symbol, market='US')
            
            # 生成信号ID（使用标准化的symbol）
            signal_id = f"{standardized_symbol}_{option_data.time.strftime('%Y%m%d%H%M%S')}_{option_data.side}"
            
            # 保存信号到数据库（使用标准化的symbol）
            signal_data = {
                'signal_id': signal_id,
                'symbol': standardized_symbol,  # 使用标准化的symbol
                'option_type': option_data.option_type,
                'contract': option_data.contract,
                'side': option_data.side,
                'premium': option_data.premium,
                'stock_price': option_data.stock_price,  # 保存期权数据中的股票价格
                'signal_time': option_data.time.isoformat(),
                'processed': False,
                'meta': option_data.metadata if option_data.metadata else {}  # 保存 metadata（包含历史数据）
            }
            self.db.save_signal(signal_data)
            
            # 转换为 SignalEvent
            signal = self._convert_to_signal(option_data)
            
            # 调用策略判断（返回决策和过滤原因）
            decision, filter_reason = self.strategy.on_signal(signal, self.market_client)
            
            if decision:
                self.logger.info(
                    f"买入决策: {decision.symbol} {decision.shares}股 @${decision.price_limit:.2f} "
                    f"(仓位{decision.pos_ratio:.1%})"
                )
                
                # 执行买入
                self._execute_buy(decision, signal_id)
                
                # 更新信号状态：生成了订单
                self.db.update_signal_processed(
                    signal_id, 
                    generated_order=True, 
                    order_id=decision.client_id
                )
            else:
                # 使用策略返回的详细过滤原因
                filter_reason = filter_reason or "策略过滤(未知原因)"
                self.logger.info(f"信号被过滤: {option_data.symbol} - {filter_reason}")
                # 更新信号状态：未通过过滤，并记录详细原因
                self.db.update_signal_processed(
                    signal_id, 
                    generated_order=False,
                    filter_reason=filter_reason
                )
                
        except Exception as e:
            self.logger.error(f"处理信号失败: {e}", exc_info=True)
    
    def _convert_to_signal(self, option_data) -> SignalEvent:
        """
        将 OptionData 转换为 SignalEvent
        
        Args:
            option_data: OptionData 对象
            
        Returns:
            SignalEvent
        """
        # 标准化股票代码（美股市场）
        standardized_symbol = normalize_symbol(option_data.symbol, market='US')
        
        return SignalEvent(
            event_id=f"{standardized_symbol}_{option_data.time.strftime('%Y%m%d%H%M%S')}",
            symbol=standardized_symbol,  # 使用标准化的symbol
            premium_usd=option_data.premium,
            ask=None,  # ask 字段已从 OptionData 中移除
            chain_id=option_data.contract,
            event_time_cn=option_data.time,  # 已经是北京时间转换后的ET时间
            event_time_et=option_data.time if hasattr(option_data.time, 'tzinfo') else 
                         option_data.time.replace(tzinfo=ZoneInfo('America/New_York')),
            stock_price=option_data.stock_price,  # 传递期权数据中的股票价格
            metadata=option_data.metadata  # 传递元数据（包含历史期权数据）
        )
    
    def _execute_buy(self, decision, signal_id=None):
        """
        执行买入操作
        
        Args:
            decision: EntryDecision 对象
            signal_id: 关联的信号ID（可选）
        """
        try:
            self.logger.info(f"[_execute_buy] 开始执行买入: symbol={decision.symbol}, shares={decision.shares}, price=${decision.price_limit:.2f}, client_id={decision.client_id}")
            
            # 标准化股票代码（确保包含市场前缀，如 US.AAPL）
            standardized_symbol = normalize_symbol(decision.symbol, market='US')
            self.logger.debug(f"[_execute_buy] 标准化符号: {decision.symbol} → {standardized_symbol}")
            
            # 使用市价单提高成交率
            self.logger.debug(f"[_execute_buy] 调用 market_client.buy_stock(): symbol={decision.symbol}, qty={decision.shares}")
            order_id = self.market_client.buy_stock(
                symbol=decision.symbol,  # Futu API内部也会标准化，这里保持兼容
                quantity=decision.shares,
                price=None,  # 市价单不需要指定价格
                order_type='MARKET'
            )
            self.logger.debug(f"[_execute_buy] buy_stock 返回: order_id={order_id} (type: {type(order_id)})")
            
            if order_id:
                self.logger.info(f"买入订单已提交: {standardized_symbol} [ID: {order_id}]")
                
                # 获取订单时间
                order_time_str = decision.t_exec_et.isoformat() if hasattr(decision, 't_exec_et') else datetime.now(ZoneInfo('America/New_York')).isoformat()
                order_time_dt = datetime.fromisoformat(order_time_str)
                
                # 立即将股票加入黑名单（使用标准化的symbol）
                if order_time_dt.tzinfo is None:
                    order_time_dt = order_time_dt.replace(tzinfo=ZoneInfo('America/New_York'))
                self.strategy.blacklist[standardized_symbol] = order_time_dt
                self.logger.debug(f"黑名单更新: {standardized_symbol} 加入黑名单，买入时间: {order_time_dt}")
                
                # 保存订单记录（使用标准化的symbol）
                order_data = {
                    'order_id': decision.client_id,
                    'symbol': standardized_symbol,  # 使用标准化的symbol
                    'order_type': 'BUY',
                    'order_time': order_time_str,
                    'shares': decision.shares,
                    'price': decision.price_limit,  # 估算价格，实际成交价由市价单确定
                    'status': 'PENDING',
                    'signal_id': signal_id,
                    'pos_ratio': decision.pos_ratio,
                    'meta': decision.meta if hasattr(decision, 'meta') else {}
                }
                self.logger.debug(f"[_execute_buy] 保存订单到数据库: {order_data}")
                self.db.save_order(order_data)
                self.logger.info(f"[_execute_buy] 订单已保存: client_id={decision.client_id}")
                
                # 保存持仓记录（使用标准化的symbol）
                position_data = {
                    'symbol': standardized_symbol,  # 使用标准化的symbol
                    'shares': decision.shares,
                    'entry_time': order_data['order_time'],
                    'entry_price': decision.price_limit,  # 估算价格，待成交后更新
                    'entry_order_id': decision.client_id,
                    'signal_id': signal_id,
                    'target_profit_price': decision.price_limit * (1 + self.strategy.take_profit),
                    'stop_loss_price': decision.price_limit * (1 - self.strategy.stop_loss),
                    'highest_price': decision.price_limit,  # 初始最高价 = 买入价
                    'status': 'OPEN'
                }
                self.db.save_position(position_data)
                
                # 初始化最高价（从买入价开始）
                self.position_highest_prices[standardized_symbol] = decision.price_limit
                self.logger.info(f"记录 {standardized_symbol} 买入价（初始最高价）: ${decision.price_limit:.2f}")
                
                # 更新日交易计数
                self.strategy.daily_trade_count += 1
                self.logger.debug(f"日交易计数更新: {self.strategy.daily_trade_count}")
                
                # 保存策略状态（包括更新后的黑名单和交易计数）
                self._save_strategy_state()
                
            else:
                self.logger.error(f"买入订单提交失败: {decision.symbol}")
                
        except Exception as e:
            self.logger.error(f"[_execute_buy] 执行买入异常: {type(e).__name__}: {str(e)}", exc_info=True)
    
    def _check_positions(self):
        """
        检查持仓，判断是否需要卖出
        """
        try:
            # 获取所有未成交的卖单（全局去重保护）
            pending_sell_symbols = set()
            try:
                pending_orders = self.market_client.get_order_list(status_filter='PENDING')
                if pending_orders:
                    pending_sell_symbols = {
                        order['symbol'] for order in pending_orders 
                        if order['side'] == 'SELL'
                    }
                    if pending_sell_symbols:
                        self.logger.debug(f"未成交卖单: {pending_sell_symbols}")
            except Exception as e:
                self.logger.warning(f"查询未成交订单失败: {e}")
            
            # 从数据库获取持仓的开仓时间信息和最高价
            db_positions = self.db.get_all_open_positions()
            entry_time_map = {
                pos['symbol']: pos['entry_time'] 
                for pos in db_positions
            }
            
            # 创建最高价映射（从数据库）
            highest_price_map = {
                pos['symbol']: pos.get('highest_price', pos.get('entry_price', 0))
                for pos in db_positions
            }
            
            # 调用策略检查持仓
            exit_decisions = self.strategy.on_position_check(
                self.market_client, 
                entry_time_map=entry_time_map,
                highest_price_map=highest_price_map
            )
            
            # 更新所有持仓的最高价到数据库
            self._update_positions_highest_price(self.market_client, db_positions)
            
            if exit_decisions:
                for decision in exit_decisions:
                    # 双重保护：再次检查是否有未成交订单
                    if decision.symbol in pending_sell_symbols:
                        self.logger.debug(f"跳过 {decision.symbol}: 已有未成交卖单")
                        continue
                    
                    self.logger.info(f"卖出决策: {decision.symbol} {decision.shares}股 [{decision.reason}]")
                    self._execute_sell(decision)
                
        except Exception as e:
            self.logger.error(f"检查持仓失败: {e}", exc_info=True)
    
    def _execute_sell(self, decision):
        """
        执行卖出操作
        
        Args:
            decision: ExitDecision 对象
        """
        try:
            # 标准化股票代码（确保包含市场前缀）
            standardized_symbol = normalize_symbol(decision.symbol, market='US')
            
            # 使用市价单提高成交率（与买入保持一致）
            order_id = self.market_client.sell_stock(
                symbol=decision.symbol,  # Futu API内部也会标准化
                quantity=decision.shares,
                price=None,  # 市价单不需要指定价格
                order_type='MARKET'
            )
            
            if order_id:
                # 1. 获取买入订单信息（计算盈亏）- 使用标准化symbol查询
                buy_orders = self.db.get_orders_by_symbol(standardized_symbol, 'BUY')
                entry_order = buy_orders[0] if buy_orders else None
                
                # 2. 保存卖出订单（使用标准化symbol）
                order_data = {
                    'order_id': decision.client_id,
                    'symbol': standardized_symbol,  # 使用标准化的symbol
                    'order_type': 'SELL',
                    'order_time': decision.t_exec_et.isoformat() if hasattr(decision, 't_exec_et') else datetime.now(ZoneInfo('America/New_York')).isoformat(),
                    'shares': decision.shares,
                    'price': decision.price_limit,  # 估算价格（市场当前价），实际成交价由市价单确定
                    'status': 'PENDING',
                    'related_order_id': entry_order['order_id'] if entry_order else None,
                    'reason': decision.reason,
                    'meta': decision.meta if hasattr(decision, 'meta') else {}
                }
                self.db.save_order(order_data)
                
                # 3. 计算并保存预估盈亏（基于当前市场价格）
                if entry_order:
                    pnl_amount = (decision.price_limit - entry_order['price']) * decision.shares
                    pnl_ratio = (decision.price_limit - entry_order['price']) / entry_order['price']
                    self.db.update_order_pnl(decision.client_id, pnl_amount, pnl_ratio)
                    
                    self.logger.info(
                        f"卖出订单已提交: {standardized_symbol} [ID: {order_id}] "
                        f"盈亏=${pnl_amount:+.2f} ({pnl_ratio:+.1%})"
                    )
                else:
                    self.logger.info(f"卖出订单已提交: {standardized_symbol} [ID: {order_id}]")
                
                # 4. 更新持仓状态 - 使用标准化symbol
                self.db.close_position(standardized_symbol)
                
            else:
                self.logger.error(f"卖出订单提交失败: {decision.symbol}")
                
        except Exception as e:
            self.logger.error(f"执行卖出失败: {e}", exc_info=True)
        
    def _update_positions_highest_price(self, market_client: FutuClient, db_positions: list):
        """
        更新数据库中所有持仓的最高价。
        
        Args:
            market_client: 市场数据客户端
            db_positions: 从数据库获取的持仓列表
        """
        for pos in db_positions:
            symbol = pos['symbol']
            try:
                # 获取当前市场价格
                price_info = market_client.get_stock_price(symbol)
                if price_info and price_info.get('last_price', 0) > 0:
                    current_price = price_info['last_price']
                    self.db.update_position_highest_price(symbol, current_price)
                else:
                    self.logger.debug(f"无法获取 {symbol} 有效价格，跳过更新最高价")
            except Exception as e:
                self.logger.warning(f"获取 {symbol} 价格失败: {e}")


if __name__ == "__main__":
    import argparse
    import os
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='交易系统')
    parser.add_argument(
        '--config', '-c',
        type=str,
        default=None,
        help='配置文件路径 (默认: 项目根目录的 config.yaml)'
    )
    args = parser.parse_args()
    
    # 确定配置文件路径（优先级：命令行参数 > 环境变量 > 默认路径）
    if args.config:
        config_path = Path(args.config)
    elif os.environ.get('TRADING_CONFIG_PATH'):
        config_path = Path(os.environ['TRADING_CONFIG_PATH'])
    else:
        config_path = Path(__file__).parent.parent.parent / "config.yaml"
    
    # 验证配置文件是否存在
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        print(f"请指定有效的配置文件路径：")
        print(f"  1. 命令行参数: python {sys.argv[0]} --config /path/to/config.yaml")
        print(f"  2. 环境变量: export TRADING_CONFIG_PATH=/path/to/config.yaml")
        sys.exit(1)
    
    # 配置日志
    log_dir = Path(__file__).parent.parent.parent / 'logs'
    log_dir.mkdir(exist_ok=True)  # 确保日志目录存在
    log_file = log_dir / 'trading_system.log'
    
    # 获取 root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # 清除已有的 handlers（避免重复）
    root_logger.handlers.clear()
    
    # 配置日志格式
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 添加文件处理器（总是添加）
    file_handler = logging.FileHandler(str(log_file))
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # 只在前台运行时添加控制台输出
    if sys.stdout.isatty():
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    logger = logging.getLogger(__name__)
    
    try:
        # 加载配置
        logger.info(f"加载配置文件: {config_path}")
        config = SystemConfig(str(config_path))
        
        # 创建市场数据客户端
        logger.info("连接市场数据客户端...")
        market_client = FutuClient(
            host='127.0.0.1',
            port=11111,
            trd_env='SIMULATE',  # 模拟交易
            trd_market='US',
            acc_id=16428245  # 替换为你的账户ID
        )
        
        if not market_client.connect():
            logger.error("市场数据客户端连接失败")
            sys.exit(1)
        
        logger.info("✓ 市场数据客户端连接成功")
        
        try:
            # 启动系统
            system = TradingSystem(config=config, market_client=market_client)
            system.monitor()
        finally:
            # 断开连接
            market_client.disconnect()
            logger.info("市场数据客户端已断开")
            
    except KeyboardInterrupt:
        logger.info("\n程序被用户中断")
    except Exception as e:
        logger.error(f"程序异常退出: {e}", exc_info=True)
        sys.exit(1)