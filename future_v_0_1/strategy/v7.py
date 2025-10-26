"""
V7 事件驱动期权流动量策略 - 支持高杠杆的中长线期权流策略

核心特性：
见config_v7.yaml
"""

import logging
import csv
import pandas as pd
import pytz
from datetime import date, datetime, time, timedelta
from typing import Optional, Dict
from zoneinfo import ZoneInfo
from pathlib import Path

try:
    from .strategy import StrategyBase, StrategyContext, EntryDecision, ExitDecision
except ImportError:
    from strategy import StrategyBase, StrategyContext, EntryDecision, ExitDecision


class StrategyV7(StrategyBase):
    """V7 事件驱动期权流动量策略"""
    
    def __init__(self, context: StrategyContext):
        super().__init__(context)
        
        # 读取 strategy 配置
        strategy_cfg = self.cfg.get('strategy', {})
        
        # === 入场配置 ===
        filter_cfg = strategy_cfg.get('filter', {})
        self.trade_start_time = filter_cfg.get('trade_start_time', '10:00:00')  # 交易开始时间
        self.entry_delay = filter_cfg.get('entry_delay', 2)  # 信号后延迟分钟数
        self.min_option_premium = filter_cfg.get('min_option_premium', 100000)  # 最小期权溢价
        self.market_close_buffer = filter_cfg.get('market_close_buffer', 6)  # 距离收盘缓冲时间（分钟）
        
        # 历史Premium过滤
        self.historical_premium_multiplier = filter_cfg.get('historical_premium_multiplier', 2.0)  # 历史倍数
        self.historical_lookback_days = filter_cfg.get('historical_lookback_days', 7)  # 回溯天数
        self.call_csv_dir = Path(filter_cfg.get('call_csv_dir', 'call_csv_files'))  # CSV目录
        
        # 做空Premium倍数过滤
        self.max_daily_short_premium_multiplier = filter_cfg.get('max_daily_short_premium_multiplier', 0)  # 做空倍数
        
        # === 仓位配置 ===
        position_cfg = strategy_cfg.get('position_compute', {})
        self.max_daily_trades = position_cfg.get('max_daily_trades', 5)  # 每日最大交易次数
        self.max_daily_position = position_cfg.get('max_daily_position', 0.99)  # 每日总仓位上限
        self.max_single_position = position_cfg.get('max_single_position', 0.40)  # 单笔仓位上限
        self.premium_divisor = position_cfg.get('premium_divisor', 800000)  # 仓位计算除数
        
        # === 杠杆配置（已禁用）===
        # 不使用杠杆，通过max_daily_position控制仓位
        
        # === 出场配置 ===
        self.stop_loss = strategy_cfg.get('stop_loss', 0.10)  # 止损 -10%
        self.take_profit = strategy_cfg.get('take_profit', 0.20)  # 止盈 +20%
        self.trailing_stop = strategy_cfg.get('trailing_stop', 0.15)  # 追踪止损 -15%（从最高价回撤）
        self.enable_trailing_stop = strategy_cfg.get('enable_trailing_stop', True)  # 是否启用追踪止损
        self.holding_days = strategy_cfg.get('holding_days', 6)  # 持仓天数
        self.exit_time = strategy_cfg.get('exit_time', '15:00:00')  # 定时退出时间
        
        # === 黑名单配置 ===
        self.blacklist_days = strategy_cfg.get('blacklist_days', 15)  # 黑名单天数
        
        # === 交易成本（由client处理，策略不关心）===
        # 实盘：无滑点手续费
        # 回测：client会应用滑点和手续费
        
        # === 运行时状态 ===
        self.daily_trade_count = 0  # 当日交易计数
        self.blacklist: Dict[str, datetime] = {}  # 黑名单：{symbol: 买入时间}
        self.highest_price_map: Dict[str, float] = {}  # 追踪止损：{symbol: 历史最高价}
        
        # === QQQ MA数据加载 ===
        self.qqq_ma_data = None
        self.enable_ma_filter = strategy_cfg.get('enable_ma_filter', True)  # 是否启用MA过滤
        if self.enable_ma_filter:
            self._load_qqq_ma_data()
        
        # 打印配置信息
        trailing_info = f", 追踪止损{self.trailing_stop:.0%}" if self.enable_trailing_stop else ""
        self.logger.info(
            f"StrategyV7 初始化完成:\n"
            f"  入场: 时间>={self.trade_start_time}, 延迟{self.entry_delay}分钟, "
            f"溢价>=${self.min_option_premium/1000:.0f}K\n"
            f"  仓位: 日限{self.max_daily_trades}次, 总仓<={self.max_daily_position:.0%}, "
            f"单仓<={self.max_single_position:.0%}\n"
            f"  出场: 止盈{self.take_profit:+.0%}, 固定止损{self.stop_loss:+.0%}{trailing_info}, "
            f"持{self.holding_days}日@{self.exit_time}\n"
            f"  黑名单: {self.blacklist_days}日"
        )

    def _load_qqq_ma_data(self):
        """加载QQQ MA数据"""
        try:
            # 尝试从多个位置加载
            possible_paths = [
                Path('future_v_0_1/database/qqq_ma_data.csv'),
                Path('database/qqq_ma_data.csv'),
                Path(__file__).parent.parent / 'database' / 'qqq_ma_data.csv'
            ]
            
            for ma_file in possible_paths:
                if ma_file.exists():
                    # 读取CSV，自动解析日期列为index
                    self.qqq_ma_data = pd.read_csv(ma_file, index_col=0, parse_dates=True)
                    
                    # 确保index是datetime类型
                    if not isinstance(self.qqq_ma_data.index, pd.DatetimeIndex):
                        self.qqq_ma_data.index = pd.to_datetime(self.qqq_ma_data.index)
                    
                    # 去除时区信息（如果有）
                    if self.qqq_ma_data.index.tz is not None:
                        self.qqq_ma_data.index = self.qqq_ma_data.index.tz_localize(None)
                    
                    self.logger.info(
                        f"✅ QQQ MA数据加载成功: {ma_file} "
                        f"({len(self.qqq_ma_data)}条记录, "
                        f"{self.qqq_ma_data.index[0].date()} 至 {self.qqq_ma_data.index[-1].date()})"
                    )
                    
                    # 检查最新状态
                    latest = self.qqq_ma_data.iloc[-1]
                    is_bullish = latest['bullish_alignment']
                    self.logger.info(
                        f"  最新交易日({self.qqq_ma_data.index[-1].date()}): "
                        f"{'多头排列 ✓' if is_bullish else '非多头排列 ✗'} "
                        f"(MA20=${latest['MA20']:.2f}, MA60=${latest['MA60']:.2f})"
                    )
                    return
            
            # 如果所有路径都失败
            self.logger.warning(
                "⚠️  未找到QQQ MA数据文件，MA过滤将被禁用。"
                "请运行: python download_spy_ma.py"
            )
            self.enable_ma_filter = False
            
        except Exception as e:
            self.logger.error(f"❌ 加载QQQ MA数据失败: {e}，MA过滤将被禁用")
            self.qqq_ma_data = None
            self.enable_ma_filter = False

    def on_start(self):
        """策略启动"""
        self.logger.info("StrategyV7 启动")

    def on_shutdown(self):
        """策略关闭"""
        self.logger.info("StrategyV7 关闭")

    def on_day_open(self, trading_date_et: date):
        """交易日开盘"""
        self.logger.info(f"交易日开盘: {trading_date_et}")

    def on_day_close(self, trading_date_et: date):
        """交易日收盘"""
        self.logger.info(f"交易日收盘: {trading_date_et}")

    def on_signal(self, ev, market_client=None):
        """
        处理信号事件，生成开仓决策
        
        Args:
            ev: SignalEvent 信号事件
            market_client: 市场数据客户端实例
            
        Returns:
            EntryDecision 或 None
        """
        if not market_client:
            self.logger.error("市场数据客户端未提供，无法处理信号")
            return None
        
        # ===== 1. 时间过滤 =====
        # 检查交易时间窗口
        trade_start = datetime.strptime(self.trade_start_time, '%H:%M:%S').time()
        if ev.event_time_et.time() < trade_start:
            self.logger.debug(
                f"过滤: {ev.symbol} 时间过早 {ev.event_time_et.time()} < {trade_start}"
            )
            return None
        
        # 检查距离收盘时间（15:54之后不交易）
        market_close = time(15, 54, 0)
        if ev.event_time_et.time() >= market_close:
            self.logger.debug(
                f"过滤: {ev.symbol} 距离收盘过近 {ev.event_time_et.time()}"
            )
            return None
        
        # ===== 2. 期权溢价过滤 =====
        if ev.premium_usd < self.min_option_premium:
            self.logger.debug(
                f"过滤: {ev.symbol} 溢价过低 ${ev.premium_usd:,.0f} < ${self.min_option_premium:,.0f}"
            )
            return None
        
        # ===== 3. QQQ MA多头排列过滤（新增）=====
        if self.enable_ma_filter:
            if not self._check_qqq_bullish_alignment(ev.event_time_et):
                return None
        
        # ===== 4. 历史Premium过滤 =====
        # 回测时跳过（由回测引擎处理），通过检查 call_csv_dir 是否存在来判断
        if self.call_csv_dir.exists():
            if not self._check_historical_premium(ev.symbol, ev.premium_usd, ev.event_time_et):
                return None
        
        # ===== 5. 做空Premium倍数过滤 =====
        if self.call_csv_dir.exists() and self.max_daily_short_premium_multiplier > 0:
            if not self._check_daily_short_premium(ev.symbol, ev.premium_usd, ev.event_time_et):
                return None
        
        # ===== 6. 黑名单过滤 =====
        if ev.symbol in self.blacklist:
            last_buy_time = self.blacklist[ev.symbol]
            days_since = (ev.event_time_et - last_buy_time).days
            if days_since < self.blacklist_days:
                self.logger.info(
                    f"过滤: {ev.symbol} 在黑名单中 (上次买入: {last_buy_time.strftime('%Y-%m-%d')}, "
                    f"已过{days_since}天/{self.blacklist_days}天)"
                )
                return None
            else:
                # 黑名单已过期，移除
                del self.blacklist[ev.symbol]
        
        # ===== 7. 每日交易次数限制 =====
        if self.daily_trade_count >= self.max_daily_trades:
            self.logger.info(
                f"过滤: {ev.symbol} 今日已达交易上限 {self.daily_trade_count}/{self.max_daily_trades}"
            )
            return None
        
        # ===== 8. 获取账户信息 =====
        acc_info = market_client.get_account_info()
        if not acc_info:
            self.logger.error("获取账户信息失败")
            return None
        
        total_assets = acc_info['total_assets']
        cash = acc_info['cash']
        
        # ===== 9. 获取股票价格（Entry Delay处理）=====
        # 计算延迟后的买入时间
        entry_time_et = ev.event_time_et + timedelta(minutes=self.entry_delay)
        
        # 设置市场时间为买入时刻
        market_client.set_current_time(entry_time_et)
        
        # 获取买入时刻的价格
        price_info = market_client.get_stock_price(ev.symbol)
        if not price_info:
            self.logger.error(f"获取 {ev.symbol} 价格失败")
            # 恢复原时间
            market_client.set_current_time(ev.event_time_et)
            return None
        
        current_price = price_info['last_price']
        
        # 恢复市场时间为信号时刻（避免影响后续逻辑）
        market_client.set_current_time(ev.event_time_et)
        
        # ===== 10. 计算仓位比例 =====
        pos_ratio = min(ev.premium_usd / self.premium_divisor, self.max_single_position)
        
        # ===== 11. 计算股数=====
        target_value = total_assets * pos_ratio
        qty = int(target_value / current_price)
        
        if qty <= 0:
            self.logger.debug(f"过滤: {ev.symbol} 计算股数为0")
            return None
        
        # 计算目标价值
        target_cost = current_price * qty
        
        self.logger.debug(
            f"仓位计算: 溢价${ev.premium_usd:,.0f} → 仓位{pos_ratio:.1%} → "
            f"{qty}股 × ${current_price:.2f} = ${target_cost:,.2f}"
        )
        
        # ===== 12. 检查总仓位限制 =====
        positions = market_client.get_positions()
        current_position_value = 0
        
        if positions:
            # 检查是否已持有该股票
            for pos in positions:
                if pos['symbol'] == ev.symbol and pos['position'] > 0:
                    self.logger.info(f"过滤: {ev.symbol} 已持有仓位，避免重复开仓")
                    return None
                
                current_position_value += pos.get('market_value', 0)
        
        # 检查总仓位限制
        new_total_position_value = current_position_value + target_cost
        new_total_position_ratio = new_total_position_value / total_assets
        
        if new_total_position_ratio > self.max_daily_position:
            self.logger.info(
                f"过滤: {ev.symbol} 总仓位将超限 {new_total_position_ratio:.1%} > "
                f"{self.max_daily_position:.0%}"
            )
            return None
        
        # ===== 13. 检查现金充足性 =====
        if cash < target_cost:
            self.logger.info(
                f"过滤: {ev.symbol} 现金不足 需要${target_cost:,.2f}, 剩余${cash:,.2f}"
            )
            return None
        
        # ===== 14. 生成开仓决策 =====
        client_id = f"{ev.symbol}_{ev.event_time_et.strftime('%Y%m%d%H%M%S')}"
        
        self.logger.info(
            f"✓ 开仓决策: {ev.symbol} {qty}股 @${current_price:.2f} "
            f"(仓位{pos_ratio:.1%}, 溢价${ev.premium_usd:,.0f})"
        )
        
        return EntryDecision(
            symbol=ev.symbol,
            shares=qty,
            price_limit=current_price,  # 基准价，client会应用滑点（回测）
            t_exec_et=entry_time_et,
            pos_ratio=pos_ratio,
            client_id=client_id,
            meta={
                'event_id': ev.event_id,
                'premium_usd': ev.premium_usd,
                'signal_time': ev.event_time_et.isoformat(),
                'entry_delay': self.entry_delay
            }
        )

    def _check_qqq_bullish_alignment(self, signal_time: datetime) -> bool:
        """
        检查QQQ是否呈多头排列（MA20 > MA60）
        
        重要：使用信号当天之前（前一个交易日）的MA数据，避免看到未来
        
        Args:
            signal_time: 信号时间（美东时区，从北京时间转换而来）
            
        Returns:
            bool: True=多头排列，允许交易; False=非多头排列，不交易
        """
        if self.qqq_ma_data is None:
            self.logger.warning("QQQ MA数据未加载，跳过MA过滤")
            return True  # 容错：数据未加载时允许交易
        
        try:
            # Step 1: 将signal_time转换为tz-naive datetime
            if isinstance(signal_time, datetime):
                if signal_time.tzinfo is not None:
                    # 带时区（美东时区），去除时区信息保留时间值
                    signal_time_naive = signal_time.replace(tzinfo=None)
                else:
                    signal_time_naive = signal_time
            else:
                # 如果传入的就是date，转换为datetime
                signal_time_naive = datetime.combine(signal_time, datetime.min.time())
            
            # Step 2: 获取信号日期，并往前推一天（取前一个交易日的MA）
            # 因为当天的MA是基于当天收盘价计算的，盘中还没有，所以要用前一天的
            signal_date = signal_time_naive.date()
            
            # Step 3: 转换为pandas Timestamp并设置为当天的00:00:00（tz-naive）
            # 然后查找严格小于这个时间的MA数据（即前一个交易日或更早）
            signal_timestamp = pd.Timestamp(signal_date)
            
            # 查找严格小于signal_timestamp的数据（即前一天或更早）
            valid_data = self.qqq_ma_data[self.qqq_ma_data.index < signal_timestamp]
            
            if len(valid_data) == 0:
                self.logger.warning(
                    f"无法找到{signal_date}之前的QQQ MA数据，允许交易（容错）"
                )
                return True
            
            # Step 4: 获取最近的一天数据（前一个交易日）
            latest_ma = valid_data.iloc[-1]
            latest_date = valid_data.index[-1].date()
            is_bullish = latest_ma['bullish_alignment']
            
            # Step 5: 返回结果
            if is_bullish:
                self.logger.debug(
                    f"✓ QQQ多头排列检查通过 (信号日{signal_date}, 使用前一日{latest_date}的MA): "
                    f"MA20=${latest_ma['MA20']:.2f} > MA60=${latest_ma['MA60']:.2f}"
                )
                return True
            else:
                self.logger.info(
                    f"过滤: QQQ非多头排列 (信号日{signal_date}, 使用前一日{latest_date}的MA): "
                    f"MA20=${latest_ma['MA20']:.2f} ≤ MA60=${latest_ma['MA60']:.2f}"
                )
                return False
                
        except Exception as e:
            self.logger.warning(f"检查QQQ多头排列异常，允许交易（容错）: {e}")
            return True

    def _check_historical_premium(self, symbol: str, current_premium: float, 
                                   signal_time: datetime) -> bool:
        """
        检查当前期权溢价是否超过历史均值的N倍
        
        Args:
            symbol: 股票代码
            current_premium: 当前期权溢价
            signal_time: 信号时间
            
        Returns:
            bool: True=通过过滤, False=不通过
        """
        try:
            # 计算回溯日期范围
            end_date = signal_time.date() - timedelta(days=1)  # 前一天结束
            # start_date = end_date - timedelta(days=self.historical_lookback_days)  # 回溯起始日期（暂未使用）
            
            # 查找历史CSV文件
            historical_premiums = []
            
            for days_back in range(self.historical_lookback_days + 1):
                check_date = end_date - timedelta(days=days_back)
                csv_pattern = f"{symbol}_{check_date.strftime('%Y-%m-%d')}_ET.csv"
                csv_file = self.call_csv_dir / csv_pattern
                
                if csv_file.exists():
                    # 读取CSV文件中的premium数据
                    try:
                        with open(csv_file, 'r', encoding='utf-8') as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                # 假设CSV中有'premium'列
                                if 'premium' in row:
                                    premium = float(row['premium'])
                                    historical_premiums.append(premium)
                    except Exception as e:
                        self.logger.debug(f"读取历史文件失败 {csv_file}: {e}")
            
            # 如果没有足够的历史数据，允许交易（容错机制）
            if len(historical_premiums) == 0:
                self.logger.debug(
                    f"{symbol} 无历史数据，允许交易（容错）"
                )
                return True
            
            # 计算历史平均值
            avg_premium = sum(historical_premiums) / len(historical_premiums)
            threshold = avg_premium * self.historical_premium_multiplier
            
            if current_premium >= threshold:
                self.logger.debug(
                    f"✓ 历史过滤通过: {symbol} 当前${current_premium:,.0f} >= "
                    f"{self.historical_premium_multiplier}x历史均值${threshold:,.0f} "
                    f"(样本数={len(historical_premiums)})"
                )
                return True
            else:
                self.logger.info(
                    f"过滤: {symbol} 历史Premium不足 当前${current_premium:,.0f} < "
                    f"{self.historical_premium_multiplier}x历史均值${threshold:,.0f} "
                    f"(样本数={len(historical_premiums)})"
                )
                return False
                
        except Exception as e:
            # 容错：如果过滤逻辑出错，允许交易
            self.logger.warning(f"{symbol} 历史过滤异常，允许交易: {e}")
            return True

    def _check_daily_short_premium(self, symbol: str, current_premium: float, 
                                     signal_time: datetime) -> bool:
        """
        检查当天做空premium总和是否超过当前交易的倍数
        
        Args:
            symbol: 股票代码
            current_premium: 当前期权溢价
            signal_time: 信号时间
            
        Returns:
            bool: True=通过过滤, False=不通过（被过滤）
        """
        try:
            # 如果倍数为0，禁用此过滤
            if self.max_daily_short_premium_multiplier <= 0:
                return True
            
            # 查找当天的历史CSV文件
            signal_date = signal_time.date() if hasattr(signal_time, 'date') else signal_time
            csv_pattern = f"{symbol}_{signal_date.strftime('%Y-%m-%d')}_ET.csv"
            csv_file = self.call_csv_dir / csv_pattern
            
            if not csv_file.exists():
                # 没有当天历史数据，允许交易
                self.logger.debug(f"{symbol} 无当天历史CSV，跳过做空过滤")
                return True
            
            # 统计当天做空交易的premium总和
            short_sum = 0
            short_list = []
            
            # 移除时区信息以便比较
            signal_time_naive = signal_time.replace(tzinfo=None) if hasattr(signal_time, 'tzinfo') and signal_time.tzinfo else signal_time
            
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        # 解析时间
                        date_str = row.get('date', '')
                        time_str = row.get('time', '')
                        if not date_str or not time_str:
                            continue
                        
                        datetime_str = f"{date_str} {time_str}"
                        row_time_cn = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
                        
                        # 转换为ET时区
                        cn_tz = pytz.timezone('Asia/Shanghai')
                        row_time_cn = cn_tz.localize(row_time_cn)
                        et_tz = pytz.timezone('America/New_York')
                        row_time_et = row_time_cn.astimezone(et_tz).replace(tzinfo=None)
                        
                        # 只统计在信号时间之前的交易
                        if row_time_et >= signal_time_naive:
                            continue
                        
                        # 获取premium
                        premium_str = row.get('premium', '0').replace(',', '')
                        premium = float(premium_str)
                        
                        # 过滤掉小额premium
                        if premium <= 100000:
                            continue
                        
                        # 判断是否为做空交易
                        side = row.get('side', '').upper()
                        option_type = row.get('option_type', '').lower()
                        
                        # 做空：ASK PUT 或 BID CALL
                        if (side == 'ASK' and option_type == 'put') or (side == 'BID' and option_type == 'call'):
                            short_sum += premium
                            short_list.append((row_time_et.strftime('%H:%M'), side, option_type, premium))
                    
                    except Exception as e:
                        self.logger.debug(f"解析行失败: {e}")
                        continue
            
            # 计算阈值
            threshold = current_premium * self.max_daily_short_premium_multiplier
            
            # 判断是否超过阈值
            if short_sum >= threshold:
                # 构建做空交易详情（最多显示3笔）
                trades_detail = ', '.join([f"{t} {s} {o.upper()} ${p:,.0f}" for t, s, o, p in short_list[:3]])
                if len(short_list) > 3:
                    trades_detail += f" ...等{len(short_list)}笔"
                
                self.logger.info(
                    f"过滤: {symbol} 做空倍数过滤 当天做空总和${short_sum:,.0f} >= "
                    f"当前交易${current_premium:,.0f} × {self.max_daily_short_premium_multiplier} "
                    f"({trades_detail})"
                )
                return False
            else:
                self.logger.debug(
                    f"✓ 做空过滤通过: {symbol} 当天做空总和${short_sum:,.0f} < "
                    f"阈值${threshold:,.0f} (当前${current_premium:,.0f} × {self.max_daily_short_premium_multiplier})"
                )
                return True
                
        except Exception as e:
            # 容错：如果过滤逻辑出错，允许交易
            self.logger.warning(f"{symbol} 做空过滤异常，允许交易: {e}")
            return True

    def on_minute_check(self, market_client=None, entry_time_map=None):
        """
        每分钟检查持仓（实盘和回测统一调用）
        
        出场优先级：
        1. 固定止损（-5%）
        2. 追踪止损（-10% from highest）
        3. 固定止盈（+50%）
        4. 定时退出（第6天下午3:00）
        
        Args:
            market_client: 市场数据客户端实例
            entry_time_map: 持仓开仓时间映射 {symbol: entry_time_str}
            
        Returns:
            List[ExitDecision]: 平仓决策列表
        """
        return self.on_position_check(market_client, entry_time_map)
    
    def on_position_check(self, market_client=None, entry_time_map=None):
        """
        检查持仓，生成平仓决策（兼容旧接口）
        
        出场优先级：
        1. 固定止损（-5%）
        2. 追踪止损（-10% from highest）
        3. 固定止盈（+50%）
        4. 定时退出（第6天下午3:00）
        
        Args:
            market_client: 市场数据客户端实例
            entry_time_map: 持仓开仓时间映射 {symbol: entry_time_str}
            
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
        
        # DEBUG: Log entry_time_map for debugging (only if changed)
        # if entry_time_map and len(entry_time_map) > 0:
        #     self.logger.info(f"[DEBUG] entry_time_map keys: {list(entry_time_map.keys())}")
        
        exit_decisions = []
        # Use backtest time if available, otherwise use current system time
        if hasattr(market_client, 'current_time') and market_client.current_time:
            current_et = market_client.current_time
        else:
            current_et = datetime.now(ZoneInfo('America/New_York'))
        exit_time_today = datetime.strptime(self.exit_time, '%H:%M:%S').time()
        
        for pos in positions:
            symbol = pos['symbol']
            cost_price = pos['cost_price']
            current_price = pos['market_price']
            can_sell_qty = pos['can_sell_qty']
            
            # 跳过可卖数量为0的持仓
            if can_sell_qty <= 0:
                self._check_pending_orders(symbol, market_client)
                continue
            
            # 计算盈亏比例（使用当前价格，不含滑点）
            # 注意：滑点由client应用
            pnl_ratio = (current_price - cost_price) / cost_price
            
            # 更新历史最高价（用于追踪止损）
            if symbol not in self.highest_price_map:
                # 首次记录，使用成本价作为初始值
                self.highest_price_map[symbol] = max(cost_price, current_price)
            else:
                # 更新最高价
                self.highest_price_map[symbol] = max(self.highest_price_map[symbol], current_price)
            
            # ===== 1. 优先检查定时退出 =====
            if symbol in entry_time_map:
                exit_decision = self._check_timed_exit(
                    symbol, can_sell_qty, cost_price, current_price, 
                    pnl_ratio, entry_time_map[symbol], current_et, 
                    exit_time_today, market_client
                )
                if exit_decision:
                    exit_decisions.append(exit_decision)
                    # 清除最高价记录
                    if symbol in self.highest_price_map:
                        del self.highest_price_map[symbol]
                    continue  # 定时退出后不再检查止损止盈
            else:
                pass  # Symbol not in entry_time_map, skip timed exit check
            
            # 检查出场条件（20秒检查频率，直接用当前价格）
            exit_decision = self._check_exit_conditions(
                symbol, can_sell_qty, cost_price, current_price, 
                pnl_ratio, current_et
            )
            
            if exit_decision:
                exit_decisions.append(exit_decision)
                # 清除最高价记录
                if symbol in self.highest_price_map:
                    del self.highest_price_map[symbol]
        
        return exit_decisions

    def _check_timed_exit(self, symbol: str, can_sell_qty: int, cost_price: float,
                         current_price: float, pnl_ratio: float, entry_time_str: str,
                         current_et: datetime, exit_time_today: time,
                         market_client) -> Optional[ExitDecision]:
        """
        检查定时退出条件
        
        Args:
            symbol: 股票代码
            can_sell_qty: 可卖数量
            cost_price: 成本价
            current_price: 当前价格（基准价，不含滑点）
            pnl_ratio: 盈亏比例
            entry_time_str: 开仓时间字符串
            current_et: 当前美东时间
            exit_time_today: 今日退出时间
            market_client: 市场客户端
            
        Returns:
            ExitDecision 或 None
        """
        try:
            # 解析开仓时间
            entry_time_dt = datetime.fromisoformat(entry_time_str)
            if entry_time_dt.tzinfo is None:
                entry_time_et = entry_time_dt.replace(tzinfo=ZoneInfo('America/New_York'))
            else:
                entry_time_et = entry_time_dt.astimezone(ZoneInfo('America/New_York'))
            
            # 计算持仓的交易日数
            entry_date = entry_time_et.date()
            current_date = current_et.date()
            trading_days_held = self._count_trading_days(entry_date, current_date, market_client)
            
            # 检查是否到达持仓天数
            if trading_days_held >= self.holding_days:
                # 计算退出日期（第N天）
                exit_date = self._calculate_exit_date(entry_date, market_client)
                
                # 只在退出日期的退出时间或之后平仓
                if current_date >= exit_date and current_et.time() >= exit_time_today:
                    self.logger.info(
                        f"✓ 平仓决策[定时退出]: {symbol} {can_sell_qty}股 @${current_price:.2f} "
                        f"(成本${cost_price:.2f}, 持仓{trading_days_held}日, 盈亏{pnl_ratio:+.1%})"
                    )
                    return ExitDecision(
                        symbol=symbol,
                        shares=can_sell_qty,
                        price_limit=current_price,  # 基准价，client会应用滑点
                        reason='timed_exit',
                        client_id=f"{symbol}_TD_{current_et.strftime('%Y%m%d%H%M%S')}",
                        meta={
                            'holding_days': trading_days_held,
                            'pnl_ratio': pnl_ratio,
                            'entry_date': entry_date.isoformat(),
                            'exit_date': exit_date.isoformat(),
                            'cost_price': cost_price,
                            'current_price': current_price
                        }
                    )
                elif trading_days_held >= self.holding_days:
                    self.logger.debug(
                        f"{symbol} 持仓已到期({trading_days_held}日)，但未到退出时间 "
                        f"{exit_time_today}，等待平仓"
                    )
        
        except Exception as e:
            self.logger.warning(f"检查 {symbol} 定时退出失败: {e}")
        
        return None

    def _calculate_exit_date(self, entry_date: date, market_client) -> date:
        """
        计算退出日期（开仓后第N个交易日）
        
        Args:
            entry_date: 开仓日期
            market_client: 市场客户端
            
        Returns:
            date: 退出日期
        """
        # 从开仓日期开始，找到第N个交易日
        current_date = entry_date
        trading_days_count = 0
        
        # 最多尝试30天（避免无限循环）
        for _ in range(30):
            # 检查是否为交易日
            if self._is_trading_day(current_date, market_client):
                trading_days_count += 1
                
                if trading_days_count >= self.holding_days:
                    return current_date
            
            current_date += timedelta(days=1)
        
        # 如果没找到，返回N天后的日期（fallback）
        return entry_date + timedelta(days=self.holding_days)

    def _is_trading_day(self, check_date: date, market_client) -> bool:
        """
        检查是否为交易日
        
        Args:
            check_date: 检查日期
            market_client: 市场客户端
            
        Returns:
            bool: 是否为交易日
        """
        # 简单判断：排除周末
        if check_date.weekday() >= 5:  # 周六=5, 周日=6
            return False
        
        # TODO: 可以调用 market_client API 查询是否为交易日
        return True

    def _count_trading_days(self, start_date: date, end_date: date, 
                           market_client=None) -> int:
        """
        计算两个日期之间的交易日数量（包括start_date和end_date）
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            market_client: 市场数据客户端
            
        Returns:
            int: 交易日数量
        """
        if start_date > end_date:
            return 0
        
        # 尝试使用 Futu API
        if market_client:
            try:
                count = market_client.count_trading_days_between(
                    start_date=(start_date - timedelta(days=1)).strftime('%Y-%m-%d'),
                    end_date=end_date.strftime('%Y-%m-%d'),
                    market='US'
                )
                if count is not None:
                    return count
            except Exception as e:
                self.logger.debug(f"Futu API 查询交易日失败: {e}")
        
        # 本地计算（仅排除周末）
        trading_days = 0
        current = start_date
        
        while current <= end_date:
            if current.weekday() < 5:  # 周一到周五
                trading_days += 1
            current += timedelta(days=1)
        
        return trading_days

    def _check_pending_orders(self, symbol: str, market_client):
        """
        检查未成交订单（用于诊断可卖数量为0的原因）
        
        Args:
            symbol: 股票代码
            market_client: 市场客户端
        """
        try:
            pending_orders = market_client.get_order_list(
                status_filter='PENDING',
                symbol_filter=symbol
            )
            
            if pending_orders:
                pending_sells = [o for o in pending_orders if o['side'] == 'SELL']
                if pending_sells:
                    total_qty = sum(o['qty'] for o in pending_sells)
                    self.logger.debug(
                        f"{symbol} 已有未成交卖单 {len(pending_sells)}个, 锁定{total_qty}股"
                    )
                else:
                    self.logger.warning(
                        f"{symbol} 可卖数量=0 但无未成交卖单（可能T+1限制或API异常）"
                    )
        except Exception as e:
            self.logger.error(f"查询 {symbol} 订单失败: {e}")

    def _check_exit_conditions(self, symbol: str, can_sell_qty: int, 
                               cost_price: float, current_price: float, 
                               pnl_ratio: float, current_et: datetime) -> Optional[ExitDecision]:
        """
        检查止损、追踪止损和止盈条件（20秒检查频率）
        
        Args:
            symbol: 股票代码
            can_sell_qty: 可卖数量
            cost_price: 成本价
            current_price: 当前价格（基准价，不含滑点）
            pnl_ratio: 盈亏比例
            current_et: 当前美东时间
            
        Returns:
            ExitDecision 或 None
        """
        # 20秒检查频率，直接用当前价格
        low_price = current_price
        high_price = current_price
        
        # 计算各个出场价位
        stop_loss_price = cost_price * (1 - self.stop_loss)
        trailing_stop_price = self.highest_price_map.get(symbol, cost_price) * (1 - self.trailing_stop)
        take_profit_price = cost_price * (1 + self.take_profit)
        
        # ===== 1. 固定止损检查 =====
        if low_price <= stop_loss_price:
            self.logger.info(
                f"✓ 平仓决策[固定止损]: {symbol} {can_sell_qty}股 @${low_price:.2f} "
                f"(成本${cost_price:.2f}, 止损价${stop_loss_price:.2f}, 亏损{pnl_ratio:.1%})"
            )
            exit_decisions = [ExitDecision(
                symbol=symbol,
                shares=can_sell_qty,
                price_limit=low_price,  # 使用Low价成交
                reason='stop_loss',
                client_id=f"{symbol}_SL_{current_et.strftime('%Y%m%d%H%M%S')}",
                meta={
                    'pnl_ratio': pnl_ratio,
                    'cost_price': cost_price,
                    'current_price': current_price,
                    'exit_price': low_price,
                    'stop_loss_price': stop_loss_price
                }
            )]
            # 清除最高价记录
            if symbol in self.highest_price_map:
                del self.highest_price_map[symbol]
            return exit_decisions[0]
        
        # ===== 2. 追踪止损检查 =====
        if self.enable_trailing_stop and low_price <= trailing_stop_price:
            highest_price = self.highest_price_map.get(symbol, cost_price)
            drawdown_from_high = (highest_price - low_price) / highest_price
            
            self.logger.info(
                f"✓ 平仓决策[追踪止损]: {symbol} {can_sell_qty}股 @${low_price:.2f} "
                f"(最高${highest_price:.2f}, 回撤{drawdown_from_high:.1%}, 成本${cost_price:.2f})"
            )
            exit_decisions = [ExitDecision(
                symbol=symbol,
                shares=can_sell_qty,
                price_limit=low_price,  # 使用Low价成交
                reason='trailing_stop',
                client_id=f"{symbol}_TS_{current_et.strftime('%Y%m%d%H%M%S')}",
                meta={
                    'pnl_ratio': pnl_ratio,
                    'cost_price': cost_price,
                    'current_price': current_price,
                    'exit_price': low_price,
                    'highest_price': highest_price,
                    'trailing_stop_price': trailing_stop_price,
                    'drawdown_from_high': drawdown_from_high
                }
            )]
            # 清除最高价记录
            if symbol in self.highest_price_map:
                del self.highest_price_map[symbol]
            return exit_decisions[0]
        
        # ===== 3. 止盈检查 =====
        if high_price >= take_profit_price:
            highest_price = self.highest_price_map.get(symbol, current_price)
            self.logger.info(
                f"✓ 平仓决策[止盈]: {symbol} {can_sell_qty}股 @${high_price:.2f} "
                f"(成本${cost_price:.2f}, 止盈价${take_profit_price:.2f}, 盈利{pnl_ratio:.1%}, 最高${highest_price:.2f})"
            )
            exit_decisions = [ExitDecision(
                symbol=symbol,
                shares=can_sell_qty,
                price_limit=high_price,  # 使用High价成交
                reason='take_profit',
                client_id=f"{symbol}_TP_{current_et.strftime('%Y%m%d%H%M%S')}",
                meta={
                    'pnl_ratio': pnl_ratio,
                    'cost_price': cost_price,
                    'current_price': current_price,
                    'exit_price': high_price,
                    'highest_price': highest_price,
                    'take_profit_price': take_profit_price
                }
            )]
            # 清除最高价记录
            if symbol in self.highest_price_map:
                del self.highest_price_map[symbol]
            return exit_decisions[0]
        
        return None

    def on_order_filled(self, res):
        """订单成交回调"""
        self.logger.info(
            f"订单成交: {res.client_id}, 成交价: ${res.avg_price:.2f}, "
            f"成交量: {res.filled_shares}"
        )

    def on_order_rejected(self, res, reason: str):
        """订单拒绝回调"""
        self.logger.warning(
            f"订单拒绝: {res.client_id}, 原因: {reason}"
        )


if __name__ == '__main__':
    """测试脚本"""
    import yaml
    import sys
    from pathlib import Path
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 读取配置文件
    config_path = Path(__file__).parent.parent.parent / 'config.yaml'
    
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 创建策略上下文
    context = StrategyContext(
        cfg=config,
        logger=logging.getLogger('StrategyV7')
    )
    
    # 创建策略实例
    strategy = StrategyV7(context)
    
    print("\n✓ StrategyV7 测试成功")
    print(f"  日交易次数上限: {strategy.max_daily_trades}")
    print(f"  单笔仓位上限: {strategy.max_single_position:.0%}")
    print(f"  每日总仓位上限: {strategy.max_daily_position:.0%}")
    print(f"  止损/止盈: {strategy.stop_loss:.0%} / {strategy.take_profit:.0%}")
    print(f"  追踪止损: {strategy.trailing_stop:.0%}" if strategy.enable_trailing_stop else "  追踪止损: 禁用")
    print(f"  持仓天数: {strategy.holding_days}")

