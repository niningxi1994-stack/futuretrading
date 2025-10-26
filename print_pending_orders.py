"""
打印待成交订单的详细信息
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime

db_path = '/Users/niningxi/Desktop/future/op_trade_data/trading.db'

print("="*100)
print("📋 待成交订单详细信息")
print("="*100)
print()

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 查询待成交订单
cursor.execute('''
    SELECT 
        id,
        order_id,
        symbol,
        order_type,
        order_time,
        shares,
        price,
        status,
        signal_id,
        pos_ratio,
        reason,
        filled_time,
        filled_price,
        filled_shares,
        pnl_amount,
        pnl_ratio,
        meta,
        created_at,
        updated_at
    FROM orders
    WHERE symbol IN ('US.MU', 'US.DLTR')
    ORDER BY order_time DESC
''')

orders = cursor.fetchall()

if not orders:
    print("❌ 未找到相关订单")
else:
    print(f"找到 {len(orders)} 个订单\n")
    
    for idx, order in enumerate(orders, 1):
        (id, order_id, symbol, order_type, order_time, shares, price, status,
         signal_id, pos_ratio, reason, filled_time, filled_price, filled_shares,
         pnl_amount, pnl_ratio, meta, created_at, updated_at) = order
        
        print(f"【订单 {idx}】")
        print(f"  ID: {id}")
        print(f"  订单号: {order_id}")
        print(f"  股票: {symbol}")
        print(f"  类型: {order_type}")
        print(f"  状态: {status}")
        print(f"  数量: {shares} 股")
        print(f"  价格: ${price:.2f}")
        print(f"  下单时间: {order_time}")
        print(f"  仓位比例: {pos_ratio:.2%}" if pos_ratio else "  仓位比例: N/A")
        print(f"  关联信号: {signal_id}" if signal_id else "  关联信号: 无")
        print()
        
        print(f"  成交信息:")
        print(f"    成交时间: {filled_time if filled_time else '未成交'}")
        print(f"    成交价格: ${filled_price:.2f}" if filled_price else "    成交价格: N/A")
        print(f"    成交数量: {filled_shares} 股" if filled_shares else "    成交数量: N/A")
        print()
        
        if pnl_amount is not None:
            print(f"  盈亏信息:")
            print(f"    盈亏金额: ${pnl_amount:+,.2f}")
            print(f"    盈亏率: {pnl_ratio:+.2%}" if pnl_ratio else "    盈亏率: N/A")
            print()
        
        print(f"  原因: {reason}" if reason else "  原因: -")
        print(f"  创建时间: {created_at}")
        print(f"  更新时间: {updated_at}" if updated_at else "  更新时间: 未更新")
        print(f"  元数据: {meta}" if meta and meta != '{}' else "  元数据: 无")
        print("="*100)
        print()

conn.close()

print("\n💡 分析:")
print("  - 这两个订单显示为 PENDING 状态")
print("  - 但Futu查询显示已有对应持仓")
print("  - 说明订单实际上已经成交，但数据库状态未更新")
print("  - 系统应该有订单状态同步机制来更新这些订单")

