#!/bin/bash

################################################################################
# 交易系统启动脚本
# 功能：后台启动交易系统，日志重定向到文件
# 用法：./start.sh [v6|v7]  默认v6
################################################################################

# 策略版本（默认v6）
STRATEGY_VERSION="${1:-v6}"

# 项目根目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR" || exit 1

# 根据策略版本设置文件路径
if [ "$STRATEGY_VERSION" = "v7" ]; then
    CONFIG_FILE="$PROJECT_DIR/config_v7.yaml"
    SCRIPT="$PROJECT_DIR/future_v_0_1/tradingsystem/system_v7.py"
    PID_FILE="$PROJECT_DIR/trading_v7.pid"
    SYSTEM_LOG_NAME="trading_system_v7.log"
    STDOUT_LOG_NAME="stdout_v7.log"
    STDERR_LOG_NAME="stderr_v7.log"
else
    CONFIG_FILE="$PROJECT_DIR/config.yaml"
    SCRIPT="$PROJECT_DIR/future_v_0_1/tradingsystem/system.py"
    PID_FILE="$PROJECT_DIR/trading_system.pid"
    SYSTEM_LOG_NAME="trading_system.log"
    STDOUT_LOG_NAME="stdout.log"
    STDERR_LOG_NAME="stderr.log"
fi

# 日志目录
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# 日志文件
SYSTEM_LOG="$LOG_DIR/$SYSTEM_LOG_NAME"  # Python logging 主日志
STDOUT_LOG="$LOG_DIR/$STDOUT_LOG_NAME"  # 控制台输出（含 logging 输出）
STDERR_LOG="$LOG_DIR/$STDERR_LOG_NAME"  # 未捕获的异常和真正的错误

# Python 解释器
PYTHON="python3"

################################################################################
# 颜色定义
################################################################################
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

################################################################################
# 函数：检查进程是否运行
################################################################################
is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0  # 运行中
        else
            # PID 文件存在但进程不存在，删除旧的 PID 文件
            rm -f "$PID_FILE"
            return 1  # 未运行
        fi
    else
        return 1  # 未运行
    fi
}

################################################################################
# 函数：启动前检查
################################################################################
pre_check() {
    info "执行启动前检查..."
    
    # 1. 检查 Python
    if ! command -v "$PYTHON" &> /dev/null; then
        error "Python3 未安装或不在 PATH 中"
        exit 1
    fi
    info "✓ Python: $($PYTHON --version)"
    
    # 2. 检查配置文件
    if [ ! -f "$CONFIG_FILE" ]; then
        error "配置文件不存在: $CONFIG_FILE"
        exit 1
    fi
    info "✓ 配置文件: $CONFIG_FILE"
    
    # 3. 检查脚本文件
    if [ ! -f "$SCRIPT" ]; then
        error "启动脚本不存在: $SCRIPT"
        exit 1
    fi
    info "✓ 启动脚本: $SCRIPT"
    
    # 4. 检查是否已经运行
    if is_running; then
        PID=$(cat "$PID_FILE")
        error "交易系统已经在运行中 (PID: $PID)"
        error "如需重启，请先执行: ./stop.sh"
        exit 1
    fi
    
    # 5. 检查 Futu OpenD（可选）
    if ! nc -z 127.0.0.1 11111 2>/dev/null; then
        warn "⚠️  Futu OpenD (端口 11111) 似乎未启动"
        warn "请确保 Futu OpenD 已经运行，否则交易系统将无法连接"
        read -p "是否继续启动？(y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            info "启动已取消"
            exit 0
        fi
    else
        info "✓ Futu OpenD 端口连接正常"
    fi
    
    info "所有检查通过！"
    echo
}

################################################################################
# 函数：启动系统
################################################################################
start_system() {
    info "正在启动交易系统..."
    
    # 记录启动时间
    START_TIME=$(date '+%Y-%m-%d %H:%M:%S')
    echo "==================== 系统启动 ====================" >> "$STDOUT_LOG"
    echo "启动时间: $START_TIME" >> "$STDOUT_LOG"
    echo "=================================================" >> "$STDOUT_LOG"
    
    # 后台启动，重定向输出
    # 说明：
    # - trading_system.log: Python logging 的主日志（总是写入）
    # - stdout.log: 捕获 print 语句和启动信息
    # - stderr.log: 捕获未捕获的异常和系统错误
    # 后台运行时，system.py 会自动禁用控制台输出，避免重复
    nohup "$PYTHON" -u "$SCRIPT" --config "$CONFIG_FILE" \
        >> "$STDOUT_LOG" 2>> "$STDERR_LOG" &
    
    # 保存 PID
    PID=$!
    echo "$PID" > "$PID_FILE"
    
    # 等待 2 秒检查进程是否正常启动
    sleep 2
    
    if is_running; then
        info "✓ 交易系统启动成功！"
        info "  PID: $PID"
        info "  配置: $CONFIG_FILE"
        info "  日志: $SYSTEM_LOG"
        info "  标准输出: $STDOUT_LOG"
        info "  错误输出: $STDERR_LOG"
        echo
        info "查看实时日志: tail -f $SYSTEM_LOG"
        info "查看系统状态: ./status.sh"
        info "停止系统: ./stop.sh"
    else
        error "✗ 交易系统启动失败！"
        error "请查看错误日志: $STDERR_LOG"
        rm -f "$PID_FILE"
        exit 1
    fi
}

################################################################################
# 主程序
################################################################################
main() {
    echo "========================================"
    echo "   交易系统启动脚本 (Strategy $STRATEGY_VERSION)"
    echo "========================================"
    echo
    
    # 执行检查
    pre_check
    
    # 启动系统
    start_system
    
    echo
    echo "========================================"
}

# 执行主程序
main



