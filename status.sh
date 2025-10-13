#!/bin/bash

################################################################################
# 交易系统状态查询脚本
# 功能：查看交易系统运行状态、资源占用、最新日志
################################################################################

# 项目根目录
PROJECT_DIR="/Users/niningxi/Desktop/future"
cd "$PROJECT_DIR" || exit 1

# PID 文件
PID_FILE="$PROJECT_DIR/trading_system.pid"

# 日志文件
SYSTEM_LOG="$PROJECT_DIR/logs/trading_system.log"
STDOUT_LOG="$PROJECT_DIR/logs/stdout.log"
STDERR_LOG="$PROJECT_DIR/logs/stderr.log"

################################################################################
# 颜色定义
################################################################################
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

################################################################################
# 函数：打印带颜色的消息
################################################################################
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

title() {
    echo -e "${CYAN}$1${NC}"
}

################################################################################
# 函数：检查进程是否运行
################################################################################
is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0  # 运行中
        else
            return 1  # 未运行
        fi
    else
        return 1  # 未运行
    fi
}

################################################################################
# 函数：显示进程信息
################################################################################
show_process_info() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        
        echo
        title "【进程信息】"
        echo "  状态: ${GREEN}运行中 ✓${NC}"
        echo "  PID: $PID"
        
        # 获取启动时间
        if command -v ps &> /dev/null; then
            START_TIME=$(ps -p "$PID" -o lstart= 2>/dev/null)
            [ -n "$START_TIME" ] && echo "  启动时间: $START_TIME"
            
            # 运行时长
            ELAPSED=$(ps -p "$PID" -o etime= 2>/dev/null | tr -d ' ')
            [ -n "$ELAPSED" ] && echo "  运行时长: $ELAPSED"
        fi
        
        # CPU 和内存使用
        if command -v ps &> /dev/null; then
            CPU=$(ps -p "$PID" -o %cpu= 2>/dev/null | tr -d ' ')
            MEM=$(ps -p "$PID" -o %mem= 2>/dev/null | tr -d ' ')
            RSS=$(ps -p "$PID" -o rss= 2>/dev/null | tr -d ' ')
            
            [ -n "$CPU" ] && echo "  CPU 使用: ${CPU}%"
            [ -n "$MEM" ] && echo "  内存使用: ${MEM}%"
            [ -n "$RSS" ] && echo "  内存占用: $((RSS / 1024)) MB"
        fi
        
        # 命令行
        CMD=$(ps -p "$PID" -o command= 2>/dev/null)
        [ -n "$CMD" ] && echo "  命令: $CMD"
        
    else
        echo
        title "【进程信息】"
        echo "  状态: ${RED}未运行 ✗${NC}"
        
        # 检查是否有残留的 PID 文件
        if [ -f "$PID_FILE" ]; then
            warn "发现残留的 PID 文件: $PID_FILE"
            warn "运行 ./stop.sh 清理"
        fi
    fi
}

################################################################################
# 函数：显示日志信息
################################################################################
show_log_info() {
    echo
    title "【日志文件】"
    
    if [ -f "$SYSTEM_LOG" ]; then
        SIZE=$(du -h "$SYSTEM_LOG" 2>/dev/null | cut -f1)
        LINES=$(wc -l < "$SYSTEM_LOG" 2>/dev/null)
        echo "  系统日志: $SYSTEM_LOG"
        echo "    大小: $SIZE, 行数: $LINES"
    else
        echo "  系统日志: ${YELLOW}不存在${NC}"
    fi
    
    if [ -f "$STDOUT_LOG" ]; then
        SIZE=$(du -h "$STDOUT_LOG" 2>/dev/null | cut -f1)
        LINES=$(wc -l < "$STDOUT_LOG" 2>/dev/null)
        echo "  标准输出: $STDOUT_LOG"
        echo "    大小: $SIZE, 行数: $LINES"
    else
        echo "  标准输出: ${YELLOW}不存在${NC}"
    fi
    
    if [ -f "$STDERR_LOG" ]; then
        SIZE=$(du -h "$STDERR_LOG" 2>/dev/null | cut -f1)
        LINES=$(wc -l < "$STDERR_LOG" 2>/dev/null)
        echo "  错误日志: $STDERR_LOG"
        echo "    大小: $SIZE, 行数: $LINES"
        
        # 检查是否有错误
        ERROR_COUNT=$(grep -c "ERROR" "$STDERR_LOG" 2>/dev/null || echo "0")
        if [ "$ERROR_COUNT" -gt 0 ]; then
            warn "  ⚠️  检测到 $ERROR_COUNT 个错误"
        fi
    else
        echo "  错误日志: ${YELLOW}不存在${NC}"
    fi
}

################################################################################
# 函数：显示最新日志
################################################################################
show_recent_logs() {
    echo
    title "【最新日志】(最近10行)"
    
    if [ -f "$SYSTEM_LOG" ]; then
        echo
        echo "--- 系统日志 ---"
        tail -n 10 "$SYSTEM_LOG" 2>/dev/null || echo "${YELLOW}无法读取${NC}"
    fi
    
    # 如果有错误，显示最新的错误
    if [ -f "$STDERR_LOG" ]; then
        ERROR_COUNT=$(wc -l < "$STDERR_LOG" 2>/dev/null)
        if [ "$ERROR_COUNT" -gt 0 ]; then
            echo
            echo "--- 错误日志 (最近5行) ---"
            tail -n 5 "$STDERR_LOG" 2>/dev/null
        fi
    fi
}

################################################################################
# 函数：显示 Futu 连接状态
################################################################################
show_futu_status() {
    echo
    title "【Futu OpenD 状态】"
    
    if nc -z 127.0.0.1 11111 2>/dev/null; then
        echo "  端口 11111: ${GREEN}已连接 ✓${NC}"
    else
        echo "  端口 11111: ${RED}未连接 ✗${NC}"
        warn "  Futu OpenD 可能未启动"
    fi
}

################################################################################
# 函数：显示快捷命令
################################################################################
show_commands() {
    echo
    title "【快捷命令】"
    echo "  启动系统: ./start.sh"
    echo "  停止系统: ./stop.sh"
    echo "  重启系统: ./restart.sh"
    echo "  查看状态: ./status.sh"
    echo "  实时日志: tail -f $SYSTEM_LOG"
    echo "  查看对账: python view_reconciliation_history.py"
    echo "  查看数据库: python show_db.py"
}

################################################################################
# 主程序
################################################################################
main() {
    echo "========================================"
    echo "   交易系统状态查询"
    echo "========================================"
    
    # 显示各项信息
    show_process_info
    show_futu_status
    show_log_info
    show_recent_logs
    show_commands
    
    echo
    echo "========================================"
}

# 执行主程序
main



