#!/usr/bin/env python3
"""
测试 CSV 集成功能
"""
import sys
sys.path.insert(0, '/Users/niningxi/Desktop/future')

from future_v_0_1.optionparser.utils import parse_option_csv, _convert_beijing_to_et
from datetime import datetime
import os

def test_timezone_conversion():
    """测试时区转换"""
    print("\n" + "="*80)
    print("测试 1: 北京时间 → 美东时间转换")
    print("="*80)
    
    test_cases = [
        ("10/22 21:35:08", datetime(2025, 10, 22)),
        ("10/22 03:36:59", datetime(2025, 10, 22)),
        ("10/20 22:22:48", datetime(2025, 10, 20)),
    ]
    
    for time_beijing, ref_date in test_cases:
        time_et = _convert_beijing_to_et(time_beijing, ref_date)
        print(f"  北京: {time_beijing} → 美东: {time_et}")

def test_csv_parsing():
    """测试 CSV 解析"""
    print("\n" + "="*80)
    print("测试 2: CSV 文件解析")
    print("="*80)
    
    # 创建测试 CSV 文件
    test_csv = "/tmp/test_option_signal.csv"
    
    csv_content = """Time,Ticker,Side,Option Type,Contract,Stock,Premium,Bid,Ask
10/23 14:30:00,AAPL,ASK,call,180,175.50,250000,8.50,9.00
10/23 10:15:00,AAPL,ASK,call,175,174.20,180000,6.20,6.80
10/22 16:45:00,AAPL,BID,put,170,173.00,120000,4.10,4.70"""
    
    with open(test_csv, 'w') as f:
        f.write(csv_content)
    
    print(f"  创建测试文件: {test_csv}")
    
    # 解析 CSV
    result = parse_option_csv(test_csv)
    
    if result:
        print(f"\n  ✅ 解析成功:")
        
        primary = result['primary']
        print(f"\n  【主信号】")
        print(f"    时间: {primary.time}")
        print(f"    股票: {primary.symbol}")
        print(f"    方向: {primary.side}")
        print(f"    类型: {primary.option_type}")
        print(f"    合约: {primary.contract}")
        print(f"    股价: ${primary.stock_price:.2f}")
        print(f"    权利金: ${primary.premium:,.0f}")
        
        historical = result['historical']
        print(f"\n  【历史数据】({len(historical)} 条)")
        for i, hist in enumerate(historical, 1):
            print(f"    {i}. {hist['symbol']} {hist['side']} {hist['option_type']} " +
                  f"@ {hist['stock_price']:.2f} - ${hist['premium']:,.0f}")
        
        # 查看 metadata
        if primary.metadata:
            print(f"\n  【元数据】")
            print(f"    总记录数: {primary.metadata.get('total_records', 0)}")
            print(f"    源文件: {os.path.basename(primary.metadata.get('source_file', 'N/A'))}")
            print(f"    历史数据条数: {len(primary.metadata.get('history_option_data', []))}")
    else:
        print(f"  ❌ 解析失败")
    
    # 清理
    os.remove(test_csv)

def test_data_flow():
    """测试数据流"""
    print("\n" + "="*80)
    print("测试 3: 数据流验证")
    print("="*80)
    
    print("""
  CSV 数据流:
  
  CSV 文件 (第1行=主数据, 第2+=历史数据)
       ↓
  parse_option_csv()
       ├─ 读取所有行
       ├─ 转换时区 (北京 → 美东)
       ├─ 第1行 → OptionData.main
       └─ 第2+行 → OptionData.metadata['history_option_data']
       ↓
  OptionMonitor.monitor_one_round()
       ├─ 检测 .csv 扩展名
       ├─ 调用 parse_option_csv()
       └─ 生成 OptionData 对象
       ↓
  TradingSystem._process_signal()
       ├─ 创建 SignalEvent (包含 metadata)
       └─ 调用 strategy.on_signal()
       ↓
  StrategyV7.on_signal()
       ├─ 当日信号过滤
       ├─ 时间窗口过滤
       ├─ 权利金过滤
       ├─ 历史Premium过滤 ← 使用 metadata['history_option_data']
       ├─ 做空交易过滤 ← 使用 metadata['history_option_data']
       └─ 其他过滤...
       ↓
  买入决策 或 被过滤
    """)

if __name__ == '__main__':
    print("\n" + "="*80)
    print("CSV 集成功能测试")
    print("="*80)
    
    try:
        test_timezone_conversion()
        test_csv_parsing()
        test_data_flow()
        
        print("\n" + "="*80)
        print("✅ 所有测试完成！")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
