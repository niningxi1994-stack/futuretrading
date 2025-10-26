#!/bin/bash
# 监控历史数据入库进度

echo "======================================================================================================"
echo "历史数据入库进度监控"
echo "======================================================================================================"
echo ""

# 查询数据库
python3 << 'EOF'
import sqlite3

db_path = '/Users/niningxi/Desktop/future/op_trade_data/trading.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 总数
cursor.execute('SELECT COUNT(*) FROM option_signals')
total = cursor.fetchone()[0]

# APLD
cursor.execute("SELECT COUNT(*) FROM option_signals WHERE symbol LIKE '%APLD%'")
apld = cursor.fetchone()[0]

# 最新的信号时间
cursor.execute('SELECT MAX(signal_time) FROM option_signals')
latest = cursor.fetchone()[0]

# 今天处理的数量
cursor.execute("SELECT COUNT(*) FROM option_signals WHERE created_at LIKE '2025-10-21%'")
today = cursor.fetchone()[0]

print(f"📊 当前入库数据:")
print(f"   总计: {total:,} 条")
print(f"   APLD: {apld} 条")
print(f"   最新信号时间: {latest[:19] if latest else 'N/A'}")
print(f"   今日新增: {today:,} 条")

conn.close()
EOF

echo ""
echo "======================================================================================================
"
echo "提示:"
echo "  - 系统正在后台持续处理历史数据"
echo "  - 预计总共需要处理约20万条期权信号"
echo "  - 可以使用此脚本随时查看进度"
echo "  - 系统初始化完成后会自动开始监控新文件"
echo ""
echo "查看实时日志: tail -f /Users/niningxi/Desktop/future/logs/trading_system.log"
echo "======================================================================================================"

