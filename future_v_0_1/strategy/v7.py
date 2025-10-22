"""
V7 事件驱动期权流动量策略 - 支持高杠杆的中长线期权流策略

核心特性：
1. 历史Premium过滤：只交易超过历史均值2倍的期权流
2. 杠杆支持：最大1.95倍杠杆，允许负现金至-100%
3. Entry Delay：信号后2分钟买入
4. 严格风控：止损-10%，止盈+20%
5. 黑名单机制：15天内不重复交易
"""

import logging
import csv
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
        
        # === 仓位配置 ===
        position_cfg = strategy_cfg.get('position_compute', {})
        self.max_daily_trades = position_cfg.get('max_daily_trades', 5)  # 每日最大交易次数
        self.max_daily_position = position_cfg.get('max_daily_position', 0.99)  # 每日总仓位上限
        self.max_single_position = position_cfg.get('max_single_position', 0.40)  # 单笔仓位上限
        self.premium_divisor = position_cfg.get('premium_divisor', 800000)  # 仓位计算除数
        
        # === 杠杆配置 ===
        leverage_cfg = strategy_cfg.get('leverage', {})
        self.min_cash_ratio = leverage_cfg.get('min_cash_ratio', -1.0)  # 最低现金比率（-100%）
        self.max_leverage = leverage_cfg.get('max_leverage', 1.95)  # 最大杠杆倍数
        
        # === 出场配置 ===
        self.stop_loss = strategy_cfg.get('stop_loss', 0.10)  # 止损 -10%
        self.take_profit = strategy_cfg.get('take_profit', 0.20)  # 止盈 +20%
        self.holding_days = strategy_cfg.get('holding_days', 6)  # 持仓天数
        self.exit_time = strategy_cfg.get('exit_time', '15:00:00')  # 定时退出时间
        
        # === 黑名单配置 ===
        self.blacklist_days = strategy_cfg.get('blacklist_days', 15)  # 黑名单天数
        
        # === 交易成本 ===
        cost_cfg = strategy_cfg.get('cost', {})
        self.commission_per_share = cost_cfg.get('commission_per_share', 0.005)  # 每股手续费
        self.min_commission = cost_cfg.get('min_commission', 1.0)  # 最低手续费
        self.slippage = cost_cfg.get('slippage', 0.001)  # 单边滑点 0.1%
        
        # === 运行时状态 ===
        self.daily_trade_count = 0  # 当日交易计数
        self.blacklist: Dict[str, datetime] = {}  # 黑名单：{symbol: 买入时间}
        
        # 打印配置信息
        self.logger.info(
            f"StrategyV7 初始化完成:\n"
            f"  入场: 时间>={self.trade_start_time}, 延迟{self.entry_delay}分钟, "
            f"溢价>=${self.min_option_premium/1000:.0f}K, 历史{self.historical_premium_multiplier}倍\n"
            f"  仓位: 日限{self.max_daily_trades}次, 总仓<={self.max_daily_position:.0%}, "
            f"单仓<={self.max_single_position:.0%}\n"
            f"  杠杆: 现金>={self.min_cash_ratio:.0%}, 杠杆<={self.max_leverage:.2f}x\n"
            f"  出场: 止盈{self.take_profit:+.0%}, 止损{self.stop_loss:+.0%}, "
            f"持{self.holding_days}日@{self.exit_time}\n"
            f"  黑名单: {self.blacklist_days}日, 成本: ${self.commission_per_share}/股, "
            f"滑点{self.slippage:.1%}"
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
        
        # ===== 3. 历史Premium过滤（新增）=====
        # 回测时跳过（由回测引擎处理），通过检查 call_csv_dir 是否存在来判断
        if self.call_csv_dir.exists():
            if not self._check_historical_premium(ev.symbol, ev.premium_usd, ev.event_time_et):
                return None
        
        # ===== 4. 黑名单过滤 =====
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
        
        # ===== 5. 每日交易次数限制 =====
        if self.daily_trade_count >= self.max_daily_trades:
            self.logger.info(
                f"过滤: {ev.symbol} 今日已达交易上限 {self.daily_trade_count}/{self.max_daily_trades}"
            )
            return None
        
        # ===== 6. 获取账户信息 =====
        acc_info = market_client.get_account_info()
        if not acc_info:
            self.logger.error("获取账户信息失败")
            return None
        
        total_assets = acc_info['total_assets']
        cash = acc_info['cash']
        
        # ===== 7. 获取股票价格（Entry Delay处理）=====
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
        
        # ===== 8. 计算仓位比例 =====
        pos_ratio = min(ev.premium_usd / self.premium_divisor, self.max_single_position)
        
        # ===== 9. 计算股数（用基准价，不含滑点）=====
        target_value = total_assets * pos_ratio
        qty = int(target_value / current_price)  # 用基准价计算股数
        
        # 应用滑点（买入时价格上浮）
        buy_price = current_price * (1 + self.slippage)
        
        if qty <= 0:
            self.logger.debug(f"过滤: {ev.symbol} 计算股数为0")
            return None
        
        actual_cost = buy_price * qty
        
        # 计算手续费
        commission = max(qty * self.commission_per_share, self.min_commission)
        total_cost = actual_cost + commission
        
        self.logger.debug(
            f"仓位计算: 溢价${ev.premium_usd:,.0f} → 仓位{pos_ratio:.1%} → "
            f"{qty}股 × ${buy_price:.2f} = ${actual_cost:,.2f} (含手续费${commission:.2f})"
        )
        
        # ===== 10. 检查总仓位限制 =====
        positions = market_client.get_positions()
        current_position_value = 0
        
        if positions:
            # 检查是否已持有该股票
            for pos in positions:
                if pos['symbol'] == ev.symbol and pos['position'] > 0:
                    self.logger.info(f"过滤: {ev.symbol} 已持有仓位，避免重复开仓")
                    return None
                
                current_position_value += pos.get('market_value', 0)
        
        # current_position_ratio = current_position_value / total_assets  # 当前仓位比例（暂未使用）
        new_total_position_ratio = (current_position_value + actual_cost) / total_assets
        
        if new_total_position_ratio > self.max_daily_position:
            self.logger.info(
                f"过滤: {ev.symbol} 总仓位将超限 {new_total_position_ratio:.1%} > "
                f"{self.max_daily_position:.0%}"
            )
            return None
        
        # ===== 11. 检查杠杆限制 =====
        # 计算交易后的现金比率
        cash_after = cash - total_cost
        cash_ratio_after = cash_after / total_assets
        
        if cash_ratio_after < self.min_cash_ratio:
            self.logger.info(
                f"过滤: {ev.symbol} 现金比率将低于下限 {cash_ratio_after:.1%} < "
                f"{self.min_cash_ratio:.0%}"
            )
            return None
        
        # 计算交易后的杠杆倍数（用基准价计算仓位价值，不含滑点）
        position_value_no_slippage = qty * current_price  # 用基准价
        position_value_after = current_position_value + position_value_no_slippage
        total_assets_after = cash_after + position_value_after  # 交易后的总资产
        leverage_after = position_value_after / total_assets_after if total_assets_after > 0 else 0
        
        if leverage_after > self.max_leverage:
            self.logger.info(
                f"过滤: {ev.symbol} 杠杆倍数将超限 {leverage_after:.1%} > {self.max_leverage:.0%}"
            )
            return None
        
        # ===== 12. 生成开仓决策 =====
        client_id = f"{ev.symbol}_{ev.event_time_et.strftime('%Y%m%d%H%M%S')}"
        
        self.logger.info(
            f"✓ 开仓决策: {ev.symbol} {qty}股 @${buy_price:.2f} "
            f"(仓位{pos_ratio:.1%}, 溢价${ev.premium_usd:,.0f}, "
            f"历史倍数{self.historical_premium_multiplier}x, "
            f"杠杆{leverage_after:.2f}x)"
        )
        
        return EntryDecision(
            symbol=ev.symbol,
            shares=qty,
            price_limit=buy_price,
            t_exec_et=entry_time_et,  # 使用延迟后的买入时刻
            pos_ratio=pos_ratio,
            client_id=client_id,
            meta={
                'event_id': ev.event_id,
                'premium_usd': ev.premium_usd,
                'signal_time': ev.event_time_et.isoformat(),
                'entry_delay': self.entry_delay,
                'buy_price_no_slippage': current_price,
                'slippage': self.slippage,
                'commission': commission,
                'leverage': leverage_after,
                'cash_ratio_after': cash_ratio_after
            }
        )

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

    def on_position_check(self, market_client=None, entry_time_map=None):
        """
        检查持仓，生成平仓决策
        
        出场优先级：
        1. 定时退出（持仓第N天下午3:00）
        2. 止损（-10%）
        3. 止盈（+20%）
        
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
        
        exit_decisions = []
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
            
            # 应用滑点（卖出时价格下浮）
            sell_price = current_price * (1 - self.slippage)
            
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
            
            # ===== 2. 止损检查 =====
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
                        'sell_price': sell_price,
                        'slippage': self.slippage
                    }
                ))
                continue
            
            # ===== 3. 止盈检查 =====
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
                        'sell_price': sell_price,
                        'slippage': self.slippage
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
            sell_price: 卖出价（已包含滑点）
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
                        f"✓ 平仓决策[定时退出]: {symbol} {can_sell_qty}股 @${sell_price:.2f} "
                        f"(成本${cost_price:.2f}, 持仓{trading_days_held}日, 盈亏{pnl_ratio:+.1%})"
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

