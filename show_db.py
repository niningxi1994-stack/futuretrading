#!/usr/bin/env python3
"""
查看 trading.db 数据库中所有表的数据
"""

import sqlite3
from pathlib import Path

def show_database(db_path):
    """显示数据库中所有表的内容"""
    
    # 连接数据库
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 使结果可以按列名访问
    cursor = conn.cursor()
    
    try:
        # 获取所有表名
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        
        if not tables:
            print("数据库中没有表")
            return
        
        print("=" * 100)
        print(f"数据库: {db_path}")
        print(f"总表数: {len(tables)}")
        print("=" * 100)
        print()
        
        # 遍历每个表
        for table in tables:
            table_name = table['name']
            
            # 获取表结构
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            column_names = [col['name'] for col in columns]
            
            # 获取记录数
            cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
            count = cursor.fetchone()['count']
            
            # 打印表头
            print("=" * 100)
            print(f"表名: {table_name}")
            print(f"记录数: {count}")
            print(f"字段: {', '.join(column_names)}")
            print("=" * 100)
            
            if count == 0:
                print("(空表)")
                print()
                continue
            
            # 读取所有数据
            cursor.execute(f"SELECT * FROM {table_name} ORDER BY rowid DESC LIMIT 20")  # 只显示最近20条
            rows = cursor.fetchall()
            
            # 打印数据
            for i, row in enumerate(rows, 1):
                print(f"\n[记录 {i}]")
                for col_name in column_names:
                    value = row[col_name]
                    # 格式化长字符串
                    if isinstance(value, str) and len(value) > 100:
                        value = value[:100] + "..."
                    print(f"  {col_name:20s}: {value}")
            
            if count > 20:
                print(f"\n... (省略 {count - 20} 条记录)")
            
            print()
    
    finally:
        conn.close()


if __name__ == "__main__":
    db_path = "/Users/niningxi/Desktop/future/op_trade_data/trading.db"
    
    # 检查文件是否存在
    if not Path(db_path).exists():
        print(f"错误: 数据库文件不存在: {db_path}")
    else:
        show_database(db_path)

