#!/usr/bin/env python3
"""从Futu API查询实际的订单历史"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import argparse

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / 'future_v_0_1'))

from market.futu_client import FutuClient

def format_datetime(dt_str):
    """格式化日期时间"""
    try:
        if isinstance(dt_str, str):
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        else:
            dt = dt_str
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return str(dt_str)

def query_futu_orders(status_filter=None):
    """从Futu API查询订单历史
    
    Args:
        status_filter: 订单状态过滤 ('PENDING', 'FILLED', 'CANCELLED', None=全部)
    """
    
    print("="*100)
    print("📊 从 Futu API 查询订单历史")
    print("="*100)
    print()
    
    # 创建客户端
    client = FutuClient(
        host='127.0.0.1',
        port=11111,
        trd_env='SIMULATE',
        trd_market='US',
        acc_id=16428245
    )
    
    # 连接
    if not client.connect():
        print("❌ 无法连接到 FutuOpenD")
        return
    
    print("✅ 已连接到 FutuOpenD")
    print()
    
    # 查询订单
    filter_text = f"（状态: {status_filter}）" if status_filter else "（所有状态）"
    print(f"正在查询订单 {filter_text}...")
    print()
    
    orders = client.get_order_list(status_filter=status_filter)
    
    if orders is None:
        print("❌ 查询失败")
        client.disconnect()
        return
    
    if not orders:
        print(f"❌ 未找到订单")
        client.disconnect()
        return
    
    # 过滤买入订单
    buy_orders = [o for o in orders if o.get('side') == 'BUY']
    
    if not buy_orders:
        print(f"❌ 没有买入订单")
        print(f"   （共查询到 {len(orders)} 条订单，但没有买入订单）")
        client.disconnect()
        return
    
    print(f"✅ 找到 {len(buy_orders)} 条买入订单（共 {len(orders)} 条订单）")
    print("="*100)
    print()
    
    # 显示订单详情
    for i, order in enumerate(buy_orders, 1):
        symbol = order.get('symbol', 'N/A')
        order_id = order.get('order_id', 'N/A')
        order_status = order.get('order_status', 'N/A')
        order_status_raw = order.get('order_status_raw', 'N/A')
        qty = order.get('qty', 0)
        price = order.get('price', 0.0)
        dealt_qty = order.get('dealt_qty', 0)
        dealt_avg_price = order.get('dealt_avg_price', 0.0)
        create_time = order.get('create_time', 'N/A')
        updated_time = order.get('updated_time', 'N/A')
        
        print(f"[{i}] {symbol}")
        print(f"    订单ID: {order_id}")
        print(f"    状态: {order_status} ({order_status_raw})")
        print(f"    创建时间: {format_datetime(create_time)}")
        print(f"    更新时间: {format_datetime(updated_time)}")
        print(f"    计划: {qty}股 @ ${price:.2f} = ${qty * price:,.2f}")
        
        if dealt_qty > 0:
            print(f"    成交: {dealt_qty}股 @ ${dealt_avg_price:.2f} = ${dealt_qty * dealt_avg_price:,.2f}")
        else:
            print(f"    成交: 0股")
        
        print()
    
    # 统计信息
    print("="*100)
    print("统计信息:")
    print(f"  总买入订单数: {len(buy_orders)}")
    
    # 按状态分类
    status_count = {}
    for order in buy_orders:
        status = order.get('order_status', 'UNKNOWN')
        status_count[status] = status_count.get(status, 0) + 1
    
    for status, count in sorted(status_count.items()):
        print(f"  {status}: {count}")
    
    filled_orders = [o for o in buy_orders if o.get('order_status') == 'FILLED']
    if filled_orders:
        print(f"  成交率: {len(filled_orders)/len(buy_orders)*100:.1f}%")
        
        total_dealt_amount = sum(o.get('dealt_qty', 0) * o.get('dealt_avg_price', 0) for o in filled_orders)
        if total_dealt_amount > 0:
            print(f"  累计成交金额: ${total_dealt_amount:,.2f}")
    
    print("="*100)
    print()
    
    # 断开连接
    client.disconnect()

def query_specific_order(order_id):
    """查询指定订单的详细信息"""
    
    print("="*100)
    print(f"📊 查询订单 {order_id} 的详细信息")
    print("="*100)
    print()
    
    # 创建客户端
    client = FutuClient(
        host='127.0.0.1',
        port=11111,
        trd_env='SIMULATE',
        trd_market='US',
        acc_id=16428245
    )
    
    # 连接
    if not client.connect():
        print("❌ 无法连接到 FutuOpenD")
        return
    
    print("✅ 已连接到 FutuOpenD")
    print()
    
    # 查询所有订单
    print(f"正在查询订单 {order_id}...")
    print()
    
    orders = client.get_order_list()
    
    if not orders:
        print("❌ 查询失败或没有订单")
        client.disconnect()
        return
    
    # 查找指定订单
    target_order = None
    for order in orders:
        if str(order.get('order_id')) == str(order_id):
            target_order = order
            break
    
    if not target_order:
        print(f"❌ 未找到订单 {order_id}")
        print(f"   （共查询到 {len(orders)} 条订单）")
        client.disconnect()
        return
    
    # 显示详细信息
    print("✅ 找到订单！")
    print("-"*100)
    
    for key, value in sorted(target_order.items()):
        if key in ['create_time', 'updated_time']:
            value = format_datetime(value)
        print(f"  {key}: {value}")
    
    print("-"*100)
    print()
    
    # 断开连接
    client.disconnect()

def compare_with_local_db():
    """对比Futu订单和本地数据库"""
    
    import sqlite3
    
    print("="*100)
    print("📊 对比 Futu 订单 vs 本地数据库")
    print("="*100)
    print()
    
    # 查询Futu订单
    client = FutuClient(
        host='127.0.0.1',
        port=11111,
        trd_env='SIMULATE',
        trd_market='US',
        acc_id=16428245
    )
    
    if not client.connect():
        print("❌ 无法连接到 FutuOpenD")
        return
    
    futu_orders = client.get_order_list()
    if not futu_orders:
        print("❌ 无法从Futu查询订单")
        client.disconnect()
        return
    
    futu_buy_orders = {str(o.get('order_id')): o for o in futu_orders if o.get('side') == 'BUY'}
    
    print(f"✅ Futu: 找到 {len(futu_buy_orders)} 条买入订单（共 {len(futu_orders)} 条订单）")
    
    # 查询本地数据库
    db_path = Path(__file__).parent / 'op_trade_data' / 'trading.db'
    
    if not db_path.exists():
        print("❌ 本地数据库不存在")
        client.disconnect()
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT order_id, symbol, shares, price, status
        FROM orders
        WHERE order_type = 'BUY'
        ORDER BY order_time DESC
    ''')
    
    local_orders = cursor.fetchall()
    conn.close()
    
    print(f"✅ 本地数据库: 找到 {len(local_orders)} 条买入订单")
    print()
    
    # 对比
    print("【对比结果】")
    print("-"*100)
    
    for local_order in local_orders:
        local_order_id, symbol, shares, price, status = local_order
        
        print(f"\n本地订单: {local_order_id} ({symbol})")
        print(f"  本地状态: {status}")
        print(f"  本地数量: {shares}股 @ ${price:.2f}")
        
        # 尝试在Futu订单中查找（按股票代码匹配）
        found_in_futu = False
        for futu_order_id, futu_order in futu_buy_orders.items():
            futu_symbol = futu_order.get('symbol', '')
            # 移除"US."前缀进行比较
            futu_symbol_clean = futu_symbol.replace('US.', '')
            
            if symbol == futu_symbol_clean or symbol == futu_symbol:
                found_in_futu = True
                futu_status = futu_order.get('order_status', 'N/A')
                futu_status_raw = futu_order.get('order_status_raw', 'N/A')
                futu_qty = futu_order.get('qty', 0)
                futu_dealt = futu_order.get('dealt_qty', 0)
                futu_price = futu_order.get('price', 0.0)
                
                print(f"  Futu订单ID: {futu_order_id}")
                print(f"  Futu状态: {futu_status} ({futu_status_raw})")
                print(f"  Futu数量: {futu_qty}股 @ ${futu_price:.2f}")
                print(f"  Futu成交: {futu_dealt}股")
                
                if status != futu_status:
                    print(f"  ⚠️  状态不一致: 本地={status}, Futu={futu_status}")
                    print(f"      建议更新本地数据库状态为: {futu_status}")
                else:
                    print(f"  ✓ 状态一致")
                
                break
        
        if not found_in_futu:
            print(f"  ⚠️  未在Futu中找到对应订单")
            print(f"      可能原因: 订单已过期/被删除，或股票代码不匹配")
    
    print()
    print("-"*100)
    
    client.disconnect()

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='从Futu API查询订单历史')
    parser.add_argument('-s', '--status', type=str, 
                       choices=['PENDING', 'FILLED', 'CANCELLED'],
                       help='过滤订单状态 (PENDING/FILLED/CANCELLED)')
    parser.add_argument('-o', '--order-id', type=str, help='查询指定订单ID的详细信息')
    parser.add_argument('-c', '--compare', action='store_true', help='对比Futu订单和本地数据库')
    
    args = parser.parse_args()
    
    if args.order_id:
        query_specific_order(args.order_id)
    elif args.compare:
        compare_with_local_db()
    else:
        query_futu_orders(status_filter=args.status)

if __name__ == '__main__':
    main()

