"""
测试symbol标准化修复
"""

import sys
from pathlib import Path

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent / 'future_v_0_1'))

from tradingsystem.system import normalize_symbol

def test_normalize_symbol():
    """测试symbol标准化函数"""
    
    print("="*80)
    print("🧪 测试 symbol 标准化函数")
    print("="*80)
    print()
    
    test_cases = [
        ("AAPL", "US", "US.AAPL"),
        ("MGNI", "US", "US.MGNI"),
        ("US.TSLA", "US", "US.TSLA"),  # 已有前缀，不应重复添加
        ("PINS", "US", "US.PINS"),
        ("HK.00700", "US", "HK.00700"),  # 不同市场，应保持原样
    ]
    
    all_passed = True
    
    for input_symbol, market, expected in test_cases:
        result = normalize_symbol(input_symbol, market)
        passed = result == expected
        
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} | normalize_symbol('{input_symbol}', '{market}')")
        print(f"     期望: {expected}")
        print(f"     实际: {result}")
        print()
        
        if not passed:
            all_passed = False
    
    print("="*80)
    if all_passed:
        print("✅ 所有测试通过！")
    else:
        print("❌ 部分测试失败！")
    print("="*80)
    
    return all_passed


if __name__ == '__main__':
    success = test_normalize_symbol()
    sys.exit(0 if success else 1)

