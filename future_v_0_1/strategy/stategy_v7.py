"""
V7 事件驱动期权流动量策略
核心特性：
1. 历史Premium过滤：只交易超过历史均值2倍的期权流
2. Entry Delay：信号后2分钟买入
3. 严格风控：止损-10%，止盈+20%
4. 黑名单机制：15天内不重复交易
"""

import logging
from datetime import date, datetime, time, timedelta
from typing import Optional, Dict
from zoneinfo import ZoneInfo

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
        self.min_option_premium = filter_cfg.get('min_option_premium', 100000)  # 最小期权溢价
        
        # 历史Premium过滤（使用txt文件中的历史数据）
        self.historical_premium_multiplier = filter_cfg.get('historical_premium_multiplier', 2.0)  # 历史倍数
        
        # 做空交易过滤
        self.max_daily_short_premium = filter_cfg.get('max_daily_short_premium', 0)  # 当天做空premium总和上限

        # === 仓位配置 ===
        position_cfg = strategy_cfg.get('position_compute', {})
        self.max_daily_trades = position_cfg.get('max_daily_trades', 5)  # 每日最大交易次数
        self.max_daily_position = position_cfg.get('max_daily_position', 0.99)  # 每日总仓位上限
        self.max_single_position = position_cfg.get('max_single_position', 0.40)  # 单笔仓位上限
        self.premium_divisor = position_cfg.get('premium_divisor', 800000)  # 仓位计算除数

        # === 出场配置 ===
        self.stop_loss = strategy_cfg.get('stop_loss', 0.10)  # 止损 -10%
        self.take_profit = strategy_cfg.get('take_profit', 0.20)  # 止盈 +20%
        self.use_dynamic_stop_loss = strategy_cfg.get('use_dynamic_stop_loss', False)  # 是否启用动态止损
        self.dynamic_stop_loss_threshold = strategy_cfg.get('dynamic_stop_loss_threshold', 0.05)  # 动态止损阈值
        self.holding_days = strategy_cfg.get('holding_days', 6)  # 持仓天数
        self.exit_time = strategy_cfg.get('exit_time', '15:00:00')  # 定时退出时间

        # === 黑名单配置 ===
        self.blacklist_days = strategy_cfg.get('blacklist_days', 15)  # 黑名单天数

        # === 运行时状态 ===
        self.daily_trade_count = 0  # 当日交易计数
        self.blacklist: Dict[str, datetime] = {}  # 黑名单：{symbol: 买入时间}

        # 打印配置信息
        history_filter_msg = f"历史{self.historical_premium_multiplier}倍" if self.historical_premium_multiplier > 0 else "历史过滤已禁用"
        short_filter_msg = f"做空上限${self.max_daily_short_premium/1000:.0f}K" if self.max_daily_short_premium > 0 else "做空过滤已禁用"
        dynamic_sl_msg = f"动态止损{self.dynamic_stop_loss_threshold:.0%}(启用)" if self.use_dynamic_stop_loss else "动态止损已禁用"
        
        self.logger.info(
            f"StrategyV7 初始化完成:\n"
            f"  入场: 时间>={self.trade_start_time}, "
            f"溢价>=${self.min_option_premium/1000:.0f}K\n"
            f"  过滤: {history_filter_msg}, {short_filter_msg}\n"
            f"  仓位: 日限{self.max_daily_trades}次, 总仓<={self.max_daily_position:.0%}, "
            f"单仓<={self.max_single_position:.0%}\n"
            f"  出场: 止盈{self.take_profit:+.0%}, 止损{self.stop_loss:+.0%}, {dynamic_sl_msg}, "
            f"持{self.holding_days}日@{self.exit_time}\n"
            f"  黑名单: {self.blacklist_days}日"
        )

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

    def _check_dynamic_stop_loss(self, cost_price: float, current_price: float, 
                                  highest_price: float) -> bool:
        """
        检查是否触发动态止损
        
        动态止损基于从买入以来的最高点下跌幅度触发
        例如：highest_price=$100, current_price=$92, dynamic_stop_loss=8%
             则下跌幅度 = ($100 - $92) / $100 = 8%，触发卖出
        
        Args:
            cost_price: 买入价格
            current_price: 当前价格
            highest_price: 买入以来的最高价格
            
        Returns:
            True 如果应该止损，False 否则
        """
        if not self.use_dynamic_stop_loss or self.dynamic_stop_loss_threshold <= 0:
            return False
        
        # 检查最高价是否有效
        if highest_price <= 0:
            return False
        
        # 计算从最高点的下跌比例
        drawdown_ratio = (highest_price - current_price) / highest_price
        
        return drawdown_ratio >= self.dynamic_stop_loss_threshold

    def on_signal(self, ev, market_client=None):
        """
        处理信号事件，生成开仓决策
        
        Args:
            ev: SignalEvent 信号事件
            market_client: 市场数据客户端实例
            
        Returns:
            EntryDecision 或 None
        """
        # 记录新增信号
        self.logger.info(f"收到新增期权信号: {ev.symbol} 权利金${ev.premium_usd:,.0f} @{ev.event_time_et.strftime('%H:%M:%S')}")
        
        if not market_client:
            self.logger.error("市场数据客户端未提供，无法处理信号")
            return None, "市场数据客户端未提供"

        # ===== 1. 当日信号过滤 =====
        # 只处理当日信号，避免处理历史信号
        current_date_et = datetime.now(ZoneInfo('America/New_York')).date()
        signal_date_et = ev.event_time_et.date()
        
        if signal_date_et < current_date_et:
            self.logger.info(
                f"过滤: {ev.symbol} 历史信号 (信号日期: {signal_date_et}, 当前日期: {current_date_et})"
            )
            return None, "历史信号"
        
        # ===== 2. 时间过滤 =====
        # 检查交易时间窗口
        trade_start = datetime.strptime(self.trade_start_time, '%H:%M:%S').time()
        if ev.event_time_et.time() < trade_start:
            self.logger.info(
                f"过滤: {ev.symbol} 时间过早 {ev.event_time_et.time()} < {trade_start}"
            )
            return None, "交易时间未到"

        # ===== 3. 期权溢价过滤 =====
        if ev.premium_usd < self.min_option_premium:
            self.logger.info(
                f"过滤: {ev.symbol} 溢价过低 ${ev.premium_usd:,.0f} < ${self.min_option_premium:,.0f}"
            )
            return None, "权利金过低"

        # ===== 4. 历史Premium过滤（使用txt中的历史数据）=====
        if self.historical_premium_multiplier > 0:
            if not self._check_historical_premium_from_metadata(ev):
                # 注意：详细的过滤原因已在_check_historical_premium_from_metadata中记录
                return None, "历史Premium不足"
        
        # ===== 5. 做空交易过滤 =====
        if self.max_daily_short_premium > 0:
            if self._has_excessive_short_trades_today(ev):
                return None, "当日做空premium超限"

        # ===== 6. 黑名单过滤 =====
        if ev.symbol in self.blacklist:
            last_buy_time = self.blacklist[ev.symbol]
            days_since = (ev.event_time_et - last_buy_time).days
            if days_since < self.blacklist_days:
                self.logger.info(
                    f"过滤: {ev.symbol} 在黑名单中 (上次买入: {last_buy_time.strftime('%Y-%m-%d')}, "
                    f"已过{days_since}天/{self.blacklist_days}天)"
                )
                return None, "在黑名单中"
            else:
                # 黑名单已过期，移除
                del self.blacklist[ev.symbol]

        # ===== 7. 每日交易次数限制 =====
        if self.daily_trade_count >= self.max_daily_trades:
            self.logger.info(
                f"过滤: {ev.symbol} 今日已达交易上限 {self.daily_trade_count}/{self.max_daily_trades}"
            )
            return None, "日交易次数已满"

        # ===== 8. 获取账户信息 =====
        acc_info = market_client.get_account_info()
        if not acc_info:
            self.logger.error("获取账户信息失败")
            return None, "获取账户信息失败"

        total_assets = acc_info['total_assets']
        cash = acc_info['cash']

        # ===== 9. 获取股票价格（Entry Delay处理）=====
        # 获取当前的买入价格
        price_info = market_client.get_stock_price(ev.symbol)
        if not price_info or price_info['last_price'] <= 0:
            # 使用 fallback：期权数据中的股票价格
            if ev.stock_price and ev.stock_price > 0:
                current_price = ev.stock_price
                self.logger.info(f"信号: {ev.symbol} 使用期权数据中的股票价格 ${current_price:.2f}")
            else:
                self.logger.error(f"获取 {ev.symbol} 价格失败")
                return None, "获取股票价格失败"
        else:
            current_price = price_info['last_price']

        # ===== 10. 计算仓位比例 =====
        pos_ratio = min(ev.premium_usd / self.premium_divisor, self.max_single_position)

        # ===== 11. 计算股数 =====
        target_value = total_assets * pos_ratio
        qty = int(target_value / current_price)

        if qty <= 0:
            self.logger.info(f"过滤: {ev.symbol} 计算股数为0")
            return None, "计算股数为0"

        buy_price = current_price
        actual_cost = buy_price * qty

        self.logger.debug(
            f"仓位计算: 溢价${ev.premium_usd:,.0f} → 仓位{pos_ratio:.1%} → "
            f"{qty}股 × ${buy_price:.2f} = ${actual_cost:,.2f}"
        )

        # ===== 12. 检查总仓位限制 =====
        positions = market_client.get_positions()
        current_position_value = 0

        if positions:
            # 检查是否已持有该股票
            for pos in positions:
                if pos['symbol'] == ev.symbol and pos['position'] > 0:
                    self.logger.info(f"过滤: {ev.symbol} 已持有仓位，避免重复开仓")
                    return None, "已持有仓位"

                current_position_value += pos.get('market_value', 0)

        new_total_position_ratio = (current_position_value + actual_cost) / total_assets

        if new_total_position_ratio > self.max_daily_position:
            self.logger.info(
                f"过滤: {ev.symbol} 总仓位将超限 {new_total_position_ratio:.1%} > "
                f"{self.max_daily_position:.0%}"
            )
            return None, "总仓位将超限"

        # ===== 13. 检查现金是否充足 =====
        if cash < actual_cost:
            self.logger.info(
                f"过滤: {ev.symbol} 现金不足 需要${actual_cost:,.2f} > 可用${cash:,.2f}"
            )
            return None, "现金不足"

        # ===== 14. 生成开仓决策 =====
        client_id = f"{ev.symbol}_{ev.event_time_et.strftime('%Y%m%d%H%M%S')}"

        # 计算预计退出时间
        entry_date = ev.event_time_et.date()
        exit_date = self._calculate_exit_date(entry_date, market_client)
        exit_time_obj = datetime.strptime(self.exit_time, '%H:%M:%S').time()
        planned_exit = f"{exit_date.strftime('%m-%d')} {exit_time_obj.strftime('%H:%M')} ET"

        self.logger.info(
            f"✓ 开仓决策: {ev.symbol}\n"
            f"  买入: {qty}股 @${buy_price:.2f} (成本${actual_cost:,.2f})\n"
            f"  信号: 时间{ev.event_time_et.strftime('%H:%M:%S')}, 权利金${ev.premium_usd:,.0f}\n"
            f"  仓位: {pos_ratio:.1%} (历史倍数{self.historical_premium_multiplier}x)\n"
            f"  计划退出: {planned_exit}"
        )

        decision = EntryDecision(
            symbol=ev.symbol,
            shares=qty,
            price_limit=buy_price,
            t_exec_et=ev.event_time_et,  # 立即执行买入，不延迟
            pos_ratio=pos_ratio,
            client_id=client_id,
            meta={
                'event_id': ev.event_id,
                'premium_usd': ev.premium_usd,
                'signal_time': ev.event_time_et.isoformat(),
                'buy_price': current_price,
                'planned_exit_time': self.exit_time
            }
        )
        return (decision, None)

    def _check_historical_premium_from_metadata(self, ev) -> bool:
        """
        检查当前期权溢价是否超过历史均值的N倍（使用txt文件中的历史数据）
        
        Args:
            ev: SignalEvent，包含 metadata['history_option_data']
            
        Returns:
            bool: True=通过过滤, False=不通过
        """
        try:
            # 检查是否有历史数据
            if not ev.metadata or 'history_option_data' not in ev.metadata:
                self.logger.debug(
                    f"{ev.symbol} 无历史数据，允许交易（容错）"
                )
                return True
            
            history_data = ev.metadata['history_option_data']
            
            # 如果历史数据为空，允许交易
            if not history_data or len(history_data) == 0:
                self.logger.debug(
                    f"{ev.symbol} 无历史数据，允许交易（容错）"
                )
                return True
            
            # 提取历史权利金
            historical_premiums = [h['premium'] for h in history_data if 'premium' in h]
            
            if len(historical_premiums) == 0:
                self.logger.debug(
                    f"{ev.symbol} 历史数据中无权利金信息，允许交易（容错）"
                )
                return True
            
            # 计算历史平均值
            avg_premium = sum(historical_premiums) / len(historical_premiums)
            threshold = avg_premium * self.historical_premium_multiplier
            
            if ev.premium_usd >= threshold:
                self.logger.debug(
                    f"✓ 历史过滤通过: {ev.symbol} 当前${ev.premium_usd:,.0f} >= "
                    f"{self.historical_premium_multiplier}x历史均值${threshold:,.0f} "
                    f"(样本数={len(historical_premiums)})"
                )
                return True
            else:
                self.logger.info(
                    f"过滤: {ev.symbol} 历史Premium不足 当前${ev.premium_usd:,.0f} < "
                    f"{self.historical_premium_multiplier}x历史均值${threshold:,.0f} "
                    f"(样本数={len(historical_premiums)})"
                )
                return False
        
        except Exception as e:
            # 容错：如果过滤逻辑出错，允许交易
            self.logger.warning(f"{ev.symbol} 历史过滤异常，允许交易: {e}")
            return True
    
    def _has_excessive_short_trades_today(self, ev) -> bool:
        """
        检查当天该股票之前做空交易的premium总和是否超过阈值（使用txt文件中的历史数据）
        
        做空交易定义：
        - ASK PUT（买入看跌期权）：看空股票，期望股价下跌
        - BID CALL（卖出看涨期权）：看空股票，期望股价不涨或下跌
        
        Args:
            ev: SignalEvent，包含 metadata['history_option_data']
            
        Returns:
            True if 做空premium总和超过阈值（应过滤），False otherwise
        """
        try:
            # 检查是否有历史数据
            if not ev.metadata or 'history_option_data' not in ev.metadata:
                return False
            
            history_data = ev.metadata['history_option_data']
            
            if not history_data or len(history_data) == 0:
                return False
            
            signal_time = ev.event_time_et
            short_premium_sum = 0
            min_premium = 100000  # 只统计premium > 100K的交易
            short_trades_list = []  # 记录做空交易，用于调试
            
            # 遍历历史数据
            for hist in history_data:
                try:
                    # 解析历史记录的时间（已经是 ET 时间的 ISO 格式字符串）
                    time_str = hist.get('time', '')
                    if not time_str:
                        continue
                    
                    # 解析时间
                    hist_time = datetime.fromisoformat(time_str)
                    if hist_time.tzinfo is None:
                        hist_time = hist_time.replace(tzinfo=ZoneInfo('America/New_York'))
                    
                    # 确保 signal_time 有时区
                    if signal_time.tzinfo is None:
                        signal_time = signal_time.replace(tzinfo=ZoneInfo('America/New_York'))
                    
                    # 只检查当天且在信号之前的交易
                    if hist_time.date() != signal_time.date():
                        continue
                    if hist_time >= signal_time:
                        continue
                    
                    # 获取 premium
                    premium = hist.get('premium', 0)
                    if premium <= min_premium:
                        continue
                    
                    # 检查是否是做空交易
                    side = hist.get('side', '').upper()
                    option_type = hist.get('option_type', '').lower()
                    
                    # 做空交易：ASK PUT（买入看跌）或 BID CALL（卖出看涨）
                    if (side == 'ASK' and option_type == 'put') or (side == 'BID' and option_type == 'call'):
                        short_premium_sum += premium
                        short_trades_list.append((
                            hist_time.strftime('%H:%M'), 
                            side, 
                            option_type, 
                            premium
                        ))
                
                except Exception as e:
                    self.logger.debug(f"解析历史交易时间失败: {e}")
                    continue
            
            # 如果做空premium总和超过阈值，过滤
            if short_premium_sum > self.max_daily_short_premium:
                trades_detail = ', '.join([
                    f"{t} {s} {ot.upper()} ${p:,.0f}" 
                    for t, s, ot, p in short_trades_list[:3]
                ])
                if len(short_trades_list) > 3:
                    trades_detail += f" ...等{len(short_trades_list)}笔"
                
                self.logger.info(
                    f"过滤: {ev.symbol} 当天做空premium总和${short_premium_sum:,.0f} > "
                    f"${self.max_daily_short_premium:,.0f} ({trades_detail})"
                )
                return True
            
            return False
        
        except Exception as e:
            # 容错：如果过滤逻辑出错，不过滤
            self.logger.warning(f"{ev.symbol} 做空过滤异常，允许交易: {e}")
            return False

    def on_position_check(self, market_client=None, entry_time_map=None, highest_price_map=None):
        """
        检查持仓，生成平仓决策
        
        出场优先级：
        1. 定时退出（持仓第N天下午3:00）
        2. 止损（-10%）
        3. 止盈（+20%）
        
        Args:
            market_client: 市场数据客户端实例
            entry_time_map: 持仓开仓时间映射 {symbol: entry_time_str}
            highest_price_map: 持仓最高价映射 {symbol: highest_price}
            
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
        
        if highest_price_map is None:
            highest_price_map = {}

        exit_decisions = []
        current_et = datetime.now(ZoneInfo('America/New_York'))
        exit_time_today = datetime.strptime(self.exit_time, '%H:%M:%S').time()

        # 打印持仓巡检概览（包含详细的个股状态）
        self.logger.info(f"\n{'='*100}")
        self.logger.info(f"持仓巡检 [{current_et.strftime('%Y-%m-%d %H:%M:%S ET')}]")
        self.logger.info(f"{'='*100}")

        # 缓存实时价格，避免重复查询
        realtime_prices = {}

        # 打印持仓概览
        self.logger.info("\n--- 持仓监控概览 ---")
        for pos in positions:
            symbol = pos['symbol']
            cost_price = pos['cost_price']
            can_sell_qty = pos['can_sell_qty']
            entry_time_str = entry_time_map.get(symbol)

            total_position = pos['position']

            # 计算显示价格（实时或缓存）
            display_price = pos.get('market_price', 0)
            try:
                price_info = market_client.get_stock_price(symbol)
                if price_info and price_info.get('last_price', 0) > 0:
                    display_price = price_info['last_price']
            except Exception:
                pass
            
            if display_price <= 0:
                display_price = cost_price

            # 计算盈亏
            cost_total = total_position * cost_price
            market_value = display_price * total_position
            pnl_amount = market_value - cost_total
            pnl_ratio_disp = (pnl_amount / cost_total) if cost_total > 0 else 0

            # 计算止损价格
            # 计算止损价格
            static_sl_price = cost_price * (1 - self.stop_loss)
            
            # 根据是否启用动态止损来选择止损点位
            if self.use_dynamic_stop_loss:
                highest_price = highest_price_map.get(symbol, cost_price)
                # 确保最高价至少是开仓价
                if highest_price < cost_price:
                    highest_price = cost_price
                if highest_price > 0:
                    dynamic_sl = highest_price * (1 - self.dynamic_stop_loss_threshold)
                    # 动态止损点位应该低于成本价，但优先于静态止损
                    dynamic_sl_price = f"${dynamic_sl:.2f}"
                else:
                    dynamic_sl_price = f"${static_sl_price:.2f} (回退)"
            else:
                dynamic_sl_price = "禁用"

            # 计算预计退出时间
            expected_exit = "N/A"
            if symbol in entry_time_map:
                try:
                    entry_time_str = entry_time_map[symbol]
                    entry_time_dt = datetime.fromisoformat(entry_time_str)
                    if entry_time_dt.tzinfo is None:
                        entry_time_et = entry_time_dt.replace(tzinfo=ZoneInfo('America/New_York'))
                    else:
                        entry_time_et = entry_time_dt.astimezone(ZoneInfo('America/New_York'))
                    entry_date = entry_time_et.date()
                    exit_date = self._calculate_exit_date(entry_date, market_client)
                    exit_time_obj = datetime.strptime(self.exit_time, '%H:%M:%S').time()
                    expected_exit = f"{exit_date.strftime('%m-%d')} {exit_time_obj.strftime('%H:%M')} ET"
                except Exception:
                    pass

            # 格式化开仓时间显示（MM-DD HH:MM）
            entry_time_display = "N/A"
            if symbol in entry_time_map:
                try:
                    entry_time_str = entry_time_map[symbol]
                    entry_time_dt = datetime.fromisoformat(entry_time_str)
                    if entry_time_dt.tzinfo is None:
                        entry_time_et = entry_time_dt.replace(tzinfo=ZoneInfo('America/New_York'))
                    else:
                        entry_time_et = entry_time_dt.astimezone(ZoneInfo('America/New_York'))
                    entry_time_display = entry_time_et.strftime('%m-%d %H:%M')
                except Exception:
                    pass

            # 显示详细的持仓状态
            # 获取历史最高价格显示（从数据库传入的映射）
            highest_price_display = highest_price_map.get(symbol, cost_price)
            # 确保最高价至少是开仓价
            if highest_price_display < cost_price:
                highest_price_display = cost_price
            
            if highest_price_display > 0:
                highest_price_str = f", 最高${highest_price_display:.2f}"
            else:
                highest_price_str = ""
            
            self.logger.info(
                f"  📊 {symbol}: {total_position}股 @${cost_price:.2f} (开仓: {entry_time_display}) "
                f"(当前${display_price:.2f}{highest_price_str}, 盈亏${pnl_amount:+,.2f} {pnl_ratio_disp:+.2%}) | "
                f"止损(静)${static_sl_price:.2f}(动){dynamic_sl_price} | "
                f"预计退出: {expected_exit} | 可卖: {can_sell_qty}股"
            )
            # 跳过可卖数量为0的持仓
            if can_sell_qty <= 0:
                self._check_pending_orders(symbol, market_client)
                continue

            # 使用已计算的display_price作为sell_price
            current_price = display_price
            sell_price = current_price
            realtime_prices[symbol] = current_price

            # 计算盈亏比例
            pnl_ratio = (sell_price - cost_price) / cost_price


            # ===== 1. 优先检查定时退出 =====
            if symbol in entry_time_map:
                exit_decision = self._check_timed_exit(
                    symbol, can_sell_qty, cost_price, sell_price, 
                    pnl_ratio, entry_time_map[symbol], current_et, 
                    exit_time_today, market_client
                )
                if exit_decision:
                    exit_decisions.append(exit_decision)
                    continue  # 定时退出后不再检查止损止盈

            # ===== 2. 动态止损检查 =====
            # 从映射获取最高价，确保至少是开仓价
            symbol_highest_price = highest_price_map.get(symbol, cost_price)
            if symbol_highest_price < cost_price:
                symbol_highest_price = cost_price
            
            if self._check_dynamic_stop_loss(cost_price, current_price, symbol_highest_price):
                drawdown_ratio = (symbol_highest_price - current_price) / symbol_highest_price
                self.logger.info(
                    f"✓ 平仓决策[动态止损]: {symbol} {can_sell_qty}股 @${sell_price:.2f} "
                    f"(成本${cost_price:.2f}, 从最高点下跌{drawdown_ratio:.1%}, 盈亏{pnl_ratio:+.1%})"
                )
                exit_decisions.append(ExitDecision(
                    symbol=symbol,
                    shares=can_sell_qty,
                    price_limit=sell_price,
                    reason='dynamic_stop_loss',
                    client_id=f"{symbol}_DSL_{current_et.strftime('%Y%m%d%H%M%S')}",
                    meta={
                        'pnl_ratio': pnl_ratio,
                        'cost_price': cost_price,
                        'sell_price': sell_price,
                        'highest_price': symbol_highest_price
                    }
                ))
                continue

            # ===== 3. 静态止损检查 =====
            if pnl_ratio <= -self.stop_loss:
                self.logger.info(
                    f"✓ 平仓决策[止损]: {symbol} {can_sell_qty}股 @${sell_price:.2f} "
                    f"(成本${cost_price:.2f}, 亏损{pnl_ratio:.1%})"
                )
                exit_decisions.append(ExitDecision(
                    symbol=symbol,
                    shares=can_sell_qty,
                    price_limit=sell_price,
                    reason='stop_loss',
                    client_id=f"{symbol}_SL_{current_et.strftime('%Y%m%d%H%M%S')}",
                    meta={
                        'pnl_ratio': pnl_ratio,
                        'cost_price': cost_price,
                        'sell_price': sell_price
                    }
                ))
                continue

            # ===== 4. 止盈检查 =====
            if pnl_ratio >= self.take_profit:
                self.logger.info(
                    f"✓ 平仓决策[止盈]: {symbol} {can_sell_qty}股 @${sell_price:.2f} "
                    f"(成本${cost_price:.2f}, 盈利{pnl_ratio:.1%})"
                )
                exit_decisions.append(ExitDecision(
                    symbol=symbol,
                    shares=can_sell_qty,
                    price_limit=sell_price,
                    reason='take_profit',
                    client_id=f"{symbol}_TP_{current_et.strftime('%Y%m%d%H%M%S')}",
                    meta={
                        'pnl_ratio': pnl_ratio,
                        'cost_price': cost_price,
                        'sell_price': sell_price
                    }
                ))

        return exit_decisions

    def _check_timed_exit(self, symbol: str, can_sell_qty: int, cost_price: float,
                         sell_price: float, pnl_ratio: float, entry_time_str: str,
                         current_et: datetime, exit_time_today: time,
                         market_client) -> Optional[ExitDecision]:
        """
        检查定时退出条件
        
        Args:
            symbol: 股票代码
            can_sell_qty: 可卖数量
            cost_price: 成本价
            sell_price: 卖出价
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
                    pnl_amt = (sell_price - cost_price) * can_sell_qty
                    self.logger.info(
                        f"✓ 平仓决策[定时退出]: {symbol}\n"
                        f"  卖出: {can_sell_qty}股 @${sell_price:.2f}\n"
                        f"  成本价: ${cost_price:.2f}, 持仓天数: {trading_days_held}天\n"
                        f"  盈亏: ${pnl_amt:+,.2f} {pnl_ratio:+.1%}"
                    )
                    return ExitDecision(
                        symbol=symbol,
                        shares=can_sell_qty,
                        price_limit=sell_price,
                        reason='timed_exit',
                        client_id=f"{symbol}_TD_{current_et.strftime('%Y%m%d%H%M%S')}",
                        meta={
                            'holding_days': trading_days_held,
                            'pnl_ratio': pnl_ratio,
                            'entry_date': entry_date.isoformat(),
                            'exit_date': exit_date.isoformat(),
                            'cost_price': cost_price,
                            'sell_price': sell_price
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
    print(f"  最大杠杆: {strategy.max_leverage:.2f}x")
    print(f"  止损/止盈: {strategy.stop_loss:.0%} / {strategy.take_profit:.0%}")
    print(f"  持仓天数: {strategy.holding_days}")