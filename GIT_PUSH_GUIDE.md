# 🚀 Git 推送操作指导

## 📋 推送到 GitHub 的完整步骤

### 目标仓库
**GitHub URL**: https://github.com/niningxi1994-stack/futuretrading

---

## 🎯 方式 1：使用自动脚本（推荐）

### 一键推送

```bash
# 执行推送脚本
./git_push.sh
```

**脚本会自动完成**：
1. ✅ 添加所有文件
2. ✅ 创建初始提交
3. ✅ 添加远程仓库
4. ✅ 推送到 main 分支

---

## 🔧 方式 2：手动执行（推荐新手理解每一步）

### 步骤 1：添加所有文件到暂存区

```bash
cd /Users/niningxi/Desktop/future
git add .
```

**说明**：将所有文件添加到 Git 暂存区（除了 `.gitignore` 中排除的文件）

**验证**：
```bash
git status
```

你应该看到所有文件变成绿色（已暂存）。

---

### 步骤 2：创建第一次提交

```bash
git commit -m "Initial commit: 交易系统完整实现

主要功能：
- 期权信号监控与解析
- StrategyV6 交易策略
- Futu API 市场接口
- SQLite 数据库持久化
- 每日自动对账（17:00 ET）
- 完整的启动管理脚本
- 日志系统和监控工具

技术栈：
- Python 3.9+
- SQLite
- Futu OpenD API
- 美东时区时间管理
"
```

**说明**：创建初始提交，包含详细的提交说明

**验证**：
```bash
git log
```

你应该看到提交记录。

---

### 步骤 3：添加远程仓库

```bash
git remote add origin https://github.com/niningxi1994-stack/futuretrading.git
```

**说明**：将 GitHub 仓库添加为远程仓库，命名为 `origin`

**验证**：
```bash
git remote -v
```

你应该看到：
```
origin  https://github.com/niningxi1994-stack/futuretrading.git (fetch)
origin  https://github.com/niningxi1994-stack/futuretrading.git (push)
```

---

### 步骤 4：推送到 GitHub

```bash
git push -u origin main
```

**说明**：
- `push` - 推送代码
- `-u` - 设置上游分支（首次推送需要）
- `origin` - 远程仓库名称
- `main` - 分支名称

**如果遇到认证问题**，GitHub 会提示你登录：
- macOS 会弹出密钥链登录窗口
- 或者需要输入 GitHub Personal Access Token

---

## 🔐 GitHub 认证设置

### 如果使用 HTTPS（当前方式）

GitHub 已经不支持密码认证，需要使用 **Personal Access Token (PAT)**。

#### 创建 Personal Access Token

1. 访问：https://github.com/settings/tokens
2. 点击 **"Generate new token"** → **"Generate new token (classic)"**
3. 设置：
   - **Note**: `futuretrading`
   - **Expiration**: `90 days` 或 `No expiration`
   - **Select scopes**: 勾选 `repo` （完整的仓库访问权限）
4. 点击 **"Generate token"**
5. **⚠️ 复制 Token（只显示一次！）**

#### 使用 Token 推送

```bash
# 方式 1: 推送时输入用户名和 Token
git push -u origin main
# Username: niningxi1994-stack
# Password: <粘贴你的 Personal Access Token>

# 方式 2: 在 URL 中包含 Token（会保存凭据）
git remote set-url origin https://<YOUR_TOKEN>@github.com/niningxi1994-stack/futuretrading.git
git push -u origin main
```

#### 保存凭据（可选）

```bash
# macOS 使用 Keychain 保存（推荐）
git config --global credential.helper osxkeychain

# 或者缓存 15 分钟
git config --global credential.helper cache
```

---

### 如果使用 SSH（更安全，推荐长期使用）

#### 1. 检查是否已有 SSH 密钥

```bash
ls -la ~/.ssh
```

如果看到 `id_rsa.pub` 或 `id_ed25519.pub`，说明已有密钥。

#### 2. 生成新的 SSH 密钥

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

一路回车（使用默认路径，不设置密码）。

#### 3. 将 SSH 公钥添加到 GitHub

```bash
# 复制公钥到剪贴板
pbcopy < ~/.ssh/id_ed25519.pub
```

然后：
1. 访问：https://github.com/settings/keys
2. 点击 **"New SSH key"**
3. **Title**: `MacBook Trading System`
4. **Key**: 粘贴公钥
5. 点击 **"Add SSH key"**

#### 4. 修改远程仓库 URL 为 SSH

```bash
git remote set-url origin git@github.com:niningxi1994-stack/futuretrading.git
```

#### 5. 测试连接

```bash
ssh -T git@github.com
```

成功会显示：
```
Hi niningxi1994-stack! You've successfully authenticated, but GitHub does not provide shell access.
```

#### 6. 推送

```bash
git push -u origin main
```

---

## ✅ 推送成功后验证

### 1. 在终端查看

```bash
git log --oneline
```

### 2. 在 GitHub 网页查看

访问：https://github.com/niningxi1994-stack/futuretrading

你应该看到：
- ✅ 所有代码文件
- ✅ README.md 显示在首页
- ✅ 提交记录
- ✅ 文件树结构

---

## 🔄 后续更新代码

推送成功后，如果你修改了代码，使用以下命令更新：

```bash
# 1. 查看修改
git status

# 2. 添加修改的文件
git add .

# 3. 提交
git commit -m "描述你的修改"

# 4. 推送
git push
```

**简化版（一键推送更新）**：
```bash
git add . && git commit -m "更新: $(date '+%Y-%m-%d %H:%M')" && git push
```

---

## 🚨 常见问题

### 问题 1: `fatal: remote origin already exists`

**解决**：
```bash
# 删除现有的远程仓库
git remote remove origin

# 重新添加
git remote add origin https://github.com/niningxi1994-stack/futuretrading.git
```

### 问题 2: `error: failed to push some refs`

**原因**：GitHub 仓库有内容（如 README.md），与本地冲突

**解决**：
```bash
# 先拉取远程内容
git pull origin main --allow-unrelated-histories

# 解决冲突（如果有）
# 然后推送
git push -u origin main
```

### 问题 3: `Authentication failed`

**解决**：
1. 确认使用 Personal Access Token，不是密码
2. Token 权限包含 `repo`
3. 或者切换到 SSH 认证（见上文）

### 问题 4: `Permission denied (publickey)`（SSH）

**解决**：
```bash
# 检查 SSH agent
eval "$(ssh-agent -s)"

# 添加密钥
ssh-add ~/.ssh/id_ed25519

# 测试连接
ssh -T git@github.com
```

### 问题 5: 推送太慢或超时

**解决**：
```bash
# 增加缓冲区
git config --global http.postBuffer 524288000

# 或者使用 SSH（通常更快）
git remote set-url origin git@github.com:niningxi1994-stack/futuretrading.git
```

---

## 📊 推送进度示例

成功推送时，你会看到类似输出：

```
Enumerating objects: 45, done.
Counting objects: 100% (45/45), done.
Delta compression using up to 8 threads
Compressing objects: 100% (38/38), done.
Writing objects: 100% (45/45), 125.50 KiB | 8.37 MiB/s, done.
Total 45 (delta 5), reused 0 (delta 0), pack-reused 0
remote: Resolving deltas: 100% (5/5), done.
To https://github.com/niningxi1994-stack/futuretrading.git
 * [new branch]      main -> main
Branch 'main' set up to track remote branch 'main' from 'origin'.
```

---

## 🎯 快速参考

| 操作 | 命令 |
|------|------|
| 查看状态 | `git status` |
| 添加文件 | `git add .` |
| 提交 | `git commit -m "message"` |
| 推送 | `git push` |
| 拉取 | `git pull` |
| 查看日志 | `git log` |
| 查看远程仓库 | `git remote -v` |
| 查看分支 | `git branch` |

---

## 💡 推荐工作流

### 日常开发

```bash
# 1. 开始工作前，拉取最新代码
git pull

# 2. 修改代码...

# 3. 查看修改
git status
git diff

# 4. 添加、提交、推送
git add .
git commit -m "功能: 添加XXX功能"
git push
```

### 提交信息规范

```bash
# 新功能
git commit -m "功能: 添加持仓到期自动平仓"

# 修复 Bug
git commit -m "修复: 修复时区转换错误"

# 优化
git commit -m "优化: 精简日志输出"

# 文档
git commit -m "文档: 更新启动脚本说明"

# 重构
git commit -m "重构: 重构数据库查询逻辑"
```

---

## 🎉 完成！

推送成功后，你的代码就已经安全地保存在 GitHub 上了！

**查看你的仓库**：
https://github.com/niningxi1994-stack/futuretrading

**分享给他人**：
```bash
git clone https://github.com/niningxi1994-stack/futuretrading.git
```

---

需要帮助？检查上面的常见问题部分或联系 GitHub 支持。

**祝推送顺利！** 🚀✨

