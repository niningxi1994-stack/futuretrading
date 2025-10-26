#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V7策略回测脚本 - 分钟循环架构
与实盘system_v7.py完全一致的逻辑
"""

import sys
import yaml
import csv
import json
import logging
import pandas as pd
import pandas_market_calendars as mcal
import pytz
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'future_v_0_1'))

from strategy.v7 import StrategyV7
from strategy.strategy import StrategyContext, SignalEvent
from market.backtest_client import BacktestMarketClient


class BacktestRunner:
    """回测运行器 - 简化版本，分钟循环"""
    
    def __init__(self, csv_dir: str, stock_data_dir: str, config: Dict, initial_cash: float = 100000.0):
        """
        初始化回测运行器
        
        Args:
            csv_dir: 期权CSV文件目录
            stock_data_dir: 股价数据目录
            config: 配置字典
            initial_cash: 初始资金
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.csv_dir = Path(csv_dir)
        self.stock_data_dir = Path(stock_data_dir)
        self.config = config
        self.initial_cash = initial_cash
        
        # 从config读取交易成本参数
        cost_cfg = {
            'slippage': 0.0005,
            'commission_per_share': 0.005,
            'min_commission': 1.0
        }
        
        # 创建回测客户端
        self.market_client = BacktestMarketClient(
            stock_data_dir=stock_data_dir,
            initial_cash=initial_cash,
            slippage=cost_cfg.get('slippage', 0.0005),
            commission_per_share=cost_cfg.get('commission_per_share', 0.005),
            min_commission=cost_cfg.get('min_commission', 1.0)
        )
        
        # 创建策略
        strategy_context = StrategyContext(
            cfg=config,
            logger=logging.getLogger('StrategyV7')
        )
        self.strategy = StrategyV7(strategy_context)
        
        # 记录
        self.trade_records = []
        self.signal_records = []
        self.position_entry_times = {}  # {symbol: entry_time}
        
        self.logger.info(
            f"回测运行器初始化完成: "
            f"CSV={csv_dir}, 股价={stock_data_dir}, 资金=${initial_cash:,.2f}"
        )
    
    def load_signals(self, max_files: Optional[int] = None) -> List[Dict]:
        """
        加载所有信号
        
        Returns:
            信号列表（按时间排序）
        """
        self.logger.info("加载期权信号...")
        csv_files = list(self.csv_dir.glob("*.csv"))
        
        if max_files:
            csv_files = csv_files[:max_files]
        
        signals = []
        
        for csv_file in csv_files:
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                
                if len(rows) == 0:
                    continue
                
                # 最后一行是信号，前面是历史
                signal_row = rows[-1]
                history_rows = rows[:-1]
                
                # 解析信号
                signal = self._parse_signal(signal_row)
                if signal:
                    signals.append({
                        'signal': signal,
                        'history': history_rows,
                        'file': csv_file
                    })
                    
            except Exception as e:
                self.logger.debug(f"加载文件失败 {csv_file}: {e}")
        
        # 按时间排序
        signals.sort(key=lambda x: x['signal'].event_time_et)
        
        self.logger.info(f"共加载 {len(signals)} 个信号")
        return signals
    
    def _parse_signal(self, row: Dict) -> Optional[SignalEvent]:
        """解析CSV行为SignalEvent"""
        try:
            symbol = row['underlying_symbol']
            date_str = row['date']
            time_str = row['time']
            premium = float(row['premium'].replace(',', ''))
            stock_price = float(row['stock_price'])
            contract = row['contract']
            
            # 北京时间 → ET时间
            datetime_str = f"{date_str} {time_str}"
            signal_time_cn = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
            cn_tz = pytz.timezone('Asia/Shanghai')
            signal_time_cn = cn_tz.localize(signal_time_cn)
            et_tz = pytz.timezone('America/New_York')
            signal_time_et = signal_time_cn.astimezone(et_tz)
            
            return SignalEvent(
                event_id=f"{symbol}_{signal_time_et.strftime('%Y%m%d%H%M%S')}",
                symbol=symbol,
                premium_usd=premium,
                ask=stock_price,
                chain_id=contract,
                event_time_cn=signal_time_cn,
                event_time_et=signal_time_et
            )
            
        except Exception as e:
            self.logger.debug(f"解析信号失败: {e}")
            return None
    
    def check_historical_filter(self, premium: float, history_rows: List[Dict]) -> bool:
        """检查历史premium过滤"""
        if len(history_rows) == 0:
            return True
        
        # 计算历史均值
        premiums = []
        for row in history_rows:
            try:
                p = float(row['premium'].replace(',', ''))
                premiums.append(p)
            except:
                continue
        
        if len(premiums) == 0:
            return True
        
        avg = sum(premiums) / len(premiums)
        multiplier = self.strategy.historical_premium_multiplier
        threshold = avg * multiplier
        
        return premium > threshold
    
    def run(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None):
        """
        运行回测 - 真正的分钟循环架构
        
        Args:
            max_signals: 最大信号数（测试用）
        """
        # 加载信号
        all_signals = self.load_signals()
        
        if len(all_signals) == 0:
            self.logger.warning("无信号数据")
            return
        
        # Group signals by 20-second intervals
        signals_by_time = {}
        for sig_data in all_signals:
            sig_time = sig_data['signal'].event_time_et
            # Truncate to nearest 20-second interval
            seconds = sig_time.second
            interval_second = (seconds // 20) * 20
            sig_time_interval = sig_time.replace(second=interval_second, microsecond=0)
            if sig_time_interval not in signals_by_time:
                signals_by_time[sig_time_interval] = []
            signals_by_time[sig_time_interval].append(sig_data)
        
        # 获取回测日期范围
        all_times = sorted(signals_by_time.keys())
        default_start_date = all_times[0].date()
        default_end_date = all_times[-1].date()
        
        # 使用方法参数中的日期，或使用默认值
        actual_start_date = start_date.date() if start_date and hasattr(start_date, 'date') else (start_date if start_date else default_start_date)
        actual_end_date = end_date.date() if end_date and hasattr(end_date, 'date') else (end_date if end_date else default_end_date)
        
        self.logger.info(f"回测时间: {actual_start_date} 至 {actual_end_date}")
        self.logger.info(f"共 {len(all_signals)} 个信号")
        
        # 预加载股价数据
        all_symbols = {sig_data['signal'].symbol for sig_data in all_signals}
        self.logger.info(f"预加载 {len(all_symbols)} 个股票价格数据...")
        for symbol in all_symbols:
            self.market_client._load_stock_price_data(symbol)
        
        # 开始回测
        self.strategy.on_start()
        et_tz = pytz.timezone('America/New_York')
        
        # Get NYSE trading calendar
        nyse = mcal.get_calendar('NYSE')
        trading_days = nyse.valid_days(
            start_date=actual_start_date.strftime('%Y-%m-%d'),
            end_date=actual_end_date.strftime('%Y-%m-%d')
        )
        trading_days_set = set(pd.to_datetime(trading_days).date)
        
        self.logger.info(f"NYSE 交易日: {len(trading_days_set)} 天")
        
        # Generate all 20-second intervals (9:30-16:00 each trading day only)
        start_date = actual_start_date
        end_date = actual_end_date
        
        all_intervals = []
        current_date = start_date
        while current_date <= end_date:
            # Only generate intervals for NYSE trading days
            if current_date in trading_days_set:
                day_start = et_tz.localize(datetime.combine(current_date, datetime.min.time()).replace(hour=9, minute=30))
                day_end = et_tz.localize(datetime.combine(current_date, datetime.min.time()).replace(hour=16, minute=0))
                
                current_time = day_start
                while current_time <= day_end:
                    all_intervals.append(current_time)
                    current_time += timedelta(seconds=20)
            
            current_date += timedelta(days=1)
        
        self.logger.info(f"Generated {len(all_intervals)} intervals (20-second)")
        
        # Loop through each 20-second interval
        current_date = None
        for idx, current_time in enumerate(all_intervals, 1):
            if idx % 500 == 0:
                self.logger.info(f"Progress: {idx}/{len(all_intervals)} ({idx/len(all_intervals):.1%})")
            
            # 检查换日
            minute_date = current_time.date()
            if current_date is None:
                current_date = minute_date
                self.strategy.on_day_open(current_date)
            elif minute_date != current_date:
                self.strategy.on_day_close(current_date)
                self.strategy.daily_trade_count = 0
                current_date = minute_date
                self.strategy.on_day_open(current_date)
            
            # 设置当前时间
            self.market_client.set_current_time(current_time)
            
            # 1. 每分钟检查所有持仓
            exit_decisions = self.strategy.on_minute_check(
                self.market_client,
                entry_time_map={k: v.isoformat() for k, v in self.position_entry_times.items()}
            )
            
            if exit_decisions:
                for exit_dec in exit_decisions:
                    self._execute_sell(exit_dec, current_time)
            
            # 2. 如果该分钟有信号，处理信号
            if current_time in signals_by_time:
                for sig_data in signals_by_time[current_time]:
                    signal = sig_data['signal']
                    history = sig_data['history']
                    
                    # 历史过滤
                    if not self.check_historical_filter(signal.premium_usd, history):
                        self.signal_records.append({
                            'symbol': signal.symbol,
                            'time': signal.event_time_et,
                            'decision': 'FILTERED_HISTORICAL'
                        })
                        continue
                    
                    # 策略判断（包含做空过滤，已集成到策略内部）
                    decision = self.strategy.on_signal(signal, self.market_client)
                    
                    if decision:
                        self.signal_records.append({
                            'symbol': signal.symbol,
                            'time': signal.event_time_et,
                            'decision': 'BUY',
                            'shares': decision.shares,
                            'position_ratio': decision.pos_ratio
                        })
                        
                        # 执行买入
                        self._execute_buy(decision, signal)
                        
                        # 记录进入时间
                        self.position_entry_times[signal.symbol] = signal.event_time_et
                        
                        # 更新策略状态
                        self.strategy.daily_trade_count += 1
                        self.strategy.blacklist[signal.symbol] = signal.event_time_et
                        
                    else:
                        self.signal_records.append({
                            'symbol': signal.symbol,
                            'time': signal.event_time_et,
                            'decision': 'FILTERED'
                        })
        
        # 回测结束
        self._close_all_positions()
        self.strategy.on_shutdown()
        
        self.logger.info("回测完成！")
    
    def _execute_buy(self, decision, signal):
        """执行买入"""
        order = self.market_client.buy_stock(
            symbol=decision.symbol,
            quantity=decision.shares,
            price=decision.price_limit,
            order_type='LIMIT'
        )
        
        if order:
            self.trade_records.append({
                'type': 'BUY',
                'symbol': decision.symbol,
                'time': signal.event_time_et,
                'shares': order['quantity'],
                'price': order['price'],
                'amount': order['cost'],
                'premium': signal.premium_usd,
                'position_ratio': decision.pos_ratio
            })
    
    def _execute_sell(self, decision, current_time):
        """执行卖出"""
        order = self.market_client.sell_stock(
            symbol=decision.symbol,
            quantity=decision.shares,
            price=decision.price_limit,
            order_type='LIMIT'
        )
        
        if order:
            self.trade_records.append({
                'type': 'SELL',
                'symbol': decision.symbol,
                'time': current_time,
                'shares': order['quantity'],
                'price': order['price'],
                'amount': order['proceeds'],
                'reason': decision.reason
            })
            
            # 移除持仓记录
            if decision.symbol in self.position_entry_times:
                del self.position_entry_times[decision.symbol]
    
    def _close_all_positions(self):
        """回测结束时平掉所有持仓"""
        positions = self.market_client.get_positions()
        if not positions:
            return
        
        self.logger.info(f"回测结束，平掉 {len(positions)} 个剩余持仓...")
        
        for pos in positions:
            order = self.market_client.sell_stock(
                symbol=pos['symbol'],
                quantity=pos['position'],
                price=pos['market_price'],
                order_type='LIMIT'
            )
            
            if order:
                self.trade_records.append({
                    'type': 'SELL',
                    'symbol': pos['symbol'],
                    'time': datetime.now(pytz.timezone('America/New_York')),
                    'shares': order['quantity'],
                    'price': order['price'],
                    'amount': order['proceeds'],
                    'reason': '回测结束'
                })
    
    def generate_report(self) -> Dict:
        """生成回测报告"""
        summary = self.market_client.get_summary()
        
        total_signals = len(self.signal_records)
        buy_signals = len([s for s in self.signal_records if s['decision'] == 'BUY'])
        filtered = total_signals - buy_signals
        
        return {
            '=== 账户概况 ===': {
                '初始资金': f"${summary['initial_cash']:,.2f}",
                '最终资金': f"${summary['cash']:,.2f}",
                '持仓市值': f"${summary['position_value']:,.2f}",
                '总资产': f"${summary['total_assets']:,.2f}",
                '总盈亏': f"${summary['total_pnl']:+,.2f}",
                '收益率': f"{summary['total_pnl_ratio']:+.2%}"
            },
            '=== 交易统计 ===': {
                '总信号数': total_signals,
                '买入信号': buy_signals,
                '过滤信号': filtered,
                '过滤率': f"{filtered/total_signals:.1%}" if total_signals > 0 else 'N/A',
                '实际交易数': len([t for t in self.trade_records if t['type'] == 'BUY']),
                '持仓数': summary['num_positions']
            },
            '=== 盈亏分析 ===': {
                '已实现盈亏': f"${summary['realized_pnl']:+,.2f}",
                '未实现盈亏': f"${summary['unrealized_pnl']:+,.2f}"
            }
        }
    
    def print_report(self):
        """打印报告"""
        report = self.generate_report()
        
        print("\n" + "="*60)
        print("回测报告")
        print("="*60)
        
        for section, data in report.items():
            print(f"\n{section}")
            for key, value in data.items():
                print(f"  {key}: {value}")
        
        print("\n" + "="*60)
    
    def save_report(self, filename: str):
        """保存报告到JSON"""
        report = self.generate_report()
        
        # Add profit info to SELL trades
        self._add_profit_to_trades()
        
        output = {
            'backtest_time': datetime.now().isoformat(),
            'config_file': 'config_v7.yaml',
            'csv_dir': str(self.csv_dir),
            'initial_cash': self.initial_cash,
            'report': report,
            'trades': self.trade_records
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)
        
        self.logger.info(f"报告已保存: {filename}")
    
    def _add_profit_to_trades(self):
        """为SELL交易添加收益信息"""
        symbol_buys = {}  # {symbol: [buy_records]}
        
        # First pass: collect all BUY records
        for trade in self.trade_records:
            if trade['type'] == 'BUY':
                symbol = trade['symbol']
                if symbol not in symbol_buys:
                    symbol_buys[symbol] = []
                symbol_buys[symbol].append(trade)
        
        # Second pass: add profit to SELL records
        for trade in self.trade_records:
            if trade['type'] == 'SELL' and 'profit' not in trade:
                symbol = trade['symbol']
                if symbol in symbol_buys and symbol_buys[symbol]:
                    buy = symbol_buys[symbol].pop(0)
                    buy_amount = buy['amount']
                    sell_amount = trade['amount']
                    profit = sell_amount - buy_amount
                    profit_rate = (profit / buy_amount * 100) if buy_amount > 0 else 0
                    
                    trade['profit'] = round(profit, 2)
                    trade['profit_rate'] = round(profit_rate, 2)
                    trade['buy_price'] = round(buy['price'], 4)
                    trade['buy_time'] = buy['time']


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='V7策略回测')
    parser.add_argument('--config', '-c', default='config_v7.yaml', help='配置文件')
    parser.add_argument('--csv-dir', '-d', default='future_v_0_1/database/call_csv_files_clean', help='CSV目录')
    parser.add_argument('--stock-dir', '-s', default='future_v_0_1/database/stock_data_csv_min', help='股价目录')
    parser.add_argument('--cash', type=float, default=1000000.0, help='初始资金')
    parser.add_argument('--start-date', type=str, default=None, help='开始日期（YYYY-MM-DD），不指定则从最早信号开始')
    parser.add_argument('--end-date', type=str, default=None, help='结束日期（YYYY-MM-DD），不指定则到最晚信号')
    parser.add_argument('--output', '-o', default='backtest_v7_final.json', help='输出文件')
    parser.add_argument('--log-file', default='backtest_log.txt', help='日志文件')
    
    args = parser.parse_args()
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(args.log_file),
            logging.StreamHandler()
        ]
    )
    
    logger = logging.getLogger(__name__)
    
    # 加载配置
    logger.info(f"加载配置: {args.config}")
    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 添加回测成本配置
    if 'backtest' not in config:
        config['backtest'] = {}
    config['backtest']['cost'] = {
        'slippage': 0.001,
        'commission_per_share': 0.005,
        'min_commission': 1.0
    }
    
    print("\n" + "="*60)
    print("V7策略回测 - 分钟循环架构")
    print("="*60)
    print(f"配置: {args.config}")
    print(f"CSV目录: {args.csv_dir}")
    print(f"股价目录: {args.stock_dir}")
    print(f"初始资金: ${args.cash:,.2f}")
    print("="*60 + "\n")
    
    # 创建运行器
    runner = BacktestRunner(
        csv_dir=args.csv_dir,
        stock_data_dir=args.stock_dir,
        config=config,
        initial_cash=args.cash
    )
    
    # 解析日期参数
    start_date_obj = None
    end_date_obj = None
    
    if args.start_date:
        try:
            start_date_obj = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        except ValueError:
            logger.warning(f"开始日期 '{args.start_date}' 格式不正确，使用默认值")
    
    if args.end_date:
        try:
            end_date_obj = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        except ValueError:
            logger.warning(f"结束日期 '{args.end_date}' 格式不正确，使用默认值")
    
    # 运行回测
    start_time = datetime.now()
    logger.info(f"回测开始: {start_time}")
    
    runner.run(start_date=start_date_obj, end_date=end_date_obj)
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    logger.info(f"回测结束: {end_time}, 用时{duration:.1f}秒")
    
    # 打印报告
    runner.print_report()
    
    # 保存报告
    runner.save_report(args.output)
    
    print(f"\n✓ 回测完成！报告已保存到: {args.output}")


if __name__ == '__main__':
    main()
