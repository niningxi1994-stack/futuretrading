"""
交易系统主类 - V7策略版本
"""

import time
import sys
import logging
from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.config import SystemConfig
from optionparser.parser import OptionMonitor
from strategy.v7 import StrategyV7  # 使用V7策略
from strategy.strategy import StrategyContext, SignalEvent
from market.futu_client import FutuClient
from database.models import DatabaseManager
from tradingsystem.reconciliation import DailyReconciliation


def get_et_date() -> date:
    """
    获取美东时间的日期
    
    Returns:
        date: 美东时间的日期对象
    """
    et_now = datetime.now(ZoneInfo('America/New_York'))
    return et_now.date()


class TradingSystemV7:
    """交易系统主控 - V7策略版本"""
    
    def __init__(self, config: SystemConfig, market_client: FutuClient, db_path: str = None):
        """
        初始化交易系统
        
        Args:
            config: 系统配置对象
            market_client: 市场数据客户端
            db_path: 数据库路径（可选，默认使用 persistant_dir/trading_v7.db）
        """
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # 初始化数据库（与 persistant_dir 保持一致，使用V7专用数据库）
        if db_path is None:
            db_path = str(Path(config.option_monitor.persistant_dir) / 'trading_v7.db')
        self.db = DatabaseManager(db_path)
        self.logger.info(f"数据库路径: {db_path}")
        
        # 初始化期权监控器
        self.option_monitor = OptionMonitor(
            watch_dir=config.option_monitor.watch_dir,
            persistant_dir=config.option_monitor.persistant_dir,
            db=self.db
        )
        
        # 初始化V7策略
        strategy_context = StrategyContext(
            cfg=config.raw_config,
            logger=logging.getLogger('StrategyV7')
        )
        self.strategy = StrategyV7(strategy_context)
        
        # 市场数据客户端
        self.market_client = market_client
        
        # 检查间隔
        self.check_interval = config.system.check_interval
        
        # 初始化对账模块
        self.reconciliation = DailyReconciliation(
            db=self.db,
            market_client=self.market_client,
            logger=logging.getLogger('Reconciliation'),
            auto_fix=config.system.reconciliation.auto_fix
        )
        
        # 对账时间配置
        self.reconciliation_time = config.system.reconciliation.time
        
        # 恢复系统状态
        self._recover_state()
        
        # 在恢复状态后，处理历史数据
        self.option_monitor.parse_history_data()
        
        self.logger.info(f"系统初始化完成 [监控: {config.option_monitor.watch_dir}, 间隔: {self.check_interval}s]")
    
    def _recover_state(self):
        """
        系统启动时恢复状态
        
        恢复内容：
        1. 策略状态（今日交易次数）
        2. 黑名单（过去N个交易日所有买入过的股票）
        3. 已处理文件列表
        4. 持仓信息校验
        """
        today = get_et_date().isoformat()
        strategy_state = self.db.get_strategy_state(today)
        
        if strategy_state:
            self.strategy.daily_trade_count = strategy_state['daily_trade_count']
        else:
            self._save_strategy_state()
        
        # 从数据库重建黑名单
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
        
        # 恢复已处理文件列表
        processed_files = self.db.get_processed_files()
        self.option_monitor.processed_files = set(processed_files)
        
        # 校验持仓信息
        db_positions = self.db.get_all_open_positions()
        futu_positions = self.market_client.get_positions()
        
        if db_positions:
            position_summary = [f"{p['symbol']}({p['shares']}股)" for p in db_positions]
            self.logger.debug(f"数据库持仓: {position_summary}")
        
        # 对账检查
        if futu_positions:
            futu_symbols = {p['symbol'] for p in futu_positions}
            db_symbols = {p['symbol'] for p in db_positions}
            
            missing_in_db = futu_symbols - db_symbols
            if missing_in_db:
                self.logger.warning(f"持仓对账差异: Futu有但数据库无 {missing_in_db}（可能非策略持仓）")
            
            missing_in_futu = db_symbols - futu_symbols
            if missing_in_futu:
                self.logger.warning(f"持仓对账差异: 数据库有但Futu无 {missing_in_futu}（可能已手动平仓）")
        
        self.logger.info(
            f"系统状态恢复完成: 交易次数={self.strategy.daily_trade_count}, "
            f"黑名单={len(self.strategy.blacklist)}, "
            f"已处理文件={len(processed_files)}, "
            f"持仓={len(db_positions)}"
        )
    
    def _save_strategy_state(self):
        """保存策略状态到数据库"""
        today = get_et_date().isoformat()
        state_data = {
            'strategy_name': 'StrategyV7',
            'daily_trade_count': self.strategy.daily_trade_count,
            'daily_position_ratio': 0.0,
            'blacklist': self.strategy.blacklist
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
        
        # 对账标志位
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
                
                # 检查是否换日
                if current_date != last_date:
                    self.logger.info(
                        f"换日检测: {last_date} → {current_date} "
                        f"[ET: {current_et.strftime('%Y-%m-%d %H:%M:%S %Z')}]"
                    )
                    
                    self.strategy.on_day_close(last_date)
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
                    
                    try:
                        self.logger.info(f"开始对 {current_date} 进行日终对账...")
                        reconciliation_result = self.reconciliation.reconcile_daily(current_date)
                        if not reconciliation_result['passed']:
                            self.logger.warning("日终对账发现异常，请人工复核！")
                        
                        reconciled_today = True
                        self.logger.info("今日对账已完成")
                        
                    except Exception as e:
                        self.logger.error(f"日终对账失败: {e}", exc_info=True)
                
                # 1. 监控新的期权交易数据
                new_options = self.option_monitor.monitor_one_round()
                
                if new_options:
                    self.logger.info(f"发现新信号: {len(new_options)} 条")
                    
                    # 2. 处理每条新数据
                    for option_data in new_options:
                        self._process_signal(option_data)
                
                # 3. 检查持仓
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
        """处理期权信号"""
        try:
            signal_id = f"{option_data.symbol}_{option_data.time.strftime('%Y%m%d%H%M%S')}_{option_data.side}"
            
            # 保存信号到数据库
            signal_data = {
                'signal_id': signal_id,
                'symbol': option_data.symbol,
                'option_type': option_data.option_type,
                'contract': option_data.contract,
                'side': option_data.side,
                'premium': option_data.premium,
                'signal_time': option_data.time.isoformat(),
                'processed': False,
                'meta': {
                    'ask': option_data.ask,
                    'strike': option_data.strike,
                }
            }
            self.db.save_signal(signal_data)
            
            # 转换为 SignalEvent
            signal = self._convert_to_signal(option_data)
            
            # 调用策略判断
            decision = self.strategy.on_signal(signal, self.market_client)
            
            if decision:
                self.logger.info(
                    f"买入决策: {decision.symbol} {decision.shares}股 @${decision.price_limit:.2f} "
                    f"(仓位{decision.pos_ratio:.1%})"
                )
                
                # 执行买入
                self._execute_buy(decision, signal_id)
                
                # 更新信号状态
                self.db.update_signal_processed(
                    signal_id, 
                    generated_order=True, 
                    order_id=decision.client_id
                )
            else:
                self.logger.debug(f"信号被过滤: {option_data.symbol}")
                self.db.update_signal_processed(
                    signal_id, 
                    generated_order=False,
                    filter_reason="策略过滤"
                )
                
        except Exception as e:
            self.logger.error(f"处理信号失败: {e}", exc_info=True)
    
    def _convert_to_signal(self, option_data) -> SignalEvent:
        """将 OptionData 转换为 SignalEvent"""
        return SignalEvent(
            event_id=f"{option_data.symbol}_{option_data.time.strftime('%Y%m%d%H%M%S')}",
            symbol=option_data.symbol,
            premium_usd=option_data.premium,
            ask=option_data.ask,
            chain_id=option_data.contract,
            event_time_cn=option_data.time,
            event_time_et=option_data.time if hasattr(option_data.time, 'tzinfo') else 
                         option_data.time.replace(tzinfo=ZoneInfo('America/New_York'))
        )
    
    def _execute_buy(self, decision, signal_id=None):
        """执行买入操作"""
        try:
            order_id = self.market_client.buy_stock(
                symbol=decision.symbol,
                quantity=decision.shares,
                price=decision.price_limit,
                order_type='LIMIT'
            )
            
            if order_id:
                self.logger.info(f"买入订单已提交: {decision.symbol} [ID: {order_id}]")
                
                # 获取订单时间
                order_time_str = decision.t_exec_et.isoformat() if hasattr(decision, 't_exec_et') else datetime.now(ZoneInfo('America/New_York')).isoformat()
                order_time_dt = datetime.fromisoformat(order_time_str)
                
                # 加入黑名单
                if order_time_dt.tzinfo is None:
                    order_time_dt = order_time_dt.replace(tzinfo=ZoneInfo('America/New_York'))
                self.strategy.blacklist[decision.symbol] = order_time_dt
                self.logger.debug(f"黑名单更新: {decision.symbol} 加入黑名单")
                
                # 保存订单记录
                order_data = {
                    'order_id': decision.client_id,
                    'symbol': decision.symbol,
                    'order_type': 'BUY',
                    'order_time': order_time_str,
                    'shares': decision.shares,
                    'price': decision.price_limit,
                    'status': 'PENDING',
                    'signal_id': signal_id,
                    'pos_ratio': decision.pos_ratio,
                    'meta': decision.meta if hasattr(decision, 'meta') else {}
                }
                self.db.save_order(order_data)
                
                # 保存持仓记录
                position_data = {
                    'symbol': decision.symbol,
                    'shares': decision.shares,
                    'entry_time': order_data['order_time'],
                    'entry_price': decision.price_limit,
                    'entry_order_id': decision.client_id,
                    'signal_id': signal_id,
                    'target_profit_price': decision.price_limit * (1 + self.strategy.take_profit),
                    'stop_loss_price': decision.price_limit * (1 - self.strategy.stop_loss),
                    'status': 'OPEN'
                }
                self.db.save_position(position_data)
                
                # 更新日交易计数
                self.strategy.daily_trade_count += 1
                self.logger.debug(f"日交易计数更新: {self.strategy.daily_trade_count}")
                
                # 保存策略状态
                self._save_strategy_state()
                
            else:
                self.logger.error(f"买入订单提交失败: {decision.symbol}")
                
        except Exception as e:
            self.logger.error(f"执行买入失败: {e}", exc_info=True)
    
    def _check_positions(self):
        """检查持仓，判断是否需要卖出"""
        try:
            # 获取未成交卖单（全局去重保护）
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
            
            # 从数据库获取持仓开仓时间
            db_positions = self.db.get_all_open_positions()
            entry_time_map = {
                pos['symbol']: pos['entry_time'] 
                for pos in db_positions
            }
            
            # 调用策略检查持仓
            exit_decisions = self.strategy.on_position_check(
                self.market_client, 
                entry_time_map=entry_time_map
            )
            
            if exit_decisions:
                for decision in exit_decisions:
                    # 双重保护：检查是否有未成交订单
                    if decision.symbol in pending_sell_symbols:
                        self.logger.debug(f"跳过 {decision.symbol}: 已有未成交卖单")
                        continue
                    
                    self.logger.info(f"卖出决策: {decision.symbol} {decision.shares}股 [{decision.reason}]")
                    self._execute_sell(decision)
                
        except Exception as e:
            self.logger.error(f"检查持仓失败: {e}", exc_info=True)
    
    def _execute_sell(self, decision):
        """执行卖出操作"""
        try:
            order_id = self.market_client.sell_stock(
                symbol=decision.symbol,
                quantity=decision.shares,
                price=decision.price_limit,
                order_type='LIMIT'
            )
            
            if order_id:
                # 获取买入订单信息
                buy_orders = self.db.get_orders_by_symbol(decision.symbol, 'BUY')
                entry_order = buy_orders[0] if buy_orders else None
                
                # 保存卖出订单
                order_data = {
                    'order_id': decision.client_id,
                    'symbol': decision.symbol,
                    'order_type': 'SELL',
                    'order_time': decision.t_exec_et.isoformat() if hasattr(decision, 't_exec_et') else datetime.now(ZoneInfo('America/New_York')).isoformat(),
                    'shares': decision.shares,
                    'price': decision.price_limit,
                    'status': 'PENDING',
                    'related_order_id': entry_order['order_id'] if entry_order else None,
                    'reason': decision.reason,
                    'meta': decision.meta if hasattr(decision, 'meta') else {}
                }
                self.db.save_order(order_data)
                
                # 计算并保存盈亏
                if entry_order:
                    pnl_amount = (decision.price_limit - entry_order['price']) * decision.shares
                    pnl_ratio = (decision.price_limit - entry_order['price']) / entry_order['price']
                    self.db.update_order_pnl(decision.client_id, pnl_amount, pnl_ratio)
                    
                    self.logger.info(
                        f"卖出订单已提交: {decision.symbol} [ID: {order_id}] "
                        f"盈亏=${pnl_amount:+.2f} ({pnl_ratio:+.1%})"
                    )
                else:
                    self.logger.info(f"卖出订单已提交: {decision.symbol} [ID: {order_id}]")
                
                # 更新持仓状态
                self.db.close_position(decision.symbol)
                
            else:
                self.logger.error(f"卖出订单提交失败: {decision.symbol}")
                
        except Exception as e:
            self.logger.error(f"执行卖出失败: {e}", exc_info=True)


if __name__ == "__main__":
    import argparse
    import os
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='交易系统 (StrategyV7)')
    parser.add_argument(
        '--config', '-c',
        type=str,
        default=None,
        help='配置文件路径 (默认: 项目根目录的 config_v7.yaml)'
    )
    args = parser.parse_args()
    
    # 确定配置文件路径
    if args.config:
        config_path = Path(args.config)
    elif os.environ.get('TRADING_CONFIG_PATH'):
        config_path = Path(os.environ['TRADING_CONFIG_PATH'])
    else:
        config_path = Path(__file__).parent.parent.parent / "config_v7.yaml"
    
    # 验证配置文件
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        print(f"请指定有效的配置文件路径：")
        print(f"  1. 命令行参数: python {sys.argv[0]} --config /path/to/config_v7.yaml")
        print(f"  2. 环境变量: export TRADING_CONFIG_PATH=/path/to/config_v7.yaml")
        sys.exit(1)
    
    # 配置日志
    log_dir = Path(__file__).parent.parent.parent / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / 'trading_system_v7.log'
    
    # 获取 root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    
    # 配置日志格式
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 添加文件处理器
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
            system = TradingSystemV7(config=config, market_client=market_client)
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

