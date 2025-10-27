"""
V8 事件驱动期权流动量策略 - 简化版本（直接买入 + 固定仓位）

核心特性：
- 数据源：CSV历史数据（merged_strategy_v1_calls_bell_2023M3_2025M9.csv）
- 入场：直接买入，无复杂过滤
- 仓位：固定20%
- 出场优先级：
  1. 达到expiry日期 + 10:00 AM 卖出
  2. 达到strike价格 卖出
  3. 止盈+20% 卖出
  4. 止损-10% 卖出
"""

import logging
from datetime import date, datetime, time, timedelta
from typing import Optional, Dict
from zoneinfo import ZoneInfo
from pathlib import Path

try:
    from .strategy import StrategyBase, StrategyContext, EntryDecision, ExitDecision
except ImportError:
    from strategy import StrategyBase, StrategyContext, EntryDecision, ExitDecision


class StrategyV8(StrategyBase):
    """V8 事件驱动期权流动量策略 - 简化版本"""
    
    def __init__(self, context: StrategyContext):
        super().__init__(context)
        
        # 读取 strategy 配置
        strategy_cfg = self.cfg.get('strategy', {})
        
        # === 入场配置 ===
        filter_cfg = strategy_cfg.get('filter', {})
        
        # 交易时间窗口（支持多个时间段）
        self.trade_time_ranges = filter_cfg.get('trade_time_ranges', [])
        # 向后兼容：如果没有配置ranges，使用trade_start_time
        if not self.trade_time_ranges and 'trade_start_time' in filter_cfg:
            self.trade_time_ranges = [[filter_cfg.get('trade_start_time', '09:30:00'), '16:00:00']]
        
        self.market_close_buffer = filter_cfg.get('market_close_buffer', 6)
        
        # DTE过滤
        self.dte_min = filter_cfg.get('dte_min', 0)
        self.dte_max = filter_cfg.get('dte_max', 999999)
        
        # OTM率过滤
        self.otm_max = filter_cfg.get('otm_max', 100.0)
        self.otm_min = filter_cfg.get('otm_min', 0.0)
        
        # === 仓位配置（固定20%）===
        position_cfg = strategy_cfg.get('position_compute', {})
        self.fixed_position_ratio = position_cfg.get('fixed_position_ratio', 0.20)  # 固定20%
        self.max_daily_position = position_cfg.get('max_daily_position', 0.99)  # 每日总仓位上限
        
        # === 出场配置 ===
        self.stop_loss = strategy_cfg.get('stop_loss', 0.10)  # 止损 -10%
        self.take_profit = strategy_cfg.get('take_profit', 0.20)  # 止盈 +20%
        self.exit_time = strategy_cfg.get('exit_time', '10:00:00')  # 定时退出时间（expiry日10:00）
        
        # === 运行时状态 ===
        self.daily_trade_count = 0
        self.position_metadata: Dict[str, Dict] = {}  # {symbol: {strike, expiry, ...}}
        self.highest_price_map: Dict[str, float] = {}  # 追踪最高价
        
        # 打印配置信息
        time_ranges_str = ', '.join([f"{r[0]}-{r[1]}" for r in self.trade_time_ranges]) if self.trade_time_ranges else '全天'
        self.logger.info(
            f"StrategyV8 初始化完成:\n"
            f"  入场: 时间={time_ranges_str}, DTE={self.dte_min}-{self.dte_max}天, OTM={self.otm_min:.1f}-{self.otm_max:.1f}%\n"
            f"  仓位: 固定{self.fixed_position_ratio:.0%}, 日限<={self.max_daily_position:.0%}\n"
            f"  出场: strike/expiry(10:00)/止盈{self.take_profit:+.0%}/止损{self.stop_loss:+.0%}"
        )

    def on_start(self):
        """策略启动"""
        self.logger.info("StrategyV8 启动")

    def on_shutdown(self):
        """策略关闭"""
        self.logger.info("StrategyV8 关闭")

    def on_day_open(self, trading_date_et: date):
        """交易日开盘"""
        self.logger.info(f"交易日开盘: {trading_date_et}")

    def on_day_close(self, trading_date_et: date):
        """交易日收盘"""
        self.logger.info(f"交易日收盘: {trading_date_et}")

    def on_signal(self, ev, market_client=None):
        """
        处理信号事件，生成开仓决策
        
        V8优化版本：加入DTE、OTM、时间窗口过滤
        
        Args:
            ev: SignalEvent 信号事件
            market_client: 市场数据客户端实例
            
        Returns:
            EntryDecision 或 None
        """
        if not market_client:
            self.logger.error("市场数据客户端未提供，无法处理信号")
            return None
        
        # ===== 1. 时间窗口过滤 =====
        current_time = ev.event_time_et.time()
        
        # 检查是否在配置的时间窗口内
        if self.trade_time_ranges:
            in_time_range = False
            for time_range in self.trade_time_ranges:
                start_time = datetime.strptime(time_range[0], '%H:%M:%S').time()
                end_time = datetime.strptime(time_range[1], '%H:%M:%S').time()
                if start_time <= current_time <= end_time:
                    in_time_range = True
                    break
            
            if not in_time_range:
                self.logger.info(
                    f"过滤[时间窗口]: {ev.symbol} 不在交易时段 {current_time}"
                )
                return None
        
        # 检查距离收盘时间
        market_close = time(15, 54, 0)
        if current_time >= market_close:
            self.logger.info(
                f"过滤[接近收盘]: {ev.symbol} 时间={current_time}"
            )
            return None
        
        # ===== 2. DTE过滤 =====
        if hasattr(ev, 'expiry') and ev.expiry:
            expiry_date = ev.expiry if isinstance(ev.expiry, date) else datetime.strptime(str(ev.expiry), '%Y-%m-%d').date()
            current_date = ev.event_time_et.date()
            dte = (expiry_date - current_date).days
            
            if dte < self.dte_min:
                self.logger.info(
                    f"过滤[DTE过短]: {ev.symbol} DTE={dte}天 < {self.dte_min}天"
                )
                return None
            
            if dte > self.dte_max:
                self.logger.info(
                    f"过滤[DTE过长]: {ev.symbol} DTE={dte}天 > {self.dte_max}天"
                )
                return None
        else:
            dte = None
            self.logger.warning(f"{ev.symbol} 缺少expiry信息，无法计算DTE")
        
        # ===== 3. OTM率过滤（使用CSV中的stock_price，避免合股等问题）=====
        if hasattr(ev, 'strike') and ev.strike and hasattr(ev, 'stock_price') and ev.stock_price:
            strike = float(ev.strike)
            signal_stock_price = float(ev.stock_price)  # 使用CSV中的价格
            
            # 计算OTM率 (对于call期权)
            otm_rate = (strike - signal_stock_price) / signal_stock_price * 100
            
            if otm_rate > self.otm_max:
                self.logger.info(
                    f"过滤[OTM过高]: {ev.symbol} OTM={otm_rate:.2f}% > {self.otm_max:.1f}% "
                    f"(Strike=${strike:.2f}, SignalPrice=${signal_stock_price:.2f})"
                )
                return None
            
            if otm_rate < self.otm_min:
                self.logger.info(
                    f"过滤[OTM过低]: {ev.symbol} OTM={otm_rate:.2f}% < {self.otm_min:.1f}%"
                )
                return None
        else:
            otm_rate = None
            if not (hasattr(ev, 'strike') and ev.strike):
                self.logger.warning(f"{ev.symbol} 缺少strike信息，无法计算OTM率")
            elif not (hasattr(ev, 'stock_price') and ev.stock_price):
                self.logger.warning(f"{ev.symbol} 缺少stock_price信息，无法计算OTM率")
        
        # ===== 4. 获取股票价格（用于实际买入）=====
        market_client.set_current_time(ev.event_time_et)
        
        price_info = market_client.get_stock_price(ev.symbol)
        if not price_info:
            self.logger.error(f"获取 {ev.symbol} 价格失败")
            return None
        
        current_price = price_info['last_price']
        
        # ===== 5. 获取账户信息 =====
        acc_info = market_client.get_account_info()
        if not acc_info:
            self.logger.error("获取账户信息失败")
            return None
        
        total_assets = acc_info['total_assets']
        cash = acc_info['cash']
        
        # ===== 6. 计算仓位（固定比例）=====
        target_value = total_assets * self.fixed_position_ratio
        qty = int(target_value / current_price)
        
        if qty <= 0:
            self.logger.debug(f"过滤: {ev.symbol} 计算股数为0")
            return None
        
        target_cost = current_price * qty
        
        self.logger.debug(
            f"仓位计算: 固定比例{self.fixed_position_ratio:.0%} → "
            f"{qty}股 × ${current_price:.2f} = ${target_cost:,.2f}"
        )
        
        # ===== 7. 检查总仓位限制 =====
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
        
        # ===== 8. 检查现金充足性 =====
        if cash < target_cost:
            self.logger.info(
                f"过滤: {ev.symbol} 现金不足 需要${target_cost:,.2f}, 剩余${cash:,.2f}"
            )
            return None
        
        # ===== 9. 生成开仓决策 =====
        client_id = f"{ev.symbol}_{ev.event_time_et.strftime('%Y%m%d%H%M%S')}"
        
        # 构建详细日志
        log_parts = [
            f"✓ 开仓决策: {ev.symbol} {qty}股 @${current_price:.2f}",
            f"仓位{self.fixed_position_ratio:.0%}"
        ]
        if dte is not None:
            log_parts.append(f"DTE={dte}天")
        if otm_rate is not None:
            log_parts.append(f"OTM={otm_rate:.2f}%")
        
        self.logger.info(", ".join(log_parts))
        
        # 准备元数据
        meta_data = {
            'event_id': ev.event_id,
            'signal_time': ev.event_time_et.isoformat(),
        }
        if dte is not None:
            meta_data['dte'] = dte
        if otm_rate is not None:
            meta_data['otm_rate'] = otm_rate
        
        return EntryDecision(
            symbol=ev.symbol,
            shares=qty,
            price_limit=current_price,
            t_exec_et=ev.event_time_et,
            pos_ratio=self.fixed_position_ratio,
            client_id=client_id,
            meta=meta_data
        )

    def on_minute_check(self, market_client=None, entry_time_map=None):
        """每分钟检查持仓"""
        return self.on_position_check(market_client, entry_time_map)
    
    def on_position_check(self, market_client=None, entry_time_map=None):
        """
        检查持仓，生成平仓决策
        
        出场优先级：
        1. 达到expiry日期 + 10:00 AM 卖出
        2. 达到strike价格 卖出
        3. 止盈+20% 卖出
        4. 止损-10% 卖出
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
        
        # 获取当前时间
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
            
            # 跳过可卖数量为0的持仓，以及当前没有价格数据的持仓
            if can_sell_qty <= 0:
                continue
            
            # 如果没有价格数据（比如股票停盘），跳过该持仓的检查
            # 等待下一个有数据的交易日再处理
            if current_price is None or current_price <= 0:
                self.logger.debug(f"跳过 {symbol}：无价格数据（可能停盘）")
                continue
            
            # 计算盈亏比例
            pnl_ratio = (current_price - cost_price) / cost_price
            
            # 更新历史最高价
            if symbol not in self.highest_price_map:
                self.highest_price_map[symbol] = max(cost_price, current_price)
            else:
                self.highest_price_map[symbol] = max(self.highest_price_map[symbol], current_price)
            
            # ===== 1. 检查strike价格出场 =====
            # 目标价 = strike + option_price (期权本身的价格)
            if symbol in self.position_metadata:
                meta = self.position_metadata[symbol]
                if 'strike' in meta and 'option_price' in meta:
                    strike = meta['strike']
                    option_price = meta['option_price']
                    target_price = strike + option_price  # strike + spot
                    
                    if current_price >= target_price:
                        self.logger.info(
                            f"✓ 平仓决策[达到目标价]: {symbol} {can_sell_qty}股 @${current_price:.2f} "
                            f"(成本${cost_price:.2f}, Strike=${strike:.2f}, 期权价=${option_price:.2f}, "
                            f"目标=${target_price:.2f}, 盈亏{pnl_ratio:+.1%})"
                        )
                        exit_decisions.append(ExitDecision(
                            symbol=symbol,
                            shares=can_sell_qty,
                            price_limit=current_price,
                            reason='strike_price',
                            client_id=f"{symbol}_ST_{current_et.strftime('%Y%m%d%H%M%S')}",
                            meta={'pnl_ratio': pnl_ratio, 'strike': strike, 'target_price': target_price}
                        ))
                        # 清除元数据
                        if symbol in self.position_metadata:
                            del self.position_metadata[symbol]
                        if symbol in self.highest_price_map:
                            del self.highest_price_map[symbol]
                        continue
            
            # ===== 2. 检查expiry日期出场 =====
            if symbol in self.position_metadata:
                meta = self.position_metadata[symbol]
                if 'expiry' in meta:
                    expiry_date = meta['expiry']
                    current_date = current_et.date()
                    
                    if current_date >= expiry_date and current_et.time() >= exit_time_today:
                        self.logger.info(
                            f"✓ 平仓决策[expiry到期]: {symbol} {can_sell_qty}股 @${current_price:.2f} "
                            f"(成本${cost_price:.2f}, 到期日{expiry_date}, 盈亏{pnl_ratio:+.1%})"
                        )
                        exit_decisions.append(ExitDecision(
                            symbol=symbol,
                            shares=can_sell_qty,
                            price_limit=current_price,
                            reason='expiry_date',
                            client_id=f"{symbol}_EX_{current_et.strftime('%Y%m%d%H%M%S')}",
                            meta={'pnl_ratio': pnl_ratio, 'expiry': expiry_date.isoformat()}
                        ))
                        # 清除元数据
                        if symbol in self.position_metadata:
                            del self.position_metadata[symbol]
                        if symbol in self.highest_price_map:
                            del self.highest_price_map[symbol]
                        continue
            
            # ===== 3. 检查止损 =====
            stop_loss_price = cost_price * (1 - self.stop_loss)
            if current_price <= stop_loss_price:
                self.logger.info(
                    f"✓ 平仓决策[止损]: {symbol} {can_sell_qty}股 @${current_price:.2f} "
                    f"(成本${cost_price:.2f}, 止损价${stop_loss_price:.2f}, 亏损{pnl_ratio:.1%})"
                )
                exit_decisions.append(ExitDecision(
                    symbol=symbol,
                    shares=can_sell_qty,
                    price_limit=current_price,
                    reason='stop_loss',
                    client_id=f"{symbol}_SL_{current_et.strftime('%Y%m%d%H%M%S')}",
                    meta={'pnl_ratio': pnl_ratio, 'stop_loss_price': stop_loss_price}
                ))
                # 清除元数据和最高价
                if symbol in self.position_metadata:
                    del self.position_metadata[symbol]
                if symbol in self.highest_price_map:
                    del self.highest_price_map[symbol]
                continue
            
            # ===== 4. 检查止盈 =====
            take_profit_price = cost_price * (1 + self.take_profit)
            if current_price >= take_profit_price:
                self.logger.info(
                    f"✓ 平仓决策[止盈]: {symbol} {can_sell_qty}股 @${current_price:.2f} "
                    f"(成本${cost_price:.2f}, 止盈价${take_profit_price:.2f}, 盈利{pnl_ratio:.1%})"
                )
                exit_decisions.append(ExitDecision(
                    symbol=symbol,
                    shares=can_sell_qty,
                    price_limit=current_price,
                    reason='take_profit',
                    client_id=f"{symbol}_TP_{current_et.strftime('%Y%m%d%H%M%S')}",
                    meta={'pnl_ratio': pnl_ratio, 'take_profit_price': take_profit_price}
                ))
                # 清除元数据和最高价
                if symbol in self.position_metadata:
                    del self.position_metadata[symbol]
                if symbol in self.highest_price_map:
                    del self.highest_price_map[symbol]
                continue
        
        return exit_decisions

    def store_position_metadata(self, symbol: str, strike: float, expiry: date, option_price: float = None):
        """存储持仓的strike、expiry和期权价格信息（由回测器调用）"""
        self.position_metadata[symbol] = {
            'strike': strike,
            'expiry': expiry,
            'option_price': option_price  # spot from signal (option ask price)
        }

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
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 读取配置文件
    config_path = Path(__file__).parent.parent.parent / 'config_v8.yaml'
    
    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        sys.exit(1)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 创建策略上下文
    context = StrategyContext(
        cfg=config,
        logger=logging.getLogger('StrategyV8')
    )
    
    # 创建策略实例
    strategy = StrategyV8(context)
    
    print("\n✓ StrategyV8 测试成功")
    print(f"  固定仓位: {strategy.fixed_position_ratio:.0%}")
    print(f"  每日总仓位上限: {strategy.max_daily_position:.0%}")
    print(f"  止损/止盈: {strategy.stop_loss:.0%} / {strategy.take_profit:.0%}")
    print(f"  expiry出场时间: {strategy.exit_time}")
