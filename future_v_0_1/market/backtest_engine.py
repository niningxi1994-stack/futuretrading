"""
回测引擎
基于V7策略，使用CSV文件数据进行回测
"""

import csv
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sys
import pytz

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategy.v7 import StrategyV7
from strategy.strategy import StrategyContext, SignalEvent, EntryDecision
from market.backtest_client import BacktestMarketClient


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, csv_dir: str, stock_data_dir: str, config: Dict, initial_cash: float = 100000.0):
        """
        初始化回测引擎
        
        Args:
            csv_dir: 期权CSV文件目录
            stock_data_dir: 股价数据目录
            config: 策略配置
            initial_cash: 初始资金
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.csv_dir = Path(csv_dir)
        self.stock_data_dir = Path(stock_data_dir)
        self.config = config
        self.initial_cash = initial_cash
        
        # 创建模拟市场客户端（传入股价数据目录）
        self.market_client = BacktestMarketClient(
            stock_data_dir=stock_data_dir,
            initial_cash=initial_cash
        )
        
        # 创建策略
        strategy_context = StrategyContext(
            cfg=config,
            logger=logging.getLogger('StrategyV7')
        )
        self.strategy = StrategyV7(strategy_context)
        
        # 读取做空过滤阈值
        self.max_daily_short_premium = config.get('strategy', {}).get('filter', {}).get('max_daily_short_premium', 0)
        self.logger.info(f"做空过滤阈值: ${self.max_daily_short_premium:,.0f} (0=禁用)")
        
        # 股价数据缓存 {symbol: DataFrame}
        self.stock_price_cache: Dict = {}
        
        # 回测结果
        self.trade_records: List[Dict] = []
        self.signal_records: List[Dict] = []
        
        self.logger.info(
            f"回测引擎初始化: CSV目录={csv_dir}, 股价目录={stock_data_dir}, "
            f"初始资金=${initial_cash:,.2f}"
        )
    
    def load_csv_file(self, csv_file: Path) -> Optional[Dict]:
        """
        加载CSV文件
        
        Args:
            csv_file: CSV文件路径
            
        Returns:
            包含历史数据和信号的字典
        """
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            if len(rows) == 0:
                self.logger.warning(f"CSV文件为空: {csv_file}")
                return None
            
            # 最后一行是信号
            signal_row = rows[-1]
            
            # 前面的行是历史数据（用于计算均值）
            history_rows = rows[:-1]
            
            return {
                'file': csv_file,
                'signal': signal_row,
                'history': history_rows,
            }
            
        except Exception as e:
            self.logger.error(f"加载CSV文件失败 {csv_file}: {e}")
            return None
    
    def parse_signal(self, signal_row: Dict) -> Optional[SignalEvent]:
        """
        解析信号（将UTC+8时间转换为ET时间）
        
        Args:
            signal_row: CSV信号行
            
        Returns:
            SignalEvent对象
        """
        try:
            # 提取字段
            symbol = signal_row['underlying_symbol']
            date_str = signal_row['date']
            time_str = signal_row['time']
            premium_str = signal_row['premium'].replace(',', '')
            stock_price_str = signal_row['stock_price']
            contract = signal_row['contract']
            
            # 解析时间（UTC+8北京时间）
            datetime_str = f"{date_str} {time_str}"
            signal_time_cn = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
            
            # clean数据已经是正确日期，直接转换即可
            # 使用pytz设置时区（UTC+8北京时间）
            cn_tz = pytz.timezone('Asia/Shanghai')
            signal_time_cn = cn_tz.localize(signal_time_cn)
            
            # 转换为ET时间（pytz自动处理夏令时/冬令时）
            et_tz = pytz.timezone('America/New_York')
            signal_time_et = signal_time_cn.astimezone(et_tz)
            
            # 解析premium和价格
            premium = float(premium_str)
            stock_price = float(stock_price_str)
            
            # 创建SignalEvent
            signal = SignalEvent(
                event_id=f"{symbol}_{signal_time_et.strftime('%Y%m%d%H%M%S')}",
                symbol=symbol,
                premium_usd=premium,
                ask=stock_price,
                chain_id=contract,
                event_time_cn=signal_time_cn,
                event_time_et=signal_time_et,
            )
            
            return signal
            
        except Exception as e:
            self.logger.error(f"解析信号失败: {e}, 行={signal_row}")
            return None
    
    def load_stock_price_data(self, symbol: str) -> Optional[List[Dict]]:
        """
        加载股票的分钟级价格数据
        
        Args:
            symbol: 股票代码
            
        Returns:
            价格数据列表（已排序）
        """
        # 检查缓存
        if symbol in self.stock_price_cache:
            return self.stock_price_cache[symbol]
        
        # 查找该股票的所有CSV文件
        stock_files = list(self.stock_data_dir.glob(f"{symbol}_*.csv"))
        
        if not stock_files:
            self.logger.warning(f"未找到 {symbol} 的股价数据")
            return None
        
        # 加载并合并所有文件
        all_data = []
        for stock_file in stock_files:
            try:
                with open(stock_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # 解析时间（假设是ET时间）
                        timestamp_str = row['timestamp']
                        dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        et_tz = pytz.timezone('America/New_York')
                        dt_et = et_tz.localize(dt)
                        
                        all_data.append({
                            'timestamp': dt_et,
                            'open': float(row['open']),
                            'high': float(row['high']),
                            'low': float(row['low']),
                            'close': float(row['close']),
                            'volume': float(row['volume']),
                        })
            except Exception as e:
                self.logger.debug(f"加载股价文件失败 {stock_file}: {e}")
        
        if not all_data:
            return None
        
        # 按时间排序
        all_data.sort(key=lambda x: x['timestamp'])
        
        # 缓存
        self.stock_price_cache[symbol] = all_data
        
        self.logger.debug(f"加载 {symbol} 股价数据: {len(all_data)}条")
        return all_data
    
    def get_stock_price_at_time(self, symbol: str, target_time: datetime) -> Optional[float]:
        """
        获取指定时间的股价（使用前一分钟的收盘价）
        
        Args:
            symbol: 股票代码
            target_time: 目标时间
            
        Returns:
            股价（close价格）
        """
        price_data = self.load_stock_price_data(symbol)
        if not price_data:
            return None
        
        # 找到目标时间之前最近的一条数据
        closest_price = None
        for data_point in price_data:
            if data_point['timestamp'] <= target_time:
                closest_price = data_point['close']
            else:
                break
        
        return closest_price
    
    def calculate_historical_premium(self, history_rows: List[Dict]) -> float:
        """
        计算历史premium均值
        
        Args:
            history_rows: 历史数据行
            
        Returns:
            历史premium均值
        """
        if len(history_rows) == 0:
            return 0.0
        
        premiums = []
        for row in history_rows:
            try:
                premium_str = row['premium'].replace(',', '')
                premium = float(premium_str)
                premiums.append(premium)
            except Exception as e:
                self.logger.debug(f"解析历史premium失败: {e}")
        
        if len(premiums) == 0:
            return 0.0
        
        return sum(premiums) / len(premiums)
    
    def has_short_trades_today(self, symbol: str, signal_time: datetime, history_rows: List[Dict]) -> bool:
        """
        检查当天该股票之前做空交易的premium总和是否超过阈值
        
        Args:
            symbol: 股票代码
            signal_time: 当前信号时间
            history_rows: CSV中的历史数据（包含当天之前的记录）
            
        Returns:
            True if 做空premium总和超过阈值, False otherwise
        """
        # 如果阈值为0，禁用此过滤
        if self.max_daily_short_premium <= 0:
            return False
        
        if not history_rows or len(history_rows) == 0:
            return False
        
        # 移除signal_time的时区信息（避免比较时出错）
        if hasattr(signal_time, 'tzinfo') and signal_time.tzinfo is not None:
            signal_time = signal_time.replace(tzinfo=None)
        
        short_premium_sum = 0
        min_premium = 100000  # 只统计premium > 100K的交易
        short_trades_list = []  # 记录做空交易，用于调试
        
        # 检查当天的交易（在信号之前）
        for row in history_rows:
            try:
                # 解析CSV中的时间（北京时间）
                date_str = row['date']
                time_str = row['time']
                
                # 转换成纽约时间（和信号时间一致）
                datetime_str = f"{date_str} {time_str}"
                row_time_cn = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
                
                cn_tz = pytz.timezone('Asia/Shanghai')
                row_time_cn = cn_tz.localize(row_time_cn)
                et_tz = pytz.timezone('America/New_York')
                row_time_et = row_time_cn.astimezone(et_tz).replace(tzinfo=None)
                
                # 只检查当天且在信号之前的交易
                if row_time_et.date() != signal_time.date():
                    continue
                if row_time_et >= signal_time:
                    continue
                
                # 获取premium
                premium_str = str(row.get('premium', '0')).replace(',', '')
                try:
                    premium = float(premium_str)
                except:
                    continue
                
                # 只统计premium > 100K的交易
                if premium <= min_premium:
                    continue
                
                # 检查是否是做空交易
                side = row.get('side', '').upper()
                option_type = row.get('option_type', '').lower()
                
                # 做空交易：ASK PUT（买入看跌）或 BID CALL（卖出看涨）
                if (side == 'ASK' and option_type == 'put') or (side == 'BID' and option_type == 'call'):
                    short_premium_sum += premium
                    short_trades_list.append((row_time_et.strftime('%H:%M'), side, option_type, premium))
                    
            except Exception as e:
                self.logger.debug(f"解析交易时间失败: {e}")
                continue
        
        # 如果做空premium总和超过阈值，过滤
        if short_premium_sum > self.max_daily_short_premium:
            trades_detail = ', '.join([f"{t} {s} {ot.upper()} ${p:,.0f}" for t, s, ot, p in short_trades_list[:3]])
            if len(short_trades_list) > 3:
                trades_detail += f" ...等{len(short_trades_list)}笔"
            self.logger.info(
                f"过滤: {symbol} 当天做空premium总和${short_premium_sum:,.0f} > ${self.max_daily_short_premium:,.0f} ({trades_detail})"
            )
            return True
        
        return False
    
    def check_historical_filter(self, signal_premium: float, history_rows: List[Dict]) -> bool:
        """
        检查历史premium过滤
        
        Args:
            signal_premium: 信号的premium
            history_rows: 历史数据行
            
        Returns:
            True=通过过滤, False=不通过
        """
        if len(history_rows) == 0:
            self.logger.debug("无历史数据，允许交易（容错）")
            return True
        
        avg_premium = self.calculate_historical_premium(history_rows)
        multiplier = self.strategy.historical_premium_multiplier
        threshold = avg_premium * multiplier
        
        if signal_premium > threshold:  # 严格大于，不包含等于
            self.logger.debug(
                f"✓ 历史过滤通过: 当前${signal_premium:,.0f} > "
                f"{multiplier}x历史均值${threshold:,.0f}"
            )
            return True
        else:
            self.logger.info(
                f"过滤: 历史Premium不足 当前${signal_premium:,.0f} <= "
                f"{multiplier}x历史均值${threshold:,.0f}"
            )
            return False
    
    def run_backtest(self, max_files: Optional[int] = None):
        """
        运行回测（时间驱动架构）
        
        流程：
        1. 加载所有信号和股价数据
        2. 按时间顺序遍历每一分钟
        3. 每分钟检查所有持仓的止盈止损
        4. 如果该分钟有新信号，处理开仓
        
        Args:
            max_files: 最大文件数（用于测试）
        """
        # === 第一步：加载所有信号数据 ===
        self.logger.info("加载期权信号数据...")
        csv_files = list(self.csv_dir.glob("*.csv"))
        
        signals_data = []
        for csv_file in csv_files:
            data = self.load_csv_file(csv_file)
            if data:
                signal = self.parse_signal(data['signal'])
                if signal:
                    signals_data.append({
                        'signal': signal,
                        'history': data['history'],
                        'file': csv_file
                    })
        
        # 按时间排序
        signals_data.sort(key=lambda x: x['signal'].event_time_et)
        
        if max_files:
            signals_data = signals_data[:max_files]
        
        self.logger.info(f"共加载{len(signals_data)}个信号（按时间排序）")
        
        if len(signals_data) == 0:
            self.logger.warning("没有信号数据，回测结束")
            return
        
        # === 第二步：构建时间线（所有需要检查的时间点）===
        self.logger.info("构建时间线...")
        
        # 获取回测时间范围
        start_time = signals_data[0]['signal'].event_time_et
        end_time = signals_data[-1]['signal'].event_time_et
        
        self.logger.info(f"回测时间范围: {start_time} 到 {end_time}")
        
        # 创建信号时间映射 {时间: [信号列表]}
        signals_by_time = {}
        for sig_data in signals_data:
            sig_time = sig_data['signal'].event_time_et
            if sig_time not in signals_by_time:
                signals_by_time[sig_time] = []
            signals_by_time[sig_time].append(sig_data)
        
        # === 第三步：构建完整的时间序列（包含所有分钟）===
        # 收集所有持仓股票，准备获取分钟数据
        all_symbols = set()
        for sig_data in signals_data:
            all_symbols.add(sig_data['signal'].symbol)
        
        self.logger.info(f"预加载{len(all_symbols)}个股票的价格数据...")
        
        # 预加载所有股票的价格数据
        for symbol in all_symbols:
            self.market_client._load_stock_price_data(symbol)
        
        # 获取所有信号时间点
        all_times = sorted(signals_by_time.keys())
        
        # === 第四步：事件驱动回测（只在信号时间检查）===
        # 注意：为了性能，我们在每个信号时间点做两件事：
        # 1. 检查持仓（扫描上个信号到当前信号之间的所有分钟价格）
        # 2. 处理新信号
        
        self.logger.info(f"开始回测: {len(all_times)}个信号时间点")
        
        self.strategy.on_start()
        
        position_entry_times = {}
        current_date = None
        last_check_time = None
        
        # 遍历每个信号时间点
        for time_idx, current_time in enumerate(all_times, 1):
            if time_idx % 100 == 0:
                self.logger.info(f"进度: {time_idx}/{len(all_times)} ({time_idx/len(all_times):.1%})")
            
            # === 检查换日 ===
            signal_date = current_time.date()
            if current_date is None:
                current_date = signal_date
                self.strategy.on_day_open(current_date)
            elif signal_date != current_date:
                # === 换日前，检查前一天15:00的退出（防止当天15:00后无信号） ===
                if len(position_entry_times) > 0 and last_check_time:
                    # 构造前一天15:00的时间点
                    day_end_time = last_check_time.replace(hour=15, minute=0, second=0, microsecond=0)
                    # 如果最后检查时间在15:00之前，需要补充检查15:00
                    if last_check_time.hour < 15 or (last_check_time.hour == 15 and last_check_time.minute == 0):
                        pass  # 已经检查过15:00了
                    else:
                        # 扫描last_check_time到当天收盘
                        self._check_positions_minutely(
                            last_check_time,
                            last_check_time.replace(hour=23, minute=59, second=59),
                            position_entry_times
                        )
                
                self.strategy.on_day_close(current_date)
                self.strategy.daily_trade_count = 0
                current_date = signal_date
                self.strategy.on_day_open(current_date)
            
            # === 设置当前时间（用于处理新信号）===
            self.market_client.set_current_time(current_time)
            
            # === 处理该时间点的所有信号 ===
            if current_time in signals_by_time:
                for sig_data in signals_by_time[current_time]:
                    signal = sig_data['signal']
                    history_rows = sig_data['history']
                    csv_file = sig_data['file']
                    
                    # *** 关键：在处理每个信号前，扫描所有持仓的每一分钟价格 ***
                    if len(position_entry_times) > 0:
                        self._check_positions_minutely(
                            last_check_time if last_check_time else current_time,
                            current_time,
                            position_entry_times
                        )
                        # 更新最后检查时间
                        last_check_time = current_time
            
                    # 检查历史过滤
                    if not self.check_historical_filter(signal.premium_usd, history_rows):
                        self.signal_records.append({
                            'file': csv_file.name,
                            'symbol': signal.symbol,
                            'time': signal.event_time_et,
                            'premium': signal.premium_usd,
                            'price': signal.ask,
                            'decision': 'FILTERED_HISTORICAL',
                            'reason': '历史premium不足',
                        })
                        continue
                    
                    # 检查当天是否有做空交易（ASK PUT 或 BID CALL）
                    if self.has_short_trades_today(signal.symbol, signal.event_time_et, history_rows):
                        self.signal_records.append({
                            'file': csv_file.name,
                            'symbol': signal.symbol,
                            'time': signal.event_time_et,
                            'premium': signal.premium_usd,
                            'price': signal.ask,
                            'decision': 'FILTERED_SHORT',
                            'reason': '当天有做空交易',
                        })
                        continue
                    
                    # 调用策略判断
                    decision = self.strategy.on_signal(signal, self.market_client)
                    
                    if decision:
                        # 记录决策
                        self.signal_records.append({
                            'file': csv_file.name,
                            'symbol': signal.symbol,
                            'time': signal.event_time_et,
                            'premium': signal.premium_usd,
                            'price': signal.ask,
                            'decision': 'BUY',
                            'shares': decision.shares,
                            'position_ratio': decision.pos_ratio,
                        })
                        
                        # 执行买入
                        self._execute_buy(decision, signal)
                        
                        # 记录持仓进入时间
                        position_entry_times[signal.symbol] = signal.event_time_et
                        
                        # 更新策略状态
                        self.strategy.daily_trade_count += 1
                        self.strategy.blacklist[signal.symbol] = signal.event_time_et
                    else:
                        self.signal_records.append({
                            'file': csv_file.name,
                            'symbol': signal.symbol,
                            'time': signal.event_time_et,
                            'premium': signal.premium_usd,
                            'price': signal.ask,
                            'decision': 'FILTERED',
                            'reason': '策略过滤',
                        })
        
        # 回测结束，强制平掉所有剩余持仓
        self._close_all_positions("回测结束")
        
        # 策略关闭
        self.strategy.on_shutdown()
        
        self.logger.info("\n回测完成！")
    
    def _execute_buy(self, decision: EntryDecision, signal: SignalEvent):
        """
        执行买入
        
        Args:
            decision: 买入决策
            signal: 信号
        """
        try:
            # 执行买入
            order_id = self.market_client.buy_stock(
                symbol=decision.symbol,
                quantity=decision.shares,
                price=decision.price_limit,
                order_type='LIMIT'
            )
            
            if order_id:
                # 记录交易
                self.trade_records.append({
                    'type': 'BUY',
                    'symbol': decision.symbol,
                    'time': signal.event_time_et,
                    'shares': decision.shares,
                    'price': decision.price_limit,
                    'amount': decision.shares * decision.price_limit,
                    'premium': signal.premium_usd,
                    'position_ratio': decision.pos_ratio,
                })
                
        except Exception as e:
            self.logger.error(f"执行买入失败: {e}")
    
    def _check_positions_minutely(self, start_time, end_time, position_entry_times):
        """
        逐分钟检查持仓的止盈止损
        
        关键：从entry_time扫描到end_time的所有分钟价格，而非start_time到end_time
        
        Args:
            start_time: 上次检查时间（未使用，保留参数兼容性）
            end_time: 当前时间
            position_entry_times: 持仓进入时间映射
        """
        positions = self.market_client.get_positions()
        if not positions:
            return
        
        # 对每个持仓，从entry_time扫描到当前的所有价格
        for pos in positions:
            symbol = pos['symbol']
            cost_price = pos['cost_price']
            shares = pos['position']
            
            # 必须有entry_time
            if symbol not in position_entry_times:
                continue
            
            entry_time = position_entry_times[symbol]
            
            # 获取该股票的价格数据（DataFrame）
            df = self.market_client._load_stock_price_data(symbol)
            if df is None or len(df) == 0:
                continue
            
            # 去掉时区信息（匹配DataFrame的tz-naive index）
            entry_tz_naive = entry_time.replace(tzinfo=None) if hasattr(entry_time, 'tzinfo') else entry_time
            end_tz_naive = end_time.replace(tzinfo=None) if hasattr(end_time, 'tzinfo') else end_time
            
            # 从entry_time扫描到end_time（使用pandas向量化加速）
            price_data = df[(df.index >= entry_tz_naive) & (df.index <= end_tz_naive)]
            if len(price_data) == 0:
                continue
            
            # 计算计划退出日期（用于定时退出检查）
            entry_time = position_entry_times[symbol]
            entry_tz_naive = entry_time.replace(tzinfo=None) if hasattr(entry_time, 'tzinfo') else entry_time
            planned_exit_date = entry_tz_naive.replace(hour=15, minute=0, second=0, microsecond=0)
            planned_exit_date += timedelta(days=self.strategy.holding_days)
            while planned_exit_date.weekday() >= 5:
                planned_exit_date += timedelta(days=1)
            
            # 向量化计算所有分钟的盈亏比率
            price_data = price_data.copy()
            price_data['pnl_ratio'] = (price_data['close'] - cost_price) / cost_price
            
            # 找到所有触发条件的时刻
            stop_loss_threshold = -self.strategy.stop_loss
            
            # 标记每个条件的触发时刻
            exit_times = []
            
            # 止损触发时刻
            stop_loss_rows = price_data[price_data['pnl_ratio'] <= stop_loss_threshold]
            if len(stop_loss_rows) > 0:
                exit_times.append(('止损', stop_loss_rows.index[0], stop_loss_rows.iloc[0]))
            
            # 止盈触发时刻
            take_profit_rows = price_data[price_data['pnl_ratio'] >= self.strategy.take_profit]
            if len(take_profit_rows) > 0:
                exit_times.append(('止盈', take_profit_rows.index[0], take_profit_rows.iloc[0]))
            
            # 定时退出触发时刻
            time_exit_rows = price_data[price_data.index >= planned_exit_date]
            if len(time_exit_rows) > 0:
                exit_times.append(('定时退出', time_exit_rows.index[0], time_exit_rows.iloc[0]))
            
            # 如果没有任何触发条件，跳过
            if len(exit_times) == 0:
                continue
            
            # 找到最早触发的条件
            exit_times.sort(key=lambda x: x[1])  # 按时间排序
            exit_type, check_time, row_data = exit_times[0]
            current_price = row_data['close']
            pnl_ratio = row_data['pnl_ratio']
            days_held = (check_time.date() - entry_tz_naive.date()).days
            
            # 执行退出
            self.logger.info(
                f"✓ {exit_type}触发: {symbol} {shares}股 @${current_price:.2f} "
                f"时间={check_time.strftime('%Y-%m-%d %H:%M')}, "
                f"持仓{days_held}天, 盈亏{pnl_ratio:+.1%}"
            )
            
            if exit_type == '止损':
                self._execute_sell(symbol, shares, current_price, "止损", check_time)
            elif exit_type == '止盈':
                self._execute_sell(symbol, shares, current_price, "止盈", check_time)
            else:  # 定时退出
                self._execute_sell(symbol, shares, current_price, f"定时退出({days_held}天)", check_time)
            
            if symbol in position_entry_times:
                del position_entry_times[symbol]
    
    def _check_and_exit_positions(self, current_time, position_entry_times):
        """
        检查持仓并决定是否退出（止盈止损或定时退出）
        
        Args:
            current_time: 当前时间
            position_entry_times: 持仓进入时间映射
        """
        positions = self.market_client.get_positions()
        if not positions:
            return
        
        for pos in positions:
            symbol = pos['symbol']
            cost_price = pos['cost_price']
            current_price = pos['market_price']
            shares = pos['position']
            
            # 计算盈亏比例
            pnl_ratio = (current_price - cost_price) / cost_price
            
            # 检查止损
            if pnl_ratio <= -self.strategy.stop_loss:
                self.logger.info(
                    f"✓ 止损平仓: {symbol} {shares}股 @${current_price:.2f}, "
                    f"成本${cost_price:.2f}, 亏损{pnl_ratio:.1%}"
                )
                self._execute_sell(symbol, shares, current_price, "止损", current_time)
                continue
            
            # 检查止盈
            if pnl_ratio >= self.strategy.take_profit:
                self.logger.info(
                    f"✓ 止盈平仓: {symbol} {shares}股 @${current_price:.2f}, "
                    f"成本${cost_price:.2f}, 盈利{pnl_ratio:.1%}"
                )
                self._execute_sell(symbol, shares, current_price, "止盈", current_time)
                continue
            
            # 检查持仓时间（定时退出）- 使用自然日而非交易日
            if symbol in position_entry_times:
                entry_time = position_entry_times[symbol]
                
                # 计算退出日期（入场时间 + holding_days个自然日，跳过周末）
                exit_date = entry_time.replace(hour=15, minute=0, second=0, microsecond=0)
                exit_date += timedelta(days=self.strategy.holding_days)
                
                # 跳过周末
                while exit_date.weekday() >= 5:  # 5=周六, 6=周日
                    exit_date += timedelta(days=1)
                
                # 如果当前时间已过退出日期的15:00，执行平仓
                if (current_time.date() >= exit_date.date() and current_time.hour >= 15):
                    days_held = (current_time.date() - entry_time.date()).days
                    self.logger.info(
                        f"✓ 定时平仓: {symbol} {shares}股 @${current_price:.2f}, "
                        f"持仓{days_held}天, 盈亏{pnl_ratio:+.1%}"
                    )
                    self._execute_sell(symbol, shares, current_price, f"定时退出({days_held}天)", current_time)
                    # 从持仓时间映射中移除
                    del position_entry_times[symbol]
    
    def _execute_sell(self, symbol: str, shares: int, price: float, reason: str, current_time):
        """
        执行卖出
        
        Args:
            symbol: 股票代码
            shares: 数量
            price: 价格
            reason: 卖出原因
            current_time: 当前时间
        """
        try:
            order_id = self.market_client.sell_stock(
                symbol=symbol,
                quantity=shares,
                price=price,
                order_type='LIMIT'
            )
            
            if order_id:
                # 记录交易
                self.trade_records.append({
                    'type': 'SELL',
                    'symbol': symbol,
                    'time': current_time,
                    'shares': shares,
                    'price': price,
                    'amount': shares * price,
                    'reason': reason,
                })
                
        except Exception as e:
            self.logger.error(f"执行卖出失败 {symbol}: {e}")
    
    def _close_all_positions(self, reason: str):
        """
        平掉所有剩余持仓（回测结束时）
        
        Args:
            reason: 平仓原因
        """
        positions = self.market_client.get_positions()
        if not positions:
            return
        
        from datetime import datetime
        et_tz = pytz.timezone('America/New_York')
        current_time = datetime.now(et_tz)
        
        self.logger.info(f"\n{reason}，平掉所有剩余持仓...")
        
        for pos in positions:
            symbol = pos['symbol']
            shares = pos['position']
            
            # 尝试获取股价数据的最新价格
            price_data = self.load_stock_price_data(symbol)
            if price_data and len(price_data) > 0:
                # 使用股价数据的最后一个价格
                price = price_data[-1]['close']
                self.logger.debug(f"使用股价数据最新价格: {symbol} ${price:.2f}")
            else:
                # 使用当前市价
                price = pos['market_price']
                self.logger.debug(f"使用持仓市价: {symbol} ${price:.2f}")
            
            self.logger.info(f"平仓: {symbol} {shares}股 @${price:.2f}")
            self._execute_sell(symbol, shares, price, reason, current_time)
    
    def generate_report(self) -> Dict:
        """
        生成回测报告
        
        Returns:
            报告字典
        """
        summary = self.market_client.get_summary()
        
        # 统计信号
        total_signals = len(self.signal_records)
        buy_signals = len([s for s in self.signal_records if s['decision'] == 'BUY'])
        filtered_signals = total_signals - buy_signals
        
        # 统计交易
        buy_trades = [t for t in self.trade_records if t['type'] == 'BUY']
        
        report = {
            '=== 账户概况 ===': {
                '初始资金': f"${summary['initial_cash']:,.2f}",
                '最终资金': f"${summary['cash']:,.2f}",
                '持仓市值': f"${summary['position_value']:,.2f}",
                '总资产': f"${summary['total_assets']:,.2f}",
                '总盈亏': f"${summary['total_pnl']:+,.2f}",
                '收益率': f"{summary['total_pnl_ratio']:+.2%}",
            },
            '=== 交易统计 ===': {
                '总信号数': total_signals,
                '买入信号': buy_signals,
                '过滤信号': filtered_signals,
                '过滤率': f"{filtered_signals/total_signals:.1%}" if total_signals > 0 else 'N/A',
                '实际交易数': len(buy_trades),
                '持仓数': summary['num_positions'],
            },
            '=== 盈亏分析 ===': {
                '已实现盈亏': f"${summary['realized_pnl']:+,.2f}",
                '未实现盈亏': f"${summary['unrealized_pnl']:+,.2f}",
            },
        }
        
        return report
    
    def print_report(self):
        """打印回测报告"""
        report = self.generate_report()
        
        print("\n" + "="*60)
        print("回测报告")
        print("="*60)
        
        for section_name, section_data in report.items():
            print(f"\n{section_name}")
            for key, value in section_data.items():
                print(f"  {key}: {value}")
        
        print("\n" + "="*60)
        
        # 打印持仓明细
        positions = self.market_client.get_positions()
        if positions:
            print("\n持仓明细:")
            print(f"{'股票':<10} {'数量':<10} {'成本价':<12} {'现价':<12} {'盈亏':<15} {'盈亏率':<10}")
            print("-" * 80)
            for pos in positions:
                print(
                    f"{pos['symbol']:<10} "
                    f"{pos['position']:<10} "
                    f"${pos['cost_price']:<11.2f} "
                    f"${pos['market_price']:<11.2f} "
                    f"${pos['pnl']:+14.2f} "
                    f"{pos['pnl_ratio']:+9.1%}"
                )
        
        print("\n" + "="*60)


if __name__ == '__main__':
    import yaml
    from pathlib import Path
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 读取配置文件
    config_path = Path(__file__).parent.parent.parent / 'config_v7.yaml'
    
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # CSV目录
    csv_dir = Path(__file__).parent.parent / 'database' / 'call_csv_files'
    
    # 创建回测引擎
    engine = BacktestEngine(
        csv_dir=str(csv_dir),
        config=config,
        initial_cash=100000.0
    )
    
    # 运行回测
    engine.run_backtest(max_files=10)  # 测试前10个文件
    
    # 打印报告
    engine.print_report()

