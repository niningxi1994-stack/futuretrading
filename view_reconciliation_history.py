#!/usr/bin/env python3
"""
对账历史查询工具
查询和显示数据库中保存的对账记录
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from future_v_0_1.database.models import DatabaseManager
import json
from datetime import datetime


def print_separator(char="=", length=80):
    """打印分隔线"""
    print(char * length)


def print_reconciliation_summary(days=30):
    """打印对账汇总统计"""
    db_path = "/Users/niningxi/Desktop/future/op_trade_data/trading.db"
    
    if not Path(db_path).exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    db = DatabaseManager(db_path)
    
    print_separator()
    print(f"对账汇总统计（最近 {days} 天）")
    print_separator()
    
    summary = db.get_reconciliation_summary(days)
    
    print(f"\n📊 总体统计:")
    print(f"  总对账次数: {summary.get('total_reconciliations', 0)}")
    print(f"  ✅ 通过: {summary.get('passed_count', 0)}")
    print(f"  ⚠️  未通过: {summary.get('failed_count', 0)}")
    print(f"  🔧 自动修复次数: {summary.get('auto_fix_count', 0)}")
    print(f"  ⚠️  发现问题总数: {summary.get('total_issues', 0)}")
    
    if summary.get('total_reconciliations', 0) > 0:
        pass_rate = summary.get('passed_count', 0) / summary['total_reconciliations'] * 100
        print(f"  📈 通过率: {pass_rate:.1f}%")
    
    print()


def print_reconciliation_history(days=7):
    """打印对账历史记录"""
    db_path = "/Users/niningxi/Desktop/future/op_trade_data/trading.db"
    
    if not Path(db_path).exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    db = DatabaseManager(db_path)
    
    print_separator()
    print(f"对账历史记录（最近 {days} 天）")
    print_separator()
    
    history = db.get_reconciliation_history(days)
    
    if not history:
        print("\n暂无对账记录")
        return
    
    print(f"\n共 {len(history)} 条记录:\n")
    
    for i, record in enumerate(history, 1):
        status = "✅ 通过" if record['passed'] else "⚠️  异常"
        auto_fix = "🔧" if record['auto_fix_applied'] else ""
        
        recon_time = record['reconciliation_time']
        if isinstance(recon_time, str):
            try:
                dt = datetime.fromisoformat(recon_time)
                time_str = dt.strftime('%H:%M:%S')
            except:
                time_str = recon_time
        else:
            time_str = str(recon_time)
        
        print(f"[{i:2d}] {record['trading_date']} {time_str} | {status} {auto_fix}")
        print(f"     问题数: {record['issues_count']}")
        print()


def print_reconciliation_detail(trading_date: str):
    """打印指定日期的对账详情"""
    db_path = "/Users/niningxi/Desktop/future/op_trade_data/trading.db"
    
    if not Path(db_path).exists():
        print(f"❌ 数据库不存在: {db_path}")
        return
    
    db = DatabaseManager(db_path)
    
    print_separator()
    print(f"对账详情 [{trading_date}]")
    print_separator()
    
    result = db.get_reconciliation_result(trading_date)
    
    if not result:
        print(f"\n未找到 {trading_date} 的对账记录")
        return
    
    # 基本信息
    print(f"\n📅 对账日期: {result['trading_date']}")
    print(f"⏰ 对账时间: {result['reconciliation_time']}")
    print(f"✅ 对账结果: {'通过' if result['passed'] else '未通过'}")
    print(f"⚠️  问题数量: {result['issues_count']}")
    print(f"🔧 自动修复: {'是' if result['auto_fix_applied'] else '否'}")
    
    # 持仓检查
    print("\n" + "=" * 80)
    print("【1. 持仓检查】")
    print("=" * 80)
    position_check = result.get('position_check', {})
    print(f"  结果: {'✅ 通过' if position_check.get('passed') else '⚠️  异常'}")
    print(f"  数据库持仓数: {position_check.get('db_count', 0)}")
    print(f"  Futu持仓数: {position_check.get('futu_count', 0)}")
    if position_check.get('differences'):
        print(f"  差异数量: {len(position_check['differences'])}")
    
    # 订单检查
    print("\n" + "=" * 80)
    print("【2. 订单检查】")
    print("=" * 80)
    order_check = result.get('order_check', {})
    print(f"  结果: {'✅ 通过' if order_check.get('passed') else '⚠️  异常'}")
    print(f"  数据库订单数: {order_check.get('db_count', 0)}")
    print(f"  Futu订单数: {order_check.get('futu_count', 0)}")
    
    # 账户检查
    print("\n" + "=" * 80)
    print("【3. 账户检查】")
    print("=" * 80)
    account_check = result.get('account_check', {})
    print(f"  结果: {'✅ 通过' if account_check.get('passed') else '⚠️  异常'}")
    if account_check.get('total_assets'):
        print(f"  总资产: ${account_check['total_assets']:,.2f}")
        print(f"  现金: ${account_check['cash']:,.2f}")
    
    # 每日统计
    print("\n" + "=" * 80)
    print("【4. 每日统计】")
    print("=" * 80)
    daily_stats = result.get('daily_stats', {})
    if daily_stats:
        print(f"  买入订单: {daily_stats.get('buy_orders', 0)}")
        print(f"  卖出订单: {daily_stats.get('sell_orders', 0)}")
        print(f"  开仓持仓: {daily_stats.get('open_positions', 0)}")
        print(f"  今日盈亏: ${daily_stats.get('total_pnl', 0):,.2f}")
        print(f"  平均盈亏率: {daily_stats.get('avg_pnl_ratio', 0):+.2%}")
    
    # 问题摘要
    issues = result.get('issues_summary', [])
    if issues:
        print("\n" + "=" * 80)
        print("【5. 问题摘要】")
        print("=" * 80)
        for i, issue in enumerate(issues, 1):
            print(f"\n  问题 {i}:")
            print(f"    类型: {issue.get('type', 'unknown')}")
            if 'symbol' in issue:
                print(f"    股票: {issue['symbol']}")
            if 'description' in issue:
                print(f"    描述: {issue['description']}")
            if 'db_qty' in issue and 'futu_qty' in issue:
                print(f"    数据库数量: {issue['db_qty']}")
                print(f"    Futu数量: {issue['futu_qty']}")
                print(f"    差异: {issue.get('diff', 0)}")
    
    # 修复操作
    fix_actions = result.get('fix_actions', [])
    if fix_actions:
        print("\n" + "=" * 80)
        print("【6. 自动修复操作】")
        print("=" * 80)
        for i, action in enumerate(fix_actions, 1):
            print(f"\n  修复 {i}:")
            print(f"    操作: {action.get('action', 'unknown')}")
            print(f"    股票: {action.get('symbol', 'N/A')}")
            if 'reason' in action:
                print(f"    原因: {action['reason']}")
            if 'old_qty' in action and 'new_qty' in action:
                print(f"    数量变更: {action['old_qty']} → {action['new_qty']}")
    
    print("\n" + "=" * 80)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='对账历史查询工具')
    parser.add_argument('--summary', action='store_true', help='显示汇总统计')
    parser.add_argument('--history', type=int, metavar='DAYS', help='显示最近N天的对账历史')
    parser.add_argument('--detail', type=str, metavar='DATE', help='显示指定日期的对账详情（格式：YYYY-MM-DD）')
    
    args = parser.parse_args()
    
    # 如果没有指定任何参数，显示默认信息
    if not any([args.summary, args.history, args.detail]):
        print_reconciliation_summary(30)
        print()
        print_reconciliation_history(7)
        return
    
    if args.summary:
        print_reconciliation_summary(30)
    
    if args.history:
        print()
        print_reconciliation_history(args.history)
    
    if args.detail:
        print()
        print_reconciliation_detail(args.detail)


if __name__ == "__main__":
    main()

