#!/bin/bash

# 进入项目目录
cd /Users/niningxi/Desktop/future

# 初始化 Git 仓库
echo "==> 初始化 Git 仓库..."
git init

# 配置 Git 用户信息（如果还没有配置）
echo "==> 配置 Git 用户信息..."
git config user.name "niningxi1994-stack"
git config user.email "your-email@example.com"  # 请替换为你的邮箱

# 添加所有文件
echo "==> 添加文件到暂存区..."
git add .

# 查看状态
echo "==> 当前状态："
git status

# 提交
echo "==> 提交到本地仓库..."
git commit -m "Initial commit: Future Trading System

- 实现期权信号监控和解析
- 实现 V6 交易策略
- 集成 Futu OpenD API
- 实现数据库持久化（SQLite）
- 实现每日对账功能（17:00 ET）
- 支持对账结果数据库存储
- 支持黑名单机制
- 添加数据查询工具"

# 添加远程仓库
echo "==> 添加远程仓库..."
git remote add origin https://github.com/niningxi1994-stack/futuretrading.git

# 设置主分支名称为 main
echo "==> 设置主分支为 main..."
git branch -M main

# 推送到远程仓库
echo "==> 推送到 GitHub..."
git push -u origin main

echo ""
echo "✅ 完成！代码已推送到 https://github.com/niningxi1994-stack/futuretrading"
echo ""
echo "注意："
echo "1. 如果推送失败，可能需要配置 GitHub 认证"
echo "2. 可以使用 Personal Access Token 或 SSH key"
echo "3. Personal Access Token 设置: https://github.com/settings/tokens"



