---
description: 自动提交更改、Push 到当前分支
---

运行以下内联 Shell 逻辑以自动完成提交：

1. **检查 Git 状态与差异**：
   !`git status -s`
   !`git diff --stat`

2. **逻辑处理**：
   - 根据上面的变更，用简洁规范的 Conventional Commits 格式撰写 Commit Message（例如 `feat: ...` 或 `fix: ...`）。
   - 将变更暂存（Stage）并提交：
     !`git add -A && git commit -m "<根据变更总结的Commit Message>"`
   - 推送到远程仓库（自动推送到当前分支或新建同名远程分支）：
     !`git push -u origin HEAD`

3. 向用户汇报 PR 链接。
