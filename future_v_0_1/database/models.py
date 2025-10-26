"""
数据库模型定义
使用 SQLite 存储交易系统的核心数据
"""

import sqlite3
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from zoneinfo import ZoneInfo


class DatabaseManager:
    """
    数据库管理器
    负责所有数据的持久化和查询
    """
    
    def __init__(self, db_path: str):
        """
        初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # 确保数据库目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
        self._init_database()
        
        self.logger.info(f"数据库初始化完成: {db_path}")
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接（上下文管理器）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # 使用 Row 对象，可以通过列名访问
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            conn.close()
    
    def _init_database(self):
        """初始化数据库表结构"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # ============ P0: 核心业务数据 ============
            
            # 1. 订单表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE NOT NULL,           -- 订单ID（client_id）
                    symbol TEXT NOT NULL,                     -- 股票代码
                    order_type TEXT NOT NULL,                 -- BUY/SELL
                    order_time TEXT NOT NULL,                 -- 订单时间（ISO格式）
                    shares INTEGER NOT NULL,                  -- 数量
                    price REAL,                               -- 价格
                    status TEXT NOT NULL DEFAULT 'PENDING',   -- PENDING/FILLED/REJECTED/CANCELLED
                    
                    -- 关联信息
                    related_order_id TEXT,                    -- 关联订单ID（卖出订单关联买入订单）
                    signal_id TEXT,                           -- 触发信号ID
                    
                    -- 策略信息
                    pos_ratio REAL,                           -- 仓位比例
                    reason TEXT,                              -- 原因（止盈/止损/持仓天数）
                    meta TEXT,                                -- 元数据（JSON）
                    
                    -- 成交信息
                    filled_time TEXT,                         -- 成交时间
                    filled_price REAL,                        -- 成交价格
                    filled_shares INTEGER,                    -- 成交数量
                    
                    -- 盈亏（仅卖出订单）
                    pnl_amount REAL,                          -- 盈亏金额
                    pnl_ratio REAL,                           -- 盈亏比例
                    
                    created_at TEXT NOT NULL,                 -- 创建时间
                    updated_at TEXT NOT NULL                  -- 更新时间
                )
            ''')
            
            # 2. 持仓表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT UNIQUE NOT NULL,              -- 股票代码
                    shares INTEGER NOT NULL,                  -- 持仓数量
                    
                    -- 开仓信息
                    entry_time TEXT NOT NULL,                 -- 开仓时间
                    entry_price REAL NOT NULL,                -- 开仓均价
                    entry_order_id TEXT NOT NULL,             -- 开仓订单ID
                    
                    -- 当前状态
                    current_price REAL,                       -- 当前价格
                    market_value REAL,                        -- 市值
                    unrealized_pnl REAL,                      -- 未实现盈亏
                    unrealized_pnl_ratio REAL,                -- 未实现盈亏比例
                    highest_price REAL,                       -- 持仓以来最高价
                    
                    -- 策略信息
                    signal_id TEXT,                           -- 关联信号ID
                    target_profit_price REAL,                 -- 目标止盈价
                    stop_loss_price REAL,                     -- 止损价
                    target_exit_date TEXT,                    -- 目标卖出日期
                    
                    -- 状态
                    status TEXT NOT NULL DEFAULT 'OPEN',      -- OPEN/CLOSED
                    
                    created_at TEXT NOT NULL,                 -- 创建时间
                    updated_at TEXT NOT NULL,                 -- 更新时间
                    closed_at TEXT                            -- 平仓时间
                )
            ''')
            
            # 3. 已处理文件表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processed_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT UNIQUE NOT NULL,           -- 文件路径
                    processed_time TEXT NOT NULL,             -- 处理时间
                    records_count INTEGER NOT NULL DEFAULT 0, -- 记录数
                    new_signals_count INTEGER NOT NULL DEFAULT 0, -- 新信号数
                    file_hash TEXT,                           -- 文件哈希（MD5）
                    created_at TEXT NOT NULL                  -- 创建时间
                )
            ''')
            
            # ============ P1: 重要数据 ============
            
            # 4. 策略状态表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trading_date TEXT UNIQUE NOT NULL,        -- 交易日期
                    strategy_name TEXT NOT NULL,              -- 策略名称
                    
                    -- 状态数据
                    daily_trade_count INTEGER NOT NULL DEFAULT 0,  -- 今日交易次数
                    daily_position_ratio REAL NOT NULL DEFAULT 0,  -- 今日累计仓位
                    blacklist TEXT,                           -- 黑名单（JSON）
                    
                    -- 统计
                    signals_received INTEGER NOT NULL DEFAULT 0,   -- 收到信号数
                    signals_filtered INTEGER NOT NULL DEFAULT 0,   -- 过滤信号数
                    orders_placed INTEGER NOT NULL DEFAULT 0,      -- 下单数
                    
                    created_at TEXT NOT NULL,                 -- 创建时间
                    updated_at TEXT NOT NULL                  -- 更新时间
                )
            ''')
            
            # 5. 期权信号表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS option_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT UNIQUE NOT NULL,           -- 信号ID（唯一）
                    
                    -- 期权数据
                    symbol TEXT NOT NULL,                     -- 股票代码
                    option_type TEXT NOT NULL,                -- CALL/PUT
                    contract TEXT NOT NULL,                   -- 合约代码
                    side TEXT NOT NULL,                       -- BUY/SELL
                    premium REAL NOT NULL,                    -- 权利金
                    stock_price REAL,                         -- 股票价格（期权数据中的）
                    signal_time TEXT NOT NULL,                -- 信号时间
                    
                    -- 处理状态
                    processed BOOLEAN NOT NULL DEFAULT 0,     -- 是否已处理
                    generated_order BOOLEAN NOT NULL DEFAULT 0, -- 是否生成订单
                    order_id TEXT,                            -- 关联订单ID
                    
                    -- 过滤原因
                    filter_reason TEXT,                       -- 过滤原因
                    
                    -- 元数据
                    meta TEXT,                                -- 完整期权数据（JSON）
                    
                    created_at TEXT NOT NULL                  -- 创建时间
                )
            ''')
            
            # 6. 对账结果表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reconciliation_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trading_date TEXT NOT NULL,               -- 交易日期 (YYYY-MM-DD)
                    reconciliation_time TEXT NOT NULL,        -- 对账时间（ISO格式）
                    
                    -- 对账结果
                    passed BOOLEAN NOT NULL,                  -- 对账是否通过
                    
                    -- 详细检查结果（JSON格式）
                    position_check TEXT,                      -- 持仓检查结果
                    order_check TEXT,                         -- 订单检查结果
                    account_check TEXT,                       -- 账户检查结果
                    daily_stats TEXT,                         -- 每日统计
                    
                    -- 问题汇总
                    issues_count INTEGER NOT NULL DEFAULT 0,  -- 发现问题数量
                    issues_summary TEXT,                      -- 问题摘要（JSON列表）
                    
                    -- 自动修复
                    auto_fix_applied BOOLEAN NOT NULL DEFAULT 0,  -- 是否应用了自动修复
                    fix_actions TEXT,                         -- 修复操作记录（JSON列表）
                    
                    created_at TEXT NOT NULL                  -- 创建时间
                )
            ''')
            
            # 为对账结果表创建索引
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_reconciliation_date 
                ON reconciliation_results(trading_date)
            ''')
            
            # ============ 索引 ============
            
            # 订单表索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_type ON orders(order_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_time ON orders(order_time)')
            
            # 持仓表索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)')
            
            # 信号表索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_symbol ON option_signals(symbol)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_processed ON option_signals(processed)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_time ON option_signals(signal_time)')
            
            self.logger.info("数据库表结构创建完成")
    
    # ============ 订单相关方法 ============
    
    def save_order(self, order_data: Dict[str, Any]) -> int:
        """
        保存订单
        
        Args:
            order_data: 订单数据字典
            
        Returns:
            int: 订单记录ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now(ZoneInfo('America/New_York')).isoformat()
            
            cursor.execute('''
                INSERT INTO orders (
                    order_id, symbol, order_type, order_time, shares, price,
                    status, related_order_id, signal_id, pos_ratio, reason, meta,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                order_data['order_id'],
                order_data['symbol'],
                order_data['order_type'],
                order_data['order_time'],
                order_data['shares'],
                order_data.get('price'),
                order_data.get('status', 'PENDING'),
                order_data.get('related_order_id'),
                order_data.get('signal_id'),
                order_data.get('pos_ratio'),
                order_data.get('reason'),
                json.dumps(order_data.get('meta', {})),
                now, now
            ))
            
            order_id = cursor.lastrowid
            self.logger.info(f"订单已保存: {order_data['order_id']} ({order_data['order_type']})")
            
            return order_id
    
    def update_order_status(
        self, 
        order_id: str, 
        status: str,
        filled_time: Optional[str] = None,
        filled_price: Optional[float] = None,
        filled_shares: Optional[int] = None
    ):
        """更新订单状态"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE orders 
                SET status = ?, filled_time = ?, filled_price = ?, filled_shares = ?,
                    updated_at = ?
                WHERE order_id = ?
            ''', (
                status,
                filled_time,
                filled_price,
                filled_shares,
                datetime.now(ZoneInfo('America/New_York')).isoformat(),
                order_id
            ))
            
            self.logger.info(f"订单状态已更新: {order_id} -> {status}")
    
    def update_order_pnl(self, order_id: str, pnl_amount: float, pnl_ratio: float):
        """更新订单盈亏"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE orders 
                SET pnl_amount = ?, pnl_ratio = ?, updated_at = ?
                WHERE order_id = ?
            ''', (
                pnl_amount,
                pnl_ratio,
                datetime.now(ZoneInfo('America/New_York')).isoformat(),
                order_id
            ))
    
    def get_order(self, order_id: str) -> Optional[Dict]:
        """根据订单ID查询订单"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM orders WHERE order_id = ?', (order_id,))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
    
    def get_orders_by_symbol(self, symbol: str, order_type: Optional[str] = None) -> List[Dict]:
        """查询指定股票的订单"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            if order_type:
                cursor.execute(
                    'SELECT * FROM orders WHERE symbol = ? AND order_type = ? ORDER BY order_time DESC',
                    (symbol, order_type)
                )
            else:
                cursor.execute(
                    'SELECT * FROM orders WHERE symbol = ? ORDER BY order_time DESC',
                    (symbol,)
                )
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_orders_by_date(self, trading_date: str) -> List[Dict]:
        """
        查询指定日期的所有订单
        
        Args:
            trading_date: 交易日期 (YYYY-MM-DD)
            
        Returns:
            List[Dict]: 订单列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 查询当日的订单（order_time 以该日期开头）
            cursor.execute('''
                SELECT * FROM orders
                WHERE DATE(order_time) = ?
                ORDER BY order_time DESC
            ''', (trading_date,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_bought_symbols_last_n_days(self, days: int = 15) -> List[Dict]:
        """
        查询过去N天内所有买入的股票（用于恢复黑名单）
        
        黑名单用途：记录过去N个交易日买入过的股票，避免短期内重复交易同一标的
        
        Args:
            days: 天数（默认15天）
                  注意：目前使用自然日，包含周末和节假日，比交易日更保守
                  如需严格按交易日计算，需结合 Futu API 的交易日查询
            
        Returns:
            List[Dict]: 买入记录列表，每个包含 symbol, latest_order_time
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 查询过去N天内所有买入订单（已提交或已成交）
            # 使用 MAX 获取每个股票最后一次买入时间
            cursor.execute('''
                SELECT DISTINCT symbol, MAX(order_time) as latest_order_time
                FROM orders
                WHERE order_type = 'BUY'
                  AND status IN ('PENDING', 'FILLED')
                  AND order_time >= datetime('now', '-' || ? || ' days')
                GROUP BY symbol
                ORDER BY latest_order_time DESC
            ''', (days,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    # ============ 持仓相关方法 ============
    
    def save_position(self, position_data: Dict[str, Any]) -> int:
        """
        保存持仓
        
        Args:
            position_data: 持仓数据字典
            
        Returns:
            int: 持仓记录ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now(ZoneInfo('America/New_York')).isoformat()
            
            cursor.execute('''
                INSERT OR REPLACE INTO positions (
                    symbol, shares, entry_time, entry_price, entry_order_id,
                    current_price, market_value, unrealized_pnl, unrealized_pnl_ratio,
                    highest_price, signal_id, target_profit_price, stop_loss_price, target_exit_date,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                position_data['symbol'],
                position_data['shares'],
                position_data['entry_time'],
                position_data['entry_price'],
                position_data['entry_order_id'],
                position_data.get('current_price'),
                position_data.get('market_value'),
                position_data.get('unrealized_pnl'),
                position_data.get('unrealized_pnl_ratio'),
                position_data.get('highest_price'),
                position_data.get('signal_id'),
                position_data.get('target_profit_price'),
                position_data.get('stop_loss_price'),
                position_data.get('target_exit_date'),
                position_data.get('status', 'OPEN'),
                now, now
            ))
            
            position_id = cursor.lastrowid
            self.logger.info(f"持仓已保存: {position_data['symbol']} {position_data['shares']} 股")
            
            return position_id
    
    def update_position(self, symbol: str, update_data: Dict[str, Any]):
        """更新持仓信息"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 动态构建 UPDATE 语句
            set_clause = ', '.join([f'{k} = ?' for k in update_data.keys()])
            set_clause += ', updated_at = ?'
            
            values = list(update_data.values())
            values.append(datetime.now(ZoneInfo('America/New_York')).isoformat())
            values.append(symbol)
            
            cursor.execute(
                f'UPDATE positions SET {set_clause} WHERE symbol = ?',
                values
            )
            
            self.logger.info(f"持仓已更新: {symbol}")
    
    def close_position(self, symbol: str):
        """平仓"""
        self.update_position(symbol, {
            'status': 'CLOSED',
            'closed_at': datetime.now(ZoneInfo('America/New_York')).isoformat()
        })
    
    def update_position_highest_price(self, symbol: str, current_price: float):
        """
        更新持仓的最高价
        
        Args:
            symbol: 股票代码
            current_price: 当前实时价格
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 获取现有最高价
            cursor.execute('SELECT highest_price FROM positions WHERE symbol = ? AND status = "OPEN"', (symbol,))
            row = cursor.fetchone()
            
            if row:
                existing_highest = row['highest_price'] if row['highest_price'] else 0
                new_highest = max(existing_highest, current_price)
                
                # 只在最高价有变化时更新
                if new_highest > existing_highest:
                    cursor.execute(
                        'UPDATE positions SET highest_price = ?, updated_at = ? WHERE symbol = ?',
                        (new_highest, datetime.now(ZoneInfo('America/New_York')).isoformat(), symbol)
                    )
                    self.logger.debug(f"更新 {symbol} 最高价: ${new_highest:.2f}")
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """查询持仓"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM positions WHERE symbol = ? AND status = "OPEN"', (symbol,))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
    
    def get_all_open_positions(self) -> List[Dict]:
        """获取所有开仓持仓"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM positions WHERE status = "OPEN" ORDER BY entry_time')
            return [dict(row) for row in cursor.fetchall()]
    
    # ============ 文件处理记录方法 ============
    
    def save_processed_file(
        self, 
        file_path: str, 
        records_count: int = 0,
        new_signals_count: int = 0,
        file_hash: Optional[str] = None
    ) -> int:
        """保存已处理文件记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now(ZoneInfo('America/New_York')).isoformat()
            
            cursor.execute('''
                INSERT OR REPLACE INTO processed_files (
                    file_path, processed_time, records_count, new_signals_count, 
                    file_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (file_path, now, records_count, new_signals_count, file_hash, now))
            
            return cursor.lastrowid
    
    def is_file_processed(self, file_path: str) -> bool:
        """检查文件是否已处理"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM processed_files WHERE file_path = ?', (file_path,))
            count = cursor.fetchone()[0]
            return count > 0
    
    def get_processed_files(self) -> List[str]:
        """获取所有已处理文件路径"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT file_path FROM processed_files ORDER BY processed_time')
            return [row[0] for row in cursor.fetchall()]
    
    # ============ 策略状态方法 ============
    
    def save_strategy_state(self, trading_date: str, state_data: Dict[str, Any]) -> int:
        """保存策略状态"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now(ZoneInfo('America/New_York')).isoformat()
            
            cursor.execute('''
                INSERT OR REPLACE INTO strategy_state (
                    trading_date, strategy_name, daily_trade_count, daily_position_ratio,
                    blacklist, signals_received, signals_filtered, orders_placed,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trading_date,
                state_data.get('strategy_name', 'StrategyV6'),
                state_data.get('daily_trade_count', 0),
                state_data.get('daily_position_ratio', 0.0),
                json.dumps(state_data.get('blacklist', {})),
                state_data.get('signals_received', 0),
                state_data.get('signals_filtered', 0),
                state_data.get('orders_placed', 0),
                now, now
            ))
            
            return cursor.lastrowid
    
    def get_strategy_state(self, trading_date: str) -> Optional[Dict]:
        """获取策略状态"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM strategy_state WHERE trading_date = ?',
                (trading_date,)
            )
            row = cursor.fetchone()
            
            if row:
                data = dict(row)
                # 解析 JSON 字段
                if data.get('blacklist'):
                    data['blacklist'] = json.loads(data['blacklist'])
                return data
            return None
    
    def update_strategy_state(self, trading_date: str, update_data: Dict[str, Any]):
        """更新策略状态"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 特殊处理 blacklist（转为 JSON）
            if 'blacklist' in update_data:
                update_data['blacklist'] = json.dumps(update_data['blacklist'])
            
            set_clause = ', '.join([f'{k} = ?' for k in update_data.keys()])
            set_clause += ', updated_at = ?'
            
            values = list(update_data.values())
            values.append(datetime.now(ZoneInfo('America/New_York')).isoformat())
            values.append(trading_date)
            
            cursor.execute(
                f'UPDATE strategy_state SET {set_clause} WHERE trading_date = ?',
                values
            )
    
    # ============ 期权信号方法 ============
    
    def save_signal(self, signal_data: Dict[str, Any]) -> int:
        """保存期权信号"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now(ZoneInfo('America/New_York')).isoformat()
            
            cursor.execute('''
                INSERT OR IGNORE INTO option_signals (
                    signal_id, symbol, option_type, contract, side, premium, stock_price, signal_time,
                    processed, generated_order, order_id, filter_reason, meta, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal_data['signal_id'],
                signal_data['symbol'],
                signal_data['option_type'],
                signal_data['contract'],
                signal_data['side'],
                signal_data['premium'],
                signal_data.get('stock_price'),  # 添加股票价格
                signal_data['signal_time'],
                signal_data.get('processed', False),
                signal_data.get('generated_order', False),
                signal_data.get('order_id'),
                signal_data.get('filter_reason'),
                json.dumps(signal_data.get('meta', {})),
                now
            ))
            
            return cursor.lastrowid
    
    def update_signal_processed(
        self, 
        signal_id: str, 
        generated_order: bool,
        order_id: Optional[str] = None,
        filter_reason: Optional[str] = None
    ):
        """更新信号处理状态"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE option_signals 
                SET processed = 1, generated_order = ?, order_id = ?, filter_reason = ?
                WHERE signal_id = ?
            ''', (generated_order, order_id, filter_reason, signal_id))
    
    def is_signal_processed(self, signal_id: str) -> bool:
        """检查信号是否已处理"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT processed FROM option_signals WHERE signal_id = ?',
                (signal_id,)
            )
            row = cursor.fetchone()
            return row[0] == 1 if row else False
    
    # ============ 统计查询方法 ============
    
    def get_daily_stats(self, trading_date: Optional[str] = None) -> Dict:
        """获取每日统计"""
        if not trading_date:
            trading_date = datetime.now(ZoneInfo('America/New_York')).date().isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            # 今日订单数
            cursor.execute('''
                SELECT COUNT(*) FROM orders 
                WHERE DATE(order_time) = ? AND order_type = 'BUY'
            ''', (trading_date,))
            stats['buy_orders'] = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM orders 
                WHERE DATE(order_time) = ? AND order_type = 'SELL'
            ''', (trading_date,))
            stats['sell_orders'] = cursor.fetchone()[0]
            
            # 今日盈亏
            cursor.execute('''
                SELECT SUM(pnl_amount), AVG(pnl_ratio) FROM orders
                WHERE DATE(filled_time) = ? AND order_type = 'SELL' AND status = 'FILLED'
            ''', (trading_date,))
            row = cursor.fetchone()
            stats['total_pnl'] = row[0] or 0
            stats['avg_pnl_ratio'] = row[1] or 0
            
            # 开仓持仓数
            cursor.execute('SELECT COUNT(*) FROM positions WHERE status = "OPEN"')
            stats['open_positions'] = cursor.fetchone()[0]
            
            return stats
    
    # ============ 对账结果管理 ============
    
    def save_reconciliation_result(self, result_data: Dict[str, Any]) -> int:
        """
        保存对账结果
        
        Args:
            result_data: 对账结果数据，包含：
                - trading_date: 交易日期
                - reconciliation_time: 对账时间
                - passed: 是否通过
                - position_check: 持仓检查结果（dict）
                - order_check: 订单检查结果（dict）
                - account_check: 账户检查结果（dict）
                - daily_stats: 每日统计（dict）
                - issues_summary: 问题摘要（list）
                - fix_actions: 修复操作记录（list）
        
        Returns:
            int: 插入的记录ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now(ZoneInfo('America/New_York')).isoformat()
            
            # 计算问题数量
            issues = result_data.get('issues_summary', [])
            issues_count = len(issues) if issues else 0
            
            # 判断是否应用了自动修复
            fix_actions = result_data.get('fix_actions', [])
            auto_fix_applied = len(fix_actions) > 0 if fix_actions else False
            
            cursor.execute('''
                INSERT INTO reconciliation_results (
                    trading_date, reconciliation_time, passed,
                    position_check, order_check, account_check, daily_stats,
                    issues_count, issues_summary,
                    auto_fix_applied, fix_actions,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                result_data['trading_date'],
                result_data.get('reconciliation_time', now),
                result_data['passed'],
                json.dumps(result_data.get('position_check', {})),
                json.dumps(result_data.get('order_check', {})),
                json.dumps(result_data.get('account_check', {})),
                json.dumps(result_data.get('daily_stats', {})),
                issues_count,
                json.dumps(issues),
                auto_fix_applied,
                json.dumps(fix_actions),
                now
            ))
            
            record_id = cursor.lastrowid
            self.logger.info(f"对账结果已保存: {result_data['trading_date']} [ID: {record_id}]")
            return record_id
    
    def get_reconciliation_result(self, trading_date: str) -> Optional[Dict]:
        """
        获取指定日期的对账结果
        
        Args:
            trading_date: 交易日期 (YYYY-MM-DD)
            
        Returns:
            Dict: 对账结果，如果不存在返回 None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM reconciliation_results WHERE trading_date = ? ORDER BY id DESC LIMIT 1',
                (trading_date,)
            )
            row = cursor.fetchone()
            
            if row:
                data = dict(row)
                # 解析 JSON 字段
                for field in ['position_check', 'order_check', 'account_check', 'daily_stats', 'issues_summary', 'fix_actions']:
                    if data.get(field):
                        try:
                            data[field] = json.loads(data[field])
                        except json.JSONDecodeError:
                            data[field] = {}
                return data
            return None
    
    def get_reconciliation_history(self, days: int = 30) -> List[Dict]:
        """
        获取对账历史记录
        
        Args:
            days: 查询最近多少天的记录
            
        Returns:
            List[Dict]: 对账记录列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 计算起始日期
            et_now = datetime.now(ZoneInfo('America/New_York'))
            start_date = (et_now - timedelta(days=days)).date().isoformat()
            
            cursor.execute('''
                SELECT 
                    id, trading_date, reconciliation_time, passed,
                    issues_count, auto_fix_applied, created_at
                FROM reconciliation_results
                WHERE trading_date >= ?
                ORDER BY trading_date DESC, id DESC
            ''', (start_date,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_reconciliation_summary(self, days: int = 30) -> Dict:
        """
        获取对账汇总统计
        
        Args:
            days: 统计最近多少天
            
        Returns:
            Dict: 统计结果
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            et_now = datetime.now(ZoneInfo('America/New_York'))
            start_date = (et_now - timedelta(days=days)).date().isoformat()
            
            summary = {}
            
            # 总对账次数
            cursor.execute('''
                SELECT COUNT(*) FROM reconciliation_results
                WHERE trading_date >= ?
            ''', (start_date,))
            summary['total_reconciliations'] = cursor.fetchone()[0]
            
            # 通过/未通过次数
            cursor.execute('''
                SELECT passed, COUNT(*) FROM reconciliation_results
                WHERE trading_date >= ?
                GROUP BY passed
            ''', (start_date,))
            pass_stats = {row[0]: row[1] for row in cursor.fetchall()}
            summary['passed_count'] = pass_stats.get(1, 0)
            summary['failed_count'] = pass_stats.get(0, 0)
            
            # 发现问题总数
            cursor.execute('''
                SELECT SUM(issues_count) FROM reconciliation_results
                WHERE trading_date >= ?
            ''', (start_date,))
            summary['total_issues'] = cursor.fetchone()[0] or 0
            
            # 自动修复次数
            cursor.execute('''
                SELECT COUNT(*) FROM reconciliation_results
                WHERE trading_date >= ? AND auto_fix_applied = 1
            ''', (start_date,))
            summary['auto_fix_count'] = cursor.fetchone()[0]
            
            return summary
    
    # ============ 期权信号管理 ============
    
    def save_option_signal(
        self,
        signal_id: str,
        symbol: str,
        option_type: str,
        contract: str,
        side: str,
        premium: float,
        stock_price: Optional[float],
        signal_time: str,
        meta: Optional[Dict] = None
    ):
        """
        保存期权信号
        
        Args:
            signal_id: 信号ID（唯一）
            symbol: 股票代码
            option_type: 期权类型 (CALL/PUT)
            contract: 合约代码
            side: 方向 (BUY/SELL)
            premium: 权利金
            stock_price: 股票价格（期权数据中的）
            signal_time: 信号时间（ISO格式）
            meta: 元数据（可选）
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            now = datetime.now(ZoneInfo('America/New_York')).isoformat()
            meta_json = json.dumps(meta) if meta else None
            
            cursor.execute('''
                INSERT OR REPLACE INTO option_signals (
                    signal_id, symbol, option_type, contract, side,
                    premium, stock_price, signal_time, meta, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal_id, symbol, option_type, contract, side,
                premium, stock_price, signal_time, meta_json, now
            ))
            
            self.logger.debug(
                f"保存期权信号: {symbol} {option_type} "
                f"权利金${premium:,.0f} 股价${stock_price:.2f if stock_price else 0}"
            )
    
    def update_option_signal_status(
        self,
        signal_id: str,
        processed: bool = True,
        generated_order: bool = False,
        order_id: Optional[str] = None,
        filter_reason: Optional[str] = None
    ):
        """
        更新期权信号处理状态
        
        Args:
            signal_id: 信号ID
            processed: 是否已处理
            generated_order: 是否生成订单
            order_id: 关联订单ID（可选）
            filter_reason: 过滤原因（可选）
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE option_signals
                SET processed = ?,
                    generated_order = ?,
                    order_id = ?,
                    filter_reason = ?
                WHERE signal_id = ?
            ''', (
                1 if processed else 0,
                1 if generated_order else 0,
                order_id,
                filter_reason,
                signal_id
            ))
    
    def get_option_signals(
        self,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        processed: Optional[bool] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        查询期权信号
        
        Args:
            symbol: 股票代码（可选）
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）
            processed: 处理状态过滤（可选）
            limit: 返回数量限制
            
        Returns:
            List[Dict]: 期权信号列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = 'SELECT * FROM option_signals WHERE 1=1'
            params = []
            
            if symbol:
                query += ' AND symbol = ?'
                params.append(symbol)
            
            if start_date:
                query += ' AND signal_time >= ?'
                params.append(start_date)
            
            if end_date:
                query += ' AND signal_time <= ?'
                params.append(end_date)
            
            if processed is not None:
                query += ' AND processed = ?'
                params.append(1 if processed else 0)
            
            query += ' ORDER BY signal_time DESC LIMIT ?'
            params.append(limit)
            
            cursor.execute(query, params)
            
            signals = []
            for row in cursor.fetchall():
                signal = dict(row)
                # 解析 meta JSON
                if signal.get('meta'):
                    try:
                        signal['meta'] = json.loads(signal['meta'])
                    except:
                        pass
                signals.append(signal)
            
            return signals
    
    def get_option_signal_stats(self, days: int = 7) -> Dict:
        """
        获取期权信号统计
        
        Args:
            days: 统计最近多少天
            
        Returns:
            Dict: 统计结果
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            et_now = datetime.now(ZoneInfo('America/New_York'))
            start_time = (et_now - timedelta(days=days)).isoformat()
            
            stats = {}
            
            # 总信号数
            cursor.execute('''
                SELECT COUNT(*) FROM option_signals
                WHERE signal_time >= ?
            ''', (start_time,))
            stats['total_signals'] = cursor.fetchone()[0]
            
            # 已处理信号数
            cursor.execute('''
                SELECT COUNT(*) FROM option_signals
                WHERE signal_time >= ? AND processed = 1
            ''', (start_time,))
            stats['processed_signals'] = cursor.fetchone()[0]
            
            # 生成订单数
            cursor.execute('''
                SELECT COUNT(*) FROM option_signals
                WHERE signal_time >= ? AND generated_order = 1
            ''', (start_time,))
            stats['orders_generated'] = cursor.fetchone()[0]
            
            # 按股票统计
            cursor.execute('''
                SELECT symbol, COUNT(*) as count
                FROM option_signals
                WHERE signal_time >= ?
                GROUP BY symbol
                ORDER BY count DESC
                LIMIT 10
            ''', (start_time,))
            stats['top_symbols'] = [
                {'symbol': row[0], 'count': row[1]}
                for row in cursor.fetchall()
            ]
            
            return stats
    
    # ============ 备份和维护 ============
    
    def backup(self, backup_path: str):
        """备份数据库"""
        import shutil
        # 确保备份目录存在
        backup_dir = Path(backup_path).parent
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.db_path, backup_path)
        self.logger.info(f"数据库已备份到: {backup_path}")
    
    def vacuum(self):
        """清理和优化数据库"""
        with self._get_connection() as conn:
            conn.execute('VACUUM')
        self.logger.info("数据库已优化")


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    db = DatabaseManager('test_trading.db')
    
    # 测试保存订单
    order = {
        'order_id': 'AAPL_20241012_001',
        'symbol': 'AAPL',
        'order_type': 'BUY',
        'order_time': datetime.now(ZoneInfo('America/New_York')).isoformat(),
        'shares': 100,
        'price': 150.0,
        'status': 'PENDING',
        'signal_id': 'SIG_001',
        'pos_ratio': 0.25
    }
    db.save_order(order)
    
    # 测试保存持仓
    position = {
        'symbol': 'AAPL',
        'shares': 100,
        'entry_time': datetime.now(ZoneInfo('America/New_York')).isoformat(),
        'entry_price': 150.0,
        'entry_order_id': 'AAPL_20241012_001',
        'signal_id': 'SIG_001',
        'target_profit_price': 172.5,
        'stop_loss_price': 142.5
    }
    db.save_position(position)
    
    # 测试查询
    print("\n所有开仓持仓:")
    positions = db.get_all_open_positions()
    for pos in positions:
        print(f"  {pos['symbol']}: {pos['shares']} 股 @ ${pos['entry_price']}")
    
    # 测试统计
    print("\n今日统计:")
    stats = db.get_daily_stats()
    print(f"  买入订单: {stats['buy_orders']}")
    print(f"  卖出订单: {stats['sell_orders']}")
    print(f"  持仓数: {stats['open_positions']}")

