"""
富途 OpenD 接口封装
提供股票交易相关的基础功能
"""

import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
from futu import (
    OpenQuoteContext,
    OpenSecTradeContext,
    TrdEnv,
    TrdSide,
    OrderType,
    TrdMarket,
    ModifyOrderOp,
    Market
)


def safe_int(val, default=0):
    """安全转换为整数，处理 'N/A' 等情况"""
    if val == 'N/A' or val is None or val == '':
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def safe_float(val, default=0.0):
    """安全转换为浮点数，处理 'N/A' 等情况"""
    if val == 'N/A' or val is None or val == '':
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class FutuClient:
    """
    富途交易客户端
    封装 FutuOpenD 的常用接口
    """
    
    def __init__(
        self, 
        host: str = '127.0.0.1', 
        port: int = 11111,
        trd_env: str = 'SIMULATE',  # 'SIMULATE' 或 'REAL'
        trd_market: str = 'US',      # 'US', 'HK', 'CN'
        acc_id: int = 0
    ):
        """
        初始化富途客户端
        
        Args:
            host: FutuOpenD 服务地址
            port: FutuOpenD 服务端口
            trd_env: 交易环境 ('SIMULATE' 模拟交易, 'REAL' 真实交易)
            trd_market: 交易市场 ('US' 美股, 'HK' 港股, 'CN' A股)
            acc_id: 账户ID (0表示使用默认账户)
        """
        self.host = host
        self.port = port
        self.acc_id = acc_id
        self.unlock_pwd = '153811'
        # 设置交易环境
        self.trd_env = TrdEnv.SIMULATE if trd_env == 'SIMULATE' else TrdEnv.REAL
        
        # 设置交易市场
        if trd_market == 'US':
            self.trd_market = TrdMarket.US
        elif trd_market == 'HK':
            self.trd_market = TrdMarket.HK
        elif trd_market == 'CN':
            self.trd_market = TrdMarket.CN
        else:
            raise ValueError(f"不支持的市场: {trd_market}")
        
        # 初始化上下文
        self.quote_ctx: Optional[OpenQuoteContext] = None
        self.trade_ctx: Optional[OpenSecTradeContext] = None
        
        # 日志
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"初始化富途客户端: {host}:{port}, 环境: {trd_env}, 市场: {trd_market}")
    
    def connect(self) -> bool:
        """
        连接 FutuOpenD
        
        Returns:
            bool: 连接是否成功
        """
        try:
            # 创建行情上下文
            self.quote_ctx = OpenQuoteContext(host=self.host, port=self.port)
            
            # 创建交易上下文
            self.trade_ctx = OpenSecTradeContext(
                host=self.host,
                port=self.port,
                filter_trdmarket=self.trd_market
            )
            
            # 解锁交易（模拟交易不需要密码）
            if self.trd_env == TrdEnv.REAL:
                self.logger.warning("真实交易需要手动解锁")
            
            self.logger.info("✓ 已连接到 FutuOpenD")
            return True
            
        except Exception as e:
            self.logger.error(f"连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
        if self.trade_ctx:
            self.trade_ctx.close()
        self.logger.info("已断开连接")
    
    # ============ 行情接口 ============
    
    def get_stock_price(self, symbol: str) -> Optional[Dict]:
        """
        查询股票价格
        
        Args:
            symbol: 股票代码，例如 'AAPL' 或 'US.AAPL'
            
        Returns:
            Dict: 包含价格信息的字典
                {
                    'symbol': str,
                    'last_price': float,      # 最新价
                    'open': float,            # 开盘价
                    'high': float,            # 最高价
                    'low': float,             # 最低价
                    'prev_close': float,      # 昨收价
                    'volume': int,            # 成交量
                    'turnover': float,        # 成交额
                    'bid': float,             # 买价
                    'ask': float,             # 卖价
                    'update_time': datetime   # 更新时间
                }
        """
        if not self.quote_ctx:
            self.logger.error("未连接到行情服务")
            return None
        
        try:
            # 确保股票代码格式正确
            if '.' not in symbol:
                symbol = f'US.{symbol}'
            
            # 订阅实时报价
            ret_sub, err_msg = self.quote_ctx.subscribe([symbol], ['QUOTE'], subscribe_push=False)
            if ret_sub != 0:
                self.logger.error(f"订阅失败: {err_msg}")
                return None
            
            # 获取快照
            ret, data = self.quote_ctx.get_stock_quote([symbol])
            if ret != 0:
                self.logger.error(f"获取报价失败: {data}")
                return None
            
            if data.empty:
                self.logger.warning(f"没有找到股票: {symbol}")
                return None
            
            row = data.iloc[0]
            
            result = {
                'symbol': row['code'],
                'last_price': float(row['last_price']),
                'open': float(row['open_price']),
                'high': float(row['high_price']),
                'low': float(row['low_price']),
                'prev_close': float(row['prev_close_price']),
                'volume': int(row['volume']),
                'turnover': float(row['turnover']),
                'update_time': row.get('update_time', datetime.now(ZoneInfo('America/New_York')))
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"查询股票价格失败: {e}")
            return None
    
    
    # ============ 账户接口 ============
    
    def get_account_info(self) -> Optional[Dict]:
        """
        查询账户信息
        
        Returns:
            Dict: 账户信息
                {
                    'total_assets': float,      # 总资产
                    'cash': float,              # 现金
                    'market_value': float,      # 持仓市值
                    'available_cash': float,    # 可用资金
                    'frozen_cash': float,       # 冻结资金
                    'unrealized_pnl': float,    # 未实现盈亏
                    'realized_pnl': float,      # 已实现盈亏
                    'power': float              # 购买力
                }
        """
        if not self.trade_ctx:
            self.logger.error("未连接到交易服务")
            return None
        
        try:
            # 获取账户列表
            ret, data = self.trade_ctx.get_acc_list()
            
            # print(data)
            if ret != 0:
                self.logger.error(f"获取账户列表失败: {data}")
                return None
            
            if data.empty:
                self.logger.error("没有可用账户")
                return None
            
            # 使用第一个账户（或指定的账户）
            acc_id = self.acc_id if self.acc_id else data.iloc[0]['acc_id']
            
            ret, data = self.trade_ctx.unlock_trade(self.unlock_pwd)
            # 获取资金信息

            ret, data = self.trade_ctx.accinfo_query(trd_env=self.trd_env, acc_id=self.acc_id)

            if ret != 0:
                self.logger.error(f"查询账户信息失败: {data}")
                return None
            
            if data.empty:
                return None
            
            row = data.iloc[0]
            result = {
                'total_assets': float(row['total_assets']),
                'cash': float(row['cash']),
                'market_value': float(row['market_val']),
            }
            
            self.logger.info(f"✓ 账户信息: 总资产=${result['total_assets']:,.2f}, 现金=${result['cash']:,.2f}")
            return result
            
        except Exception as e:
            self.logger.error(f"查询账户信息失败: {e}")
            return None
    
    def get_positions(self) -> Optional[List[Dict]]:
        """
        查询账户股票持仓
        
        Returns:
            List[Dict]: 持仓列表
                [
                    {
                        'symbol': str,              # 股票代码
                        'position': int,            # 持仓数量
                        'can_sell_qty': int,        # 可卖数量
                        'cost_price': float,        # 成本价
                        'market_price': float,      # 市价
                        'market_value': float,      # 市值
                        'unrealized_pnl': float,    # 未实现盈亏
                        'unrealized_pnl_ratio': float, # 盈亏比例
                        'today_buy_qty': int,       # 今日买入
                        'today_sell_qty': int       # 今日卖出
                    },
                    ...
                ]
        """
        if not self.trade_ctx:
            self.logger.error("未连接到交易服务")
            return None
        
        try:
            # 获取持仓
            ret, data = self.trade_ctx.position_list_query(
                trd_env=self.trd_env,
                acc_id=self.acc_id if self.acc_id else 0
            )
            
            if ret != 0:
                self.logger.error(f"查询持仓失败: {data}")
                return None
            
            if data.empty:
                self.logger.info("当前无持仓")
                return []
            
            positions = []
            for _, row in data.iterrows():
                pos = {
                    'symbol': row['code'],
                    'position': safe_int(row['qty']),
                    'can_sell_qty': safe_int(row['can_sell_qty']),
                    'cost_price': safe_float(row['cost_price']),
                    'market_price': safe_float(row['nominal_price']),
                    'market_value': safe_float(row['market_val']),
                    'unrealized_pnl': safe_float(row['pl_val']),
                    'unrealized_pnl_ratio': safe_float(row['pl_ratio']),
                    'today_buy_qty': safe_int(row.get('today_buy_qty', 0)),
                    'today_sell_qty': safe_int(row.get('today_sell_qty', 0))
                }
                positions.append(pos)
            
            self.logger.info(f"✓ 查询到 {len(positions)} 个持仓")
            return positions
            
        except Exception as e:
            self.logger.error(f"查询持仓失败: {e}")
            return None
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """
        查询指定股票的持仓
        
        Args:
            symbol: 股票代码
            
        Returns:
            Dict: 持仓信息，如果没有持仓返回 None
        """
        positions = self.get_positions()
        if not positions:
            return None
        
        # 确保股票代码格式一致
        if '.' not in symbol:
            symbol = f'US.{symbol}'
        
        for pos in positions:
            if pos['symbol'] == symbol:
                return pos
        
        return None
    
    # ============ 交易接口 ============
    
    def buy_stock(
        self, 
        symbol: str, 
        quantity: int, 
        price: Optional[float] = None,
        order_type: str = 'LIMIT'
    ) -> Optional[str]:
        """
        买入股票
        
        Args:
            symbol: 股票代码
            quantity: 数量
            price: 限价（如果 order_type='LIMIT'）
            order_type: 订单类型 ('LIMIT' 限价单, 'MARKET' 市价单)
            
        Returns:
            str: 订单ID，失败返回 None
        """
        if not self.trade_ctx:
            self.logger.error("未连接到交易服务")
            return None
        
        try:
            # 确保股票代码格式正确
            if '.' not in symbol:
                symbol = f'US.{symbol}'
            
            # 设置订单类型
            if order_type == 'MARKET':
                order_type_enum = OrderType.MARKET
                price = 0.0
            else:
                order_type_enum = OrderType.NORMAL
                if price is None:
                    self.logger.error("限价单必须指定价格")
                    return None
            
            # 下单
            ret, data = self.trade_ctx.place_order(
                price=price,
                qty=quantity,
                code=symbol,
                trd_side=TrdSide.BUY,
                order_type=order_type_enum,
                trd_env=self.trd_env,
                acc_id=self.acc_id if self.acc_id else 0
            )
            
            if ret != 0:
                self.logger.error(f"买入失败: {data}")
                return None
            
            order_id = str(data['order_id'].iloc[0])
            self.logger.info(
                f"✓ 买入订单已提交: {symbol} x{quantity} @ ${price:.2f}, "
                f"订单ID: {order_id}"
            )
            return order_id
            
        except Exception as e:
            self.logger.error(f"买入股票失败: {e}")
            return None
    
    def sell_stock(
        self, 
        symbol: str, 
        quantity: int, 
        price: Optional[float] = None,
        order_type: str = 'LIMIT'
    ) -> Optional[str]:
        """
        卖出股票
        
        Args:
            symbol: 股票代码
            quantity: 数量
            price: 限价（如果 order_type='LIMIT'）
            order_type: 订单类型 ('LIMIT' 限价单, 'MARKET' 市价单)
            
        Returns:
            str: 订单ID，失败返回 None
        """
        if not self.trade_ctx:
            self.logger.error("未连接到交易服务")
            return None
        
        try:
            # 确保股票代码格式正确
            if '.' not in symbol:
                symbol = f'US.{symbol}'
            
            # 设置订单类型
            if order_type == 'MARKET':
                order_type_enum = OrderType.MARKET
                price = 0.0
            else:
                order_type_enum = OrderType.NORMAL
                if price is None:
                    self.logger.error("限价单必须指定价格")
                    return None
            
            # 下单
            ret, data = self.trade_ctx.place_order(
                price=price,
                qty=quantity,
                code=symbol,
                trd_side=TrdSide.SELL,
                order_type=order_type_enum,
                trd_env=self.trd_env,
                acc_id=self.acc_id if self.acc_id else 0
            )
            
            if ret != 0:
                self.logger.error(f"卖出失败: {data}")
                return None
            
            order_id = str(data['order_id'].iloc[0])
            self.logger.info(
                f"✓ 卖出订单已提交: {symbol} x{quantity} @ ${price:.2f}, "
                f"订单ID: {order_id}"
            )
            return order_id
            
        except Exception as e:
            self.logger.error(f"卖出股票失败: {e}")
            return None
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        查询订单状态
        
        Args:
            order_id: 订单ID
            
        Returns:
            Dict: 订单信息
        """
        if not self.trade_ctx:
            self.logger.error("未连接到交易服务")
            return None
        
        try:
            ret, data = self.trade_ctx.order_list_query(
                trd_env=self.trd_env,
                acc_id=self.acc_id if self.acc_id else 0
            )
            
            if ret != 0:
                self.logger.error(f"查询订单失败: {data}")
                return None
            
            # 查找指定订单
            order_data = data[data['order_id'] == int(order_id)]
            if order_data.empty:
                self.logger.warning(f"未找到订单: {order_id}")
                return None
            
            row = order_data.iloc[0]
            return {
                'order_id': str(row['order_id']),
                'symbol': row['code'],
                'order_type': row['order_type'],
                'order_status': row['order_status'],
                'price': float(row['price']),
                'qty': int(row['qty']),
                'dealt_qty': int(row['dealt_qty']),
                'dealt_avg_price': float(row['dealt_avg_price'])
            }
            
        except Exception as e:
            self.logger.error(f"查询订单状态失败: {e}")
            return None
    
    def get_order_list(
        self, 
        status_filter: Optional[str] = None,
        symbol_filter: Optional[str] = None
    ) -> Optional[List[Dict]]:
        """
        查询订单列表
        
        Args:
            status_filter: 订单状态过滤 ('PENDING' 未成交, 'FILLED' 已成交, 'CANCELLED' 已取消)
                          None 表示查询所有订单
            symbol_filter: 股票代码过滤（如 'US.AAPL'），None 表示查询所有股票
            
        Returns:
            List[Dict]: 订单列表，每个订单包含以下字段：
                - order_id: 订单ID
                - symbol: 股票代码
                - side: 买卖方向 ('BUY'/'SELL')
                - order_type: 订单类型
                - order_status: 简化状态 ('PENDING'/'FILLED'/'CANCELLED'/'FAILED')
                - order_status_raw: 原始状态字符串 ('SUBMITTED'/'FILLED_ALL' 等)
                - qty: 订单数量
                - price: 订单价格
                - dealt_qty: 已成交数量
                - dealt_avg_price: 成交均价
                - create_time: 创建时间
                - updated_time: 更新时间
        """
        if not self.trade_ctx:
            self.logger.error("未连接到交易服务")
            return None
        
        try:
            ret, data = self.trade_ctx.order_list_query(
                trd_env=self.trd_env,
                acc_id=self.acc_id if self.acc_id else 0
            )
            
            if ret != 0:
                self.logger.error(f"查询订单列表失败: {data}")
                return None
            
            if data.empty:
                self.logger.info("当前无订单")
                return []
            
            # 状态映射（Futu API 返回的是字符串状态，不是数字）
            # 参考：https://openapi.futunn.com/futu-api-doc/trade/get-order-list.html
            status_map = {
                'PENDING': ['WAITING_SUBMIT', 'SUBMITTING', 'SUBMITTED', 'FILLED_PART'],  # 未完成
                'FILLED': ['FILLED_ALL'],            # 已成交
                'CANCELLED': ['CANCELLED_PART', 'CANCELLED_ALL'],  # 已撤单
                'FAILED': ['FAILED', 'DISABLED'],    # 失败/禁用
            }
            
            orders = []
            for _, row in data.iterrows():
                order_status_str = str(row['order_status'])  # 确保是字符串
                symbol = row['code']
                
                # 应用状态过滤
                if status_filter:
                    if status_filter not in status_map:
                        continue
                    if order_status_str not in status_map[status_filter]:
                        continue
                
                # 应用股票代码过滤
                if symbol_filter:
                    # 确保格式一致
                    _symbol_filter = symbol_filter if '.' in symbol_filter else f'US.{symbol_filter}'
                    if symbol != _symbol_filter:
                        continue
                
                # 解析买卖方向
                trd_side = row['trd_side']
                side = 'BUY' if trd_side == 1 else 'SELL'
                
                # 解析订单状态
                status_name = 'UNKNOWN'
                for name, codes in status_map.items():
                    if order_status_str in codes:
                        status_name = name
                        break
                
                orders.append({
                    'order_id': str(row['order_id']),
                    'symbol': symbol,
                    'side': side,
                    'order_type': str(row['order_type']),
                    'order_status': status_name,  # 简化状态：PENDING/FILLED/CANCELLED/FAILED
                    'order_status_raw': order_status_str,  # 原始状态：SUBMITTED/FILLED_ALL 等
                    'qty': safe_int(row['qty']),
                    'price': safe_float(row['price']),
                    'dealt_qty': safe_int(row.get('dealt_qty', 0)),
                    'dealt_avg_price': safe_float(row.get('dealt_avg_price', 0)),
                    'create_time': str(row.get('create_time', '')),
                    'updated_time': str(row.get('updated_time', ''))
                })
            
            return orders
            
        except Exception as e:
            self.logger.error(f"查询订单列表失败: {e}", exc_info=True)
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """
        撤销订单
        
        Args:
            order_id: 订单ID
            
        Returns:
            bool: 撤单是否成功
        """
        if not self.trade_ctx:
            self.logger.error("未连接到交易服务")
            return False
        
        try:
            ret, data = self.trade_ctx.modify_order(
                modify_order_op=ModifyOrderOp.CANCEL,
                order_id=int(order_id),
                qty=0,
                price=0,
                trd_env=self.trd_env,
                acc_id=self.acc_id if self.acc_id else 0
            )
            
            if ret != 0:
                self.logger.error(f"撤单失败: {data}")
                return False
            
            self.logger.info(f"✓ 订单已撤销: {order_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"撤单失败: {e}")
            return False
    
    def get_trading_days(
        self,
        start_date: str,
        end_date: str,
        market: str = 'US'
    ) -> Optional[List[str]]:
        """
        查询交易日列表
        
        Args:
            start_date: 开始日期，格式 'YYYY-MM-DD'
            end_date: 结束日期，格式 'YYYY-MM-DD'
            market: 市场 ('US', 'HK', 'CN')，默认美股
            
        Returns:
            List[str]: 交易日列表（格式 'YYYY-MM-DD'），失败返回 None
        """
        if not self.quote_ctx:
            self.logger.error("未连接到行情服务")
            return None
        
        try:
            # 设置市场
            if market == 'US':
                market_enum = Market.US
            elif market == 'HK':
                market_enum = Market.HK
            elif market == 'CN':
                market_enum = Market.SH  # A股用沪市
            else:
                self.logger.error(f"不支持的市场: {market}")
                return None
            
            # 查询交易日
            ret, data = self.quote_ctx.request_trading_days(
                market=market_enum,
                start=start_date,
                end=end_date
            )
            
            if ret != 0:
                self.logger.error(f"查询交易日失败: {data}")
                return None
            
            # 调试：记录原始数据格式
            self.logger.debug(f"交易日原始数据类型: {type(data)}, 内容: {data if isinstance(data, list) and len(str(data)) < 200 else '...'}")
            
            # 处理不同的返回类型
            if data is None:
                return []
            
            # 如果返回的是 DataFrame
            if hasattr(data, 'empty'):
                if data.empty:
                    return []
                trading_days = data['time'].tolist()
            # 如果返回的是列表
            elif isinstance(data, list):
                if not data:
                    # 空列表
                    return []
                
                # 列表元素可能是字符串或字典
                if isinstance(data[0], dict):
                    # 列表元素是字典，提取 'time' 字段
                    trading_days = [item.get('time', item) if isinstance(item, dict) else item for item in data]
                else:
                    # 列表元素是字符串
                    trading_days = data
            else:
                self.logger.error(f"未知的数据类型: {type(data)}")
                return None
            
            return trading_days
            
        except Exception as e:
            self.logger.error(f"查询交易日失败: {e}", exc_info=True)
            return None
    
    def is_trading_day(self, check_date: str, market: str = 'US') -> bool:
        """
        检查某日是否为交易日
        
        Args:
            check_date: 日期字符串，格式 'YYYY-MM-DD'
            market: 市场 ('US', 'HK', 'CN')，默认美股
            
        Returns:
            bool: 是否为交易日
        """
        # 查询当天的交易日
        trading_days = self.get_trading_days(check_date, check_date, market)
        
        if trading_days is None:
            # 查询失败，保守返回 False
            self.logger.warning(f"查询交易日失败，默认返回 False: {check_date}")
            return False
        
        return len(trading_days) > 0
    
    def count_trading_days_between(
        self,
        start_date: str,
        end_date: str,
        market: str = 'US'
    ) -> Optional[int]:
        """
        计算两个日期之间的交易日数量
        
        Args:
            start_date: 开始日期，格式 'YYYY-MM-DD'（不包含）
            end_date: 结束日期，格式 'YYYY-MM-DD'（包含）
            market: 市场 ('US', 'HK', 'CN')，默认美股
            
        Returns:
            int: 交易日数量，失败返回 None
        """
        trading_days = self.get_trading_days(start_date, end_date, market)
        
        if trading_days is None:
            return None
        
        # 不包含 start_date
        filtered_days = [d for d in trading_days if d > start_date]
        
        return len(filtered_days)
    
    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.disconnect()


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    acc_id = 16428245
    client = FutuClient(
        host='127.0.0.1',
        port=11111,
        trd_env='SIMULATE',
        trd_market='US',
        acc_id = acc_id
    )
    
  
    
    client.connect()
    
    print("\n" + "="*80)
    print("测试订单查询功能")
    print("="*80)
    
    # 查询持仓
    print("\n[1] 持仓信息:")
    positions = client.get_positions()
    if positions:
        for pos in positions:
            print(f"  {pos['symbol']}: 持仓 {pos['position']} 股, 可卖 {pos['can_sell_qty']} 股")
            if pos['position'] > 0 and pos['can_sell_qty'] == 0:
                print(f"    ⚠️  股票被锁定！")
    
    # 查询未成交订单
    print("\n[2] 未成交订单:")
    pending_orders = client.get_order_list(status_filter='PENDING')
    if pending_orders:
        print(f"  找到 {len(pending_orders)} 个未成交订单:")
        for order in pending_orders:
            print(f"  - 订单{order['order_id']}: {order['side']} {order['symbol']} "
                  f"{order['qty']} 股 @ ${order['price']:.2f} (状态: {order['order_status']})")
    else:
        print("  无未成交订单")
    
    # 查询所有订单
    print("\n[3] 所有订单:")
    all_orders = client.get_order_list()
    if all_orders:
        print(f"  找到 {len(all_orders)} 个订单:")
        for order in all_orders[:3]:  # 只显示前3个
            print(f"  - [{order['order_status']}] {order['side']} {order['symbol']}: "
                  f"{order['dealt_qty']}/{order['qty']} 股")
    else:
        print("  无订单记录")
    
    print("\n" + "="*80)
    client.disconnect()
    # # 创建客户端（模拟交易）
    # with FutuClient(
    #     host='127.0.0.1',
    #     port=11111,
    #     trd_env='SIMULATE',
    #     trd_market='US'
    # ) as client:
    #     print("\n" + "="*80)
    #     print("富途 API 测试")
    #     print("="*80)
        
    #     # 1. 查询股票价格
    #     print("\n[1] 查询股票价格")
    #     price_info = client.get_stock_price('AAPL')
    #     if price_info:
    #         print(f"AAPL 最新价: ${price_info['last_price']:.2f}")
        
    #     # 2. 查询账户信息
    #     print("\n[2] 查询账户信息")
    #     account_info = client.get_account_info()
    #     if account_info:
    #         print(f"总资产: ${account_info['total_assets']:,.2f}")
    #         print(f"现金: ${account_info['cash']:,.2f}")
    #         print(f"持仓市值: ${account_info['market_value']:,.2f}")
        
    #     # 3. 查询持仓
    #     print("\n[3] 查询持仓")
    #     positions = client.get_positions()
    #     if positions:
    #         for pos in positions:
    #             print(f"{pos['symbol']}: {pos['position']} 股, "
    #                   f"成本 ${pos['cost_price']:.2f}, "
    #                   f"盈亏 {pos['unrealized_pnl_ratio']:.2%}")
        
    #     # 4. 测试下单（注释掉，避免实际下单）
    #     # print("\n[4] 测试买入（已注释）")
    #     # order_id = client.buy_stock('AAPL', 10, 150.0)
    #     # if order_id:
    #     #     print(f"订单ID: {order_id}")
        
    #     print("\n" + "="*80)
    #     print("测试完成")
    #     print("="*80)

