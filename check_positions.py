#!/usr/bin/env python3
"""检查当前持仓数据"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from future_v_0_1.market.futu_client import FutuClient

# 连接 Futu
client = FutuClient(
    host='127.0.0.1',
    port=11111,
    trd_env='SIMULATE',
    trd_market='US',
    acc_id=16428245
)

if client.connect():
    positions = client.get_positions()
    
    print("=== 当前持仓数据 ===\n")
    for pos in positions:
        print(f"股票: {pos['symbol']}")
        print(f"  持仓数量 (position): {pos['position']}")
        print(f"  可卖数量 (can_sell_qty): {pos['can_sell_qty']}")
        print(f"  成本价: ${pos['cost_price']:.2f}")
        print(f"  市价: ${pos['market_price']:.2f}")
        print(f"  市值: ${pos['market_value']:,.2f}")
        print()
        
        # 检查是否符合清空条件
        if pos['position'] == 0 and pos['can_sell_qty'] == 0:
            print(f"  ⚠️  {pos['symbol']} 符合清空条件！")
    
    client.disconnect()
else:
    print("❌ 无法连接 Futu OpenD")

