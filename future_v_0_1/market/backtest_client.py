"""
Backtesting market client using Polygon.io second-level data
"""

import os
import logging
import pytz
import requests
import pandas as pd
import json
import pandas_market_calendars as mcal
from pathlib import Path
from typing import Optional, Dict, List, Set
from datetime import datetime, timedelta
from dotenv import load_dotenv


# Load .env file
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)


class BacktestMarketClient:
    """Backtesting market client using Polygon API (second-level data)"""
    
    BASE_URL = "https://api.polygon.io/v2/aggs/ticker"
    
    def __init__(self, stock_data_dir: str = None, initial_cash: float = 100000.0,
                 slippage: float = 0.0005, commission_per_share: float = 0.005, 
                 min_commission: float = 1.0):
        """
        Initialize backtesting client
        
        Args:
            stock_data_dir: Ignored (for compatibility)
            initial_cash: Initial cash amount
            slippage: Single-side slippage (default 0.05%)
            commission_per_share: Commission per share (default $0.005)
            min_commission: Minimum commission (default $1)
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Initialize Polygon API
        self.api_key = os.getenv('POLYGON_API_KEY')
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY not found in .env file")
        
        # Data cache {symbol_date: DataFrame}
        self.price_cache: Dict[str, pd.DataFrame] = {}
        self.api_calls = 0
        self.cache_hits = 0
        
        # Market calendar (NYSE)
        self.market_calendar = mcal.get_calendar('NYSE')
        
        # Trading costs
        self.slippage = slippage
        self.commission_per_share = commission_per_share
        self.min_commission = min_commission
        
        # Account info
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: Dict[str, Dict] = {}
        
        # Orders
        self.orders: List[Dict] = []
        self.order_id_counter = 1
        
        # Current time
        self.current_time: Optional[datetime] = None
        
        self.logger.info(
            f"Backtest client initialized: cash=${initial_cash:,.2f}, "
            f"slippage={slippage:.1%}, commission=${commission_per_share}/share"
        )
    
    def connect(self) -> bool:
        """Simulate connection"""
        self.logger.info("Connected (Polygon API)")
        return True
    
    def disconnect(self):
        """Simulate disconnection"""
        self.logger.info("Disconnected")
        self.logger.info(
            f"API stats: {self.api_calls} calls, "
            f"{self.cache_hits} cache hits, {len(self.price_cache)} days cached"
        )
    
    def _fetch_day_data(self, symbol: str, date_obj) -> Optional[pd.DataFrame]:
        """Fetch second-level data for a single day"""
        date_str = date_obj.isoformat() if hasattr(date_obj, 'isoformat') else str(date_obj)
        
        try:
            url = (f"{self.BASE_URL}/{symbol}/range/1/second"
                   f"/{date_str}/{date_str}"
                   f"?adjusted=true&sort=asc&limit=50000&apiKey={self.api_key}")
            
            self.api_calls += 1
            self.logger.info(f"Fetching {symbol} on {date_str} (API call #{self.api_calls})...")
            
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('resultsCount', 0) == 0:
                self.logger.warning(f"No data for {symbol} on {date_str} (possibly weekend/holiday)")
                return None
            
            results = data.get('results', [])
            records = []
            et_tz = pytz.timezone('America/New_York')
            
            for item in results:
                timestamp = datetime.fromtimestamp(item['t'] / 1000, tz=pytz.UTC)
                timestamp = timestamp.astimezone(et_tz)
                
                records.append({
                    'datetime': timestamp,
                    'close': item['c'],
                })
            
            df = pd.DataFrame(records)
            df.set_index('datetime', inplace=True)
            
            self.logger.debug(f"Fetched {symbol} on {date_str}: {len(df)} records")
            return df
            
        except Exception as e:
            self.logger.warning(f"Failed to fetch {symbol} on {date_str}: {e}")
            return None
    
    def get_price_at_time(self, symbol: str, target_time: datetime) -> Optional[float]:
        """Get close price at specific time (forward-fill if no exact match)"""
        et_tz = pytz.timezone('America/New_York')
        
        # Convert to ET timezone
        if target_time.tzinfo is not None:
            target_time = target_time.astimezone(et_tz)
        else:
            target_time = et_tz.localize(target_time)
        
        cache_key = f"{symbol}_{target_time.date().isoformat()}"
        
        if cache_key not in self.price_cache:
            df = self._fetch_day_data(symbol, target_time.date())
            if df is not None:
                self.price_cache[cache_key] = df
            else:
                return None
        else:
            self.cache_hits += 1
        
        df = self.price_cache[cache_key]
        
        try:
            # Find closest time <= target_time (use tz-aware comparison)
            idx = df.index.get_indexer([target_time], method='pad')
            if idx[0] >= 0:
                return float(df.iloc[idx[0]]['close'])
        except Exception as e:
            self.logger.debug(f"Error getting price for {symbol}: {e}")
        
        return None
    
    def set_current_time(self, current_time: datetime):
        """Set current time for backtest progress"""
        self.current_time = current_time
        
        # Update market price for all positions
        for symbol in list(self.positions.keys()):
            if self.positions[symbol]['position'] > 0:
                price = self.get_price_at_time(symbol, current_time)
                if price:
                    self.positions[symbol]['market_price'] = price
                    self.positions[symbol]['market_value'] = price * self.positions[symbol]['position']
                    
                    if 'highest_price' not in self.positions[symbol]:
                        self.positions[symbol]['highest_price'] = self.positions[symbol]['cost_price']
                    if price > self.positions[symbol]['highest_price']:
                        self.positions[symbol]['highest_price'] = price
    
    def _load_stock_price_data(self, symbol: str):
        """Preload stock data (no-op, kept for compatibility)"""
        pass
    
    def get_stock_price(self, symbol: str) -> Optional[Dict]:
        """Get current stock price at current_time"""
        if not self.current_time:
            return None
        
        price = self.get_price_at_time(symbol, self.current_time)
        if price:
            return {
                'last_price': price,
                'bid': price * 0.999,
                'ask': price * 1.001,
            }
        
        return None
    
    def get_account_info(self) -> Optional[Dict]:
        """Get account info"""
        position_value = sum(pos['market_value'] for pos in self.positions.values())
        total_assets = self.cash + position_value
        
        return {
            'cash': self.cash,
            'market_value': position_value,
            'total_assets': total_assets,
            'available_cash': self.cash,
            'power': self.cash,
        }
    
    def get_positions(self) -> List[Dict]:
        """Get position list"""
        positions = []
        for symbol, pos in self.positions.items():
            if pos['position'] > 0:
                positions.append({
                    'symbol': symbol,
                    'position': pos['position'],
                    'can_sell_qty': pos['position'],
                    'cost_price': pos['cost_price'],
                    'market_price': pos['market_price'],
                    'market_value': pos['market_value'],
                    'pnl': (pos['market_price'] - pos['cost_price']) * pos['position'],
                    'pnl_ratio': (pos['market_price'] - pos['cost_price']) / pos['cost_price'] 
                                if pos['cost_price'] > 0 else 0,
                })
        return positions
    
    def buy_stock(self, symbol: str, quantity: int, price: float, 
                  order_type: str = 'LIMIT') -> Optional[Dict]:
        """Buy stock (with slippage and commission)"""
        actual_price = price * (1 + self.slippage)
        commission = max(quantity * self.commission_per_share, self.min_commission)
        cost = actual_price * quantity + commission
        
        acc_info = self.get_account_info()
        total_assets = acc_info['total_assets']
        cash_after = self.cash - cost
        cash_ratio_after = cash_after / total_assets
        
        if cash_ratio_after < -1.0:
            self.logger.warning(
                f"Buy failed: insufficient cash {symbol}, "
                f"need ${cost:,.2f}, cash ratio {cash_ratio_after:.1%} < -100%"
            )
            return None
        
        self.cash -= cost
        
        if symbol in self.positions:
            old_pos = self.positions[symbol]
            old_shares = old_pos['position']
            old_cost = old_pos['cost_price']
            
            new_shares = old_shares + quantity
            new_cost = (old_cost * old_shares + actual_price * quantity) / new_shares
            
            self.positions[symbol] = {
                'position': new_shares,
                'cost_price': new_cost,
                'market_price': actual_price,
                'market_value': actual_price * new_shares,
            }
        else:
            self.positions[symbol] = {
                'position': quantity,
                'cost_price': actual_price,
                'market_price': actual_price,
                'market_value': actual_price * quantity,
                'highest_price': actual_price,
            }
        
        order_id = f"BUY_{self.order_id_counter:06d}"
        self.order_id_counter += 1
        
        et_tz = pytz.timezone('America/New_York')
        order = {
            'order_id': order_id,
            'symbol': symbol,
            'side': 'BUY',
            'quantity': quantity,
            'price': actual_price,
            'base_price': price,
            'commission': commission,
            'cost': cost,
            'status': 'FILLED',
            'time': self.current_time if self.current_time else datetime.now(et_tz),
        }
        self.orders.append(order)
        
        self.logger.info(
            f"Buy: {symbol} {quantity}@${actual_price:.2f} cost=${cost:,.2f}"
        )
        
        return order
    
    def sell_stock(self, symbol: str, quantity: int, price: float,
                   order_type: str = 'LIMIT') -> Optional[Dict]:
        """Sell stock (with slippage and commission)"""
        if symbol not in self.positions or self.positions[symbol]['position'] < quantity:
            self.logger.warning(f"Sell failed: insufficient position {symbol}")
            return None
        
        actual_price = price * (1 - self.slippage)
        commission = max(quantity * self.commission_per_share, self.min_commission)
        proceeds = actual_price * quantity - commission
        
        self.cash += proceeds
        
        pos = self.positions[symbol]
        cost_price = pos['cost_price']
        
        pos['position'] -= quantity
        pos['market_value'] = pos['market_price'] * pos['position']
        
        if pos['position'] == 0:
            del self.positions[symbol]
        
        order_id = f"SELL_{self.order_id_counter:06d}"
        self.order_id_counter += 1
        
        pnl = (actual_price - cost_price) * quantity - commission
        pnl_ratio = pnl / (cost_price * quantity) if cost_price > 0 else 0
        
        et_tz = pytz.timezone('America/New_York')
        order = {
            'order_id': order_id,
            'symbol': symbol,
            'side': 'SELL',
            'quantity': quantity,
            'price': actual_price,
            'base_price': price,
            'commission': commission,
            'proceeds': proceeds,
            'status': 'FILLED',
            'time': self.current_time if self.current_time else datetime.now(et_tz),
            'pnl': pnl,
            'pnl_ratio': pnl_ratio,
        }
        self.orders.append(order)
        
        self.logger.info(
            f"Sell: {symbol} {quantity}@${actual_price:.2f} pnl=${pnl:+,.2f}"
        )
        
        return order
    
    def get_order_list(self, status_filter: str = None, symbol_filter: str = None) -> List[Dict]:
        """Get order list"""
        orders = self.orders
        
        if status_filter:
            orders = [o for o in orders if o['status'] == status_filter]
        
        if symbol_filter:
            orders = [o for o in orders if o['symbol'] == symbol_filter]
        
        return orders
    
    def count_trading_days_between(self, start_date: str, end_date: str, market: str = 'US') -> Optional[int]:
        """Count trading days between dates using NYSE calendar"""
        try:
            # Get valid trading days from NYSE calendar
            schedule = self.market_calendar.valid_days(
                start_date=start_date,
                end_date=end_date
            )
            
            # Count days (excluding start_date if needed, matching original behavior)
            trading_days = len([d for d in schedule if d.strftime('%Y-%m-%d') > start_date])
            
            return trading_days
            
        except Exception as e:
            self.logger.warning(f"Failed to get trading days from calendar: {e}")
            # Fallback: simple weekday counting
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            trading_days = 0
            current = start + timedelta(days=1)
            while current <= end:
                if current.weekday() < 5:
                    trading_days += 1
                current += timedelta(days=1)
            
            return trading_days
    
    def get_summary(self) -> Dict:
        """Get account summary"""
        acc_info = self.get_account_info()
        
        total_pnl = acc_info['total_assets'] - self.initial_cash
        total_pnl_ratio = total_pnl / self.initial_cash
        
        buy_orders = [o for o in self.orders if o['side'] == 'BUY']
        sell_orders = [o for o in self.orders if o['side'] == 'SELL']
        
        realized_pnl = sum(o.get('pnl', 0) for o in sell_orders)
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

