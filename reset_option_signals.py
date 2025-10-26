#!/usr/bin/env python3
"""
重置期权信号数据

清空 option_signals 和 processed_files 表，保留 orders 和 positions 表
这样系统会重新处理所有历史期权文件并入库

使用场景：当需要将所有历史期权数据重新入库时
"""

import sqlite3
import sys
from pathlib import Path

def reset_option_signals(db_path: str):
    """
    清空期权信号相关表
    
    Args:
        db_path: 数据库路径
    """
    print("="*80)
    print("重置期权信号数据")
    print("="*80)
    
    # 确认操作
    print(f"\n数据库: {db_path}")
    print("\n即将执行以下操作:")
    print("  1. 清空 option_signals 表 (所有期权信号)")
    print("  2. 清空 processed_files 表 (已处理文件记录)")
    print("\n保留以下表:")
    print("  - orders (订单记录)")
    print("  - positions (持仓记录)")
    print("  - strategy_state (策略状态)")
    print("  - reconciliation_results (对账记录)")
    
    response = input("\n确认继续? (输入 yes 确认): ")
    if response.lower() != 'yes':
        print("操作已取消")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 查询当前数据量
        cursor.execute("SELECT COUNT(*) FROM option_signals")
        signals_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM processed_files")
        files_count = cursor.fetchone()[0]
        
        print(f"\n当前数据:")
        print(f"  - option_signals: {signals_count:,} 条")
        print(f"  - processed_files: {files_count:,} 条")
        
        # 清空表
        print("\n开始清空表...")
        cursor.execute("DELETE FROM option_signals")
        deleted_signals = cursor.rowcount
        print(f"  ✓ 已删除 option_signals: {deleted_signals:,} 条")
        
        cursor.execute("DELETE FROM processed_files")
        deleted_files = cursor.rowcount
        print(f"  ✓ 已删除 processed_files: {deleted_files:,} 条")
        
        # 重置自增ID
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='option_signals'")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='processed_files'")
        print(f"  ✓ 已重置自增ID")
        
        # 提交更改
        conn.commit()
        print("\n✓ 操作完成！")
        print("\n下次系统启动时，将重新处理所有历史期权文件并入库。")
        
    except Exception as e:
        print(f"\n✗ 操作失败: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    # 数据库路径
    db_path = "/Users/niningxi/Desktop/future/op_trade_data/trading.db"
    
    # 检查数据库是否存在
    if not Path(db_path).exists():
        print(f"错误: 数据库文件不存在: {db_path}")
        sys.exit(1)
    
    reset_option_signals(db_path)

