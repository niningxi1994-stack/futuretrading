"""
回测用的模拟市场客户端
完全模拟 FutuClient 的接口，从CSV文件读取历史数据
"""

import csv
import logging
import pytz
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timedelta


class BacktestMarketClient:
    """回测用的模拟市场客户端（模拟FutuClient接口）"""
    
    def __init__(self, stock_data_dir: str, initial_cash: float = 100000.0):
        """
        初始化回测客户端
        
        Args:
            stock_data_dir: 股价数据目录
            initial_cash: 初始资金
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.stock_data_dir = Path(stock_data_dir)
        
        # 账户信息
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: Dict[str, Dict] = {}  # {symbol: {shares, cost_price, market_price, highest_price, ...}}
        
        # 订单记录
        self.orders: List[Dict] = []
        self.order_id_counter = 1
        
        # 股价数据缓存 {symbol: DataFrame}
        self.stock_price_cache: Dict[str, pd.DataFrame] = {}
        
        # 当前时间（用于获取历史价格）
        self.current_time: Optional[datetime] = None
        
        self.logger.info(
            f"回测客户端初始化: 股价目录={stock_data_dir}, "
            f"初始资金=${initial_cash:,.2f}"
        )
    
    def connect(self) -> bool:
        """模拟连接，总是成功"""
        self.logger.info("模拟连接成功")
        return True
    
    def disconnect(self):
        """模拟断开连接"""
        self.logger.info("模拟断开连接")
    
    def set_current_time(self, current_time: datetime):
        """
        设置当前时间（回测进度）
        
        Args:
            current_time: 当前时间
        """
        self.current_time = current_time
        
        # 更新所有持仓的市价和最高价（用当前时刻价格）
        for symbol in list(self.positions.keys()):
            if self.positions[symbol]['position'] > 0:
                price = self._get_price_at_time(symbol, current_time)
                if price:
                    self.positions[symbol]['market_price'] = price
                    self.positions[symbol]['market_value'] = price * self.positions[symbol]['position']
                    
                    # 更新最高价
                    if 'highest_price' not in self.positions[symbol]:
                        self.positions[symbol]['highest_price'] = self.positions[symbol]['cost_price']
                    if price > self.positions[symbol]['highest_price']:
                        self.positions[symbol]['highest_price'] = price
    
    def _load_stock_price_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        加载股票的分钟级价格数据（使用pandas加速）
        
        Args:
            symbol: 股票代码
            
        Returns:
            DataFrame with datetime index
        """
        # 检查缓存
        if symbol in self.stock_price_cache:
            return self.stock_price_cache[symbol]
        
        # 查找该股票的所有CSV文件
        stock_files = list(self.stock_data_dir.glob(f"{symbol}_*.csv"))
        
        if not stock_files:
            self.logger.warning(f"未找到 {symbol} 的股价数据")
            return None
        
        # 加载并合并所有文件（使用pandas）
        all_dfs = []
        for stock_file in stock_files:
            try:
                df = pd.read_csv(stock_file)
                df['datetime'] = pd.to_datetime(df['timestamp'])
                all_dfs.append(df)
            except Exception as e:
                self.logger.debug(f"加载股价文件失败 {stock_file}: {e}")
        
        if not all_dfs:
            return None
        
        # 合并、去重、排序
        merged_df = pd.concat(all_dfs, ignore_index=True)
        merged_df = merged_df.drop_duplicates(subset=['timestamp']).sort_values('datetime').reset_index(drop=True)
        merged_df = merged_df.set_index('datetime')
        
        # 缓存
        self.stock_price_cache[symbol] = merged_df
        
        self.logger.debug(f"加载 {symbol} 股价数据: {len(merged_df)}条")
        return merged_df
    
    def _get_price_at_time(self, symbol: str, target_time: datetime) -> Optional[float]:
        """
        获取指定时间的股价（向下取整到当前分钟）
        
        例如：15:30:29 → 使用15:30:00的close价格
        
        Args:
            symbol: 股票代码
            target_time: 目标时间
            
        Returns:
            股价（close价格）
        """
        df = self._load_stock_price_data(symbol)
        if df is None or len(df) == 0:
            return None
        
        # 去掉时区信息（因为DataFrame的index是tz-naive）
        if hasattr(target_time, 'tzinfo') and target_time.tzinfo is not None:
            target_time = target_time.replace(tzinfo=None)
        
        # 向下取整到当前分钟
        target_time = target_time.replace(second=0, microsecond=0)
        
        # 使用pandas查询（加速）- 取>=target_time的第一条
        future_data = df[df.index >= target_time]
        if len(future_data) == 0:
            return None
        
        return future_data.iloc[0]['close']
    
    def get_stock_price(self, symbol: str) -> Optional[Dict]:
        """
        获取股票价格（模拟FutuClient接口，从CSV读取）
        返回当前时刻的价格（通过entry_delay控制买入延迟）
        
        Args:
            symbol: 股票代码
            
        Returns:
            价格信息字典
        """
        if not self.current_time:
            self.logger.warning("未设置当前时间，无法获取价格")
            return None
        
        # 使用当前时刻的价格
        price = self._get_price_at_time(symbol, self.current_time)
        if price:
            return {
                'last_price': price,
                'open': price,
                'high': price,
                'low': price,
                'prev_close': price,
                'volume': 0,
                'turnover': 0.0,
                'bid': price * 0.999,
                'ask': price * 1.001,
                'update_time': self.current_time
            }
        else:
            self.logger.warning(f"未找到 {symbol} 在 {self.current_time} 的价格数据")
            return None
    
    def get_account_info(self) -> Optional[Dict]:
        """
        获取账户信息
        
        Returns:
            账户信息字典
        """
        # 计算持仓市值
        position_value = sum(pos['market_value'] for pos in self.positions.values())
        
        # 总资产 = 现金 + 持仓市值
        total_assets = self.cash + position_value
        
        return {
            'cash': self.cash,
            'market_value': position_value,
            'total_assets': total_assets,
            'available_cash': self.cash,
            'power': self.cash,  # 购买力
        }
    
    def get_positions(self) -> List[Dict]:
        """
        获取持仓列表
        
        Returns:
            持仓列表
        """
        positions = []
        for symbol, pos in self.positions.items():
            if pos['position'] > 0:
                positions.append({
                    'symbol': symbol,
                    'position': pos['position'],
                    'can_sell_qty': pos['position'],  # 回测中假设都可卖
                    'cost_price': pos['cost_price'],
                    'market_price': pos['market_price'],
                    'market_value': pos['market_value'],
                    'pnl': (pos['market_price'] - pos['cost_price']) * pos['position'],
                    'pnl_ratio': (pos['market_price'] - pos['cost_price']) / pos['cost_price'] if pos['cost_price'] > 0 else 0,
                })
        return positions
    
    def buy_stock(self, symbol: str, quantity: int, price: float, 
                  order_type: str = 'LIMIT') -> Optional[str]:
        """
        买入股票（模拟）
        
        Args:
            symbol: 股票代码
            quantity: 数量
            price: 价格
            order_type: 订单类型
            
        Returns:
            订单ID
        """
        # 计算成本
        cost = price * quantity
        
        # 检查现金是否充足（允许负现金，最低-100%）
        acc_info = self.get_account_info()
        total_assets = acc_info['total_assets']
        cash_after = self.cash - cost
        cash_ratio_after = cash_after / total_assets
        
        # 检查现金比率下限（-100%）
        if cash_ratio_after < -1.0:
            self.logger.warning(
                f"买入失败: 现金不足 {symbol}, "
                f"需要${cost:,.2f}, 交易后现金比率{cash_ratio_after:.1%} < -100%"
            )
            return None
        
        # 扣除现金
        self.cash -= cost
        
        # 添加或更新持仓
        if symbol in self.positions:
            # 已有持仓，计算平均成本
            old_pos = self.positions[symbol]
            old_shares = old_pos['position']
            old_cost = old_pos['cost_price']
            
            new_shares = old_shares + quantity
            new_cost = (old_cost * old_shares + price * quantity) / new_shares
            
            self.positions[symbol] = {
                'position': new_shares,
                'cost_price': new_cost,
                'market_price': price,
                'market_value': price * new_shares,
            }
        else:
            # 新建持仓
            self.positions[symbol] = {
                'position': quantity,
                'cost_price': price,
                'market_price': price,
                'market_value': price * quantity,
                'highest_price': price,  # 追踪最高价
            }
        
        # 生成订单ID
        order_id = f"BUY_{self.order_id_counter:06d}"
        self.order_id_counter += 1
        
        # 记录订单
        et_tz = pytz.timezone('America/New_York')
        self.orders.append({
            'order_id': order_id,
            'symbol': symbol,
            'side': 'BUY',
            'quantity': quantity,
            'price': price,
            'order_type': order_type,
            'status': 'FILLED',
            'filled_qty': quantity,
            'avg_price': price,
            'time': self.current_time if self.current_time else datetime.now(et_tz),
        })
        
        self.logger.info(
            f"买入成功: {symbol} {quantity}股 @${price:.2f}, "
            f"成本${cost:,.2f}, 剩余现金${self.cash:,.2f}"
        )
        
        return order_id
    
    def sell_stock(self, symbol: str, quantity: int, price: float,
                   order_type: str = 'LIMIT') -> Optional[str]:
        """
        卖出股票（模拟）
        
        Args:
            symbol: 股票代码
            quantity: 数量
            price: 价格
            order_type: 订单类型
            
        Returns:
            订单ID
        """
        # 检查是否有持仓
        if symbol not in self.positions or self.positions[symbol]['position'] < quantity:
            self.logger.warning(f"卖出失败: 持仓不足 {symbol}")
            return None
        
        # 增加现金
        proceeds = price * quantity
        self.cash += proceeds
        
        # 减少持仓
        pos = self.positions[symbol]
        cost_price = pos['cost_price']
        
        pos['position'] -= quantity
        pos['market_value'] = pos['market_price'] * pos['position']
        
        # 如果持仓为0，删除
        if pos['position'] == 0:
            del self.positions[symbol]
        
        # 生成订单ID
        order_id = f"SELL_{self.order_id_counter:06d}"
        self.order_id_counter += 1
        
        # 计算盈亏
        pnl = (price - cost_price) * quantity
        pnl_ratio = (price - cost_price) / cost_price
        
        # 记录订单
        et_tz = pytz.timezone('America/New_York')
        self.orders.append({
            'order_id': order_id,
            'symbol': symbol,
            'side': 'SELL',
            'quantity': quantity,
            'price': price,
            'order_type': order_type,
            'status': 'FILLED',
            'filled_qty': quantity,
            'avg_price': price,
            'time': self.current_time if self.current_time else datetime.now(et_tz),
            'pnl': pnl,
            'pnl_ratio': pnl_ratio,
        })
        
        self.logger.info(
            f"卖出成功: {symbol} {quantity}股 @${price:.2f}, "
            f"收入${proceeds:,.2f}, 盈亏${pnl:+,.2f} ({pnl_ratio:+.1%}), "
            f"现金${self.cash:,.2f}"
        )
        
        return order_id
    
    def get_order_list(self, status_filter: str = None, symbol_filter: str = None) -> List[Dict]:
        """
        获取订单列表
        
        Args:
            status_filter: 状态过滤
            symbol_filter: 股票代码过滤
            
        Returns:
            订单列表
        """
        orders = self.orders
        
        if status_filter:
            orders = [o for o in orders if o['status'] == status_filter]
        
        if symbol_filter:
            orders = [o for o in orders if o['symbol'] == symbol_filter]
        
        return orders
    
    def count_trading_days_between(self, start_date: str, end_date: str, market: str = 'US') -> Optional[int]:
        """
        计算交易日数量（简单实现，仅排除周末）
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            market: 市场
            
        Returns:
            交易日数量
        """
        from datetime import datetime, timedelta
        
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        trading_days = 0
        current = start
        
        while current <= end:
            if current.weekday() < 5:  # 周一到周五
                trading_days += 1
            current += timedelta(days=1)
        
        return trading_days
    
    def get_summary(self) -> Dict:
        """
        获取账户汇总信息
        
        Returns:
            汇总信息字典
        """
        acc_info = self.get_account_info()
        
        # 计算总盈亏
        total_pnl = acc_info['total_assets'] - self.initial_cash
        total_pnl_ratio = total_pnl / self.initial_cash
        
        # 统计交易
        buy_orders = [o for o in self.orders if o['side'] == 'BUY']
        sell_orders = [o for o in self.orders if o['side'] == 'SELL']
        
        # 计算已实现盈亏
        realized_pnl = sum(o.get('pnl', 0) for o in sell_orders)
        
        # 计算未实现盈亏
        unrealized_pnl = sum(pos['pnl'] for pos in self.get_positions())
        
        return {
            'initial_cash': self.initial_cash,
            'cash': self.cash,
            'position_value': acc_info['market_value'],
            'total_assets': acc_info['total_assets'],
            'total_pnl': total_pnl,
            'total_pnl_ratio': total_pnl_ratio,
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'num_trades': len(buy_orders),
            'num_positions': len(self.positions),
        }

