"""
策略基类
定义策略接口和抽象方法
"""

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class SignalEvent:
    """信号事件"""
    event_id: str
    symbol: str
    premium_usd: float
    ask: Optional[float]
    chain_id: Optional[str]
    event_time_cn: datetime
    event_time_et: datetime
    strike: Optional[float] = None
    expiry: Optional[date] = None
    spot: Optional[float] = None  # option price from signal
    stock_price: Optional[float] = None  # stock price from signal (CSV price column)


@dataclass
class EntryDecision:
    """开仓决策"""
    symbol: str
    shares: int
    price_limit: float
    t_exec_et: datetime
    pos_ratio: float
    client_id: str
    meta: Dict[str, Any]


@dataclass
class ExitDecision:
    """平仓决策"""
    symbol: str
    shares: int
    price_limit: float
    reason: str  # "SL", "TP", "Timed", "Manual"
    client_id: str
    meta: Dict[str, Any]


@dataclass
class PositionView:
    """持仓视图"""
    position_id: str
    open_id: str
    symbol: str
    shares: int
    price_in: float
    fee_in: float
    open_time_et: datetime
    exit_due_et: datetime
    meta: Dict[str, Any]


@dataclass
class OrderResult:
    """订单结果"""
    client_id: str
    status: str  # "FILLED", "PARTIAL", "REJECTED", "CANCELLED", "PENDING"
    filled_shares: int
    avg_price: Optional[float]
    ts_et: datetime
    broker_order_id: Optional[str]
    raw: Dict[str, Any]


class StrategyContext:
    """
    策略上下文（依赖注入）
    提供策略运行所需的各种服务
    """
    
    def __init__(self, cfg: Dict[str, Any], logger: logging.Logger):
        """
        初始化策略上下文
        
        Args:
            cfg: 配置字典
            logger: 日志器
        """
        self.cfg = cfg
        self.logger = logger
        # 后续可以注入 repo, mkt 等服务


class StrategyBase(ABC):
    """
    策略基类（抽象类）
    定义策略必须实现的接口方法
    """
    
    def __init__(self, context: StrategyContext):
        """
        初始化策略
        
        Args:
            context: 策略上下文
        """
        self.context = context
        self.logger = context.logger
        self.cfg = context.cfg
    
    # ============ 生命周期方法 ============
    
    @abstractmethod
    def on_start(self) -> None:
        """策略启动时调用"""
        pass
    
    @abstractmethod
    def on_shutdown(self) -> None:
        """策略关闭时调用"""
        pass
    
    @abstractmethod
    def on_day_open(self, trading_date_et: date) -> None:
        """
        交易日开盘时调用
        
        Args:
            trading_date_et: 交易日期（美东时间）
        """
        pass
    
    @abstractmethod
    def on_day_close(self, trading_date_et: date) -> None:
        """
        交易日收盘时调用
        
        Args:
            trading_date_et: 交易日期（美东时间）
        """
        pass
    
    # ============ 信号处理方法 ============
    
    @abstractmethod
    def on_signal(self, ev: SignalEvent) -> Optional[EntryDecision]:
        """
        处理信号事件，决定是否开仓
        
        Args:
            ev: 信号事件
            
        Returns:
            EntryDecision: 开仓决策，如果不开仓则返回 None
        """
        pass
    
    @abstractmethod
    def on_position_check(self, pos: PositionView) -> Optional[ExitDecision]:
        """
        检查持仓，决定是否平仓
        
        Args:
            pos: 持仓视图
            
        Returns:
            ExitDecision: 平仓决策，如果不平仓则返回 None
        """
        pass
    
    # ============ 订单回调方法 ============
    
    @abstractmethod
    def on_order_filled(self, res: OrderResult) -> None:
        """
        订单成交回调
        
        Args:
            res: 订单结果
        """
        pass
    
    @abstractmethod
    def on_order_rejected(self, res: OrderResult, reason: str) -> None:
        """
        订单拒绝回调
        
        Args:
            res: 订单结果
            reason: 拒绝原因
        """
        pass


class SimpleStrategy(StrategyBase):
    """
    简单策略示例
    实现了所有抽象方法的基本版本
    """
    
    def on_start(self) -> None:
        """策略启动"""
        self.logger.info("策略启动")
    
    def on_shutdown(self) -> None:
        """策略关闭"""
        self.logger.info("策略关闭")
    
    def on_day_open(self, trading_date_et: date) -> None:
        """交易日开盘"""
        self.logger.info(f"交易日开盘: {trading_date_et}")
    
    def on_day_close(self, trading_date_et: date) -> None:
        """交易日收盘"""
        self.logger.info(f"交易日收盘: {trading_date_et}")
    
    def on_signal(self, ev: SignalEvent) -> Optional[EntryDecision]:
        """
        处理信号事件
        示例：仅记录日志，不产生交易决策
        """
        self.logger.info(
            f"收到信号: {ev.symbol}, "
            f"权利金: ${ev.premium_usd:,.0f}, "
            f"时间: {ev.event_time_et}"
        )
        # 这里可以添加策略逻辑
        return None
    
    def on_position_check(self, pos: PositionView) -> Optional[ExitDecision]:
        """
        检查持仓
        示例：不产生平仓决策
        """
        self.logger.debug(f"检查持仓: {pos.symbol}, {pos.shares} 股")
        # 这里可以添加止盈止损逻辑
        return None
    
    def on_order_filled(self, res: OrderResult) -> None:
        """订单成交"""
        self.logger.info(
            f"订单成交: {res.client_id}, "
            f"成交价: ${res.avg_price:.2f}, "
            f"成交量: {res.filled_shares}"
        )
    
    def on_order_rejected(self, res: OrderResult, reason: str) -> None:
        """订单拒绝"""
        self.logger.warning(
            f"订单拒绝: {res.client_id}, "
            f"原因: {reason}"
        )


if __name__ == '__main__':
    # 测试策略基类
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 创建策略上下文
    context = StrategyContext(
        cfg={'test': 'config'},
        logger=logging.getLogger('Strategy')
    )
    
    # 创建策略实例
    strategy = SimpleStrategy(context)
    
    # 测试生命周期方法
    strategy.on_start()
    strategy.on_day_open(date.today())
    
    # 测试信号处理
    signal = SignalEvent(
        event_id='test_001',
        symbol='AAPL',
        premium_usd=500000,
        ask=150.0,
        chain_id='AAPL_150_20251010',
        event_time_cn=datetime.now(),
        event_time_et=datetime.now()
    )
    strategy.on_signal(signal)
    
    # 测试关闭
    strategy.on_shutdown()

