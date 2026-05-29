# Git 仓库配置指南

## 本地提交状态验证
✅ 本地初始提交已完成：
- 提交哈希：21a7f61
- 提交信息：Initial commit
- 包含文件：94个
- 代码行数：31221行
- 本地分支：main
- 工作区状态：干净

## 为什么远程代码仓看不到？
当前仓库尚未配置任何远程仓库地址，提交仅保存在本地，未同步到远端。

## 配置远程仓库并推送步骤
1. 在代码托管平台（GitHub/Gitee/GitLab等）创建空仓库
2. 执行以下命令添加远程仓库：
```bash
git remote add origin <你的远程仓库地址>
```
   示例（SSH）：`git remote add origin git@github.com:yourname/YuntaoCode.git`
   示例（HTTPS）：`git remote add origin https://github.com/yourname/YuntaoCode.git`

3. 验证远程仓库配置：
```bash
git remote -v
```

4. 推送本地提交到远程：
```bash
git branch -M main
git push -u origin main
```

## 常见推送问题解决
### 连接重置/连接失败
```bash
# 重试推送（网络波动优先尝试）
git push -u origin main

# 配置代理（如有本地代理）
git config --global https.proxy http://127.0.0.1:7890
git config --global http.proxy http://127.0.0.1:7890

# 切换SSH协议（推荐长期解决方案）
git remote set-url origin git@github.com:yuntaozn/YuntaoCode.git
```

## 常用Git操作命令
```bash
# 查看提交历史
git log --oneline

# 查看当前状态
git status

# 拉取远程更新
git pull origin main

# 推送新提交
git push
```
