#!/usr/bin/env python3
"""
V7策略回测脚本
从CSV文件读取期权数据，模拟交易执行
"""

import sys
import yaml
import logging
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'future_v_0_1'))

# 导入回测引擎（现在在market目录下）
from market.backtest_engine import BacktestEngine


def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='V7策略回测')
    parser.add_argument(
        '--config', '-c',
        type=str,
        default='config_v7.yaml',
        help='配置文件路径（默认：config_v7.yaml）'
    )
    parser.add_argument(
        '--csv-dir', '-d',
        type=str,
        default='future_v_0_1/database/call_csv_files_clean',
        help='CSV文件目录（默认：future_v_0_1/database/call_csv_files_clean）'
    )
    parser.add_argument(
        '--stock-data-dir', '-s',
        type=str,
        default='future_v_0_1/database/stock_data_csv_min',
        help='股价数据目录（默认：future_v_0_1/database/stock_data_csv_min）'
    )
    parser.add_argument(
        '--initial-cash',
        type=float,
        default=100000.0,
        help='初始资金（默认：100000）'
    )
    parser.add_argument(
        '--max-files',
        type=int,
        default=None,
        help='最大文件数（用于测试，默认：全部）'
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='日志级别（默认：INFO）'
    )
    parser.add_argument(
        '--save-report',
        type=str,
        default=None,
        help='保存报告到文件'
    )
    
    args = parser.parse_args()
    
    # 配置日志
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger(__name__)
    
    # 读取配置文件
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"❌ 配置文件不存在: {config_path}")
        sys.exit(1)
    
    logger.info(f"读取配置文件: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 回测时禁用策略内部的历史过滤（由回测引擎处理）
    config['strategy']['filter']['call_csv_dir'] = 'BACKTEST_DISABLE'
    logger.info("回测模式：禁用策略内部历史过滤（由回测引擎统一处理）")
    
    # 检查CSV目录
    csv_dir = Path(args.csv_dir)
    if not csv_dir.exists():
        logger.error(f"❌ CSV目录不存在: {csv_dir}")
        sys.exit(1)
    
    csv_files = list(csv_dir.glob("*.csv"))
    logger.info(f"CSV目录: {csv_dir}, 文件数: {len(csv_files)}")
    
    if len(csv_files) == 0:
        logger.error("❌ CSV目录中没有文件")
        sys.exit(1)
    
    # 检查股价数据目录
    stock_data_dir = Path(args.stock_data_dir)
    if not stock_data_dir.exists():
        logger.error(f"❌ 股价数据目录不存在: {stock_data_dir}")
        sys.exit(1)
    
    stock_files = list(stock_data_dir.glob("*.csv"))
    logger.info(f"股价数据目录: {stock_data_dir}, 文件数: {len(stock_files)}")
    
    # 打印回测参数
    print("\n" + "="*60)
    print("V7策略回测")
    print("="*60)
    print(f"配置文件: {config_path}")
    print(f"CSV目录: {csv_dir}")
    print(f"CSV文件数: {len(csv_files)}")
    print(f"股价数据目录: {stock_data_dir}")
    print(f"股价文件数: {len(stock_files)}")
    print(f"初始资金: ${args.initial_cash:,.2f}")
    if args.max_files:
        print(f"最大文件数: {args.max_files}")
    print(f"日志级别: {args.log_level}")
    print("="*60 + "\n")
    
    # 创建回测引擎
    engine = BacktestEngine(
        csv_dir=str(csv_dir),
        stock_data_dir=str(stock_data_dir),
        config=config,
        initial_cash=args.initial_cash
    )
    
    # 运行回测
    start_time = datetime.now()
    logger.info(f"回测开始: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    engine.run_backtest(max_files=args.max_files)
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    logger.info(f"回测结束: {end_time.strftime('%Y-%m-%d %H:%M:%S')}, 耗时: {duration:.2f}秒")
    
    # 打印报告
    engine.print_report()
    
    # 保存报告（可选）
    if args.save_report:
        report_path = Path(args.save_report)
        logger.info(f"\n保存报告到: {report_path}")
        
        import json
        report = engine.generate_report()
        
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                'backtest_time': end_time.isoformat(),
                'duration_seconds': duration,
                'config_file': str(config_path),
                'csv_dir': str(csv_dir),
                'initial_cash': args.initial_cash,
                'report': report,
                'trades': engine.trade_records,
                'signals': engine.signal_records,
            }, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"✓ 报告已保存")
    
    print("\n✓ 回测完成！")


if __name__ == '__main__':
    main()

