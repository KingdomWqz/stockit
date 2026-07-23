---
description: 自动提交更改、Push 到当前分支
---

按以下步骤完成提交：

1. **检查 Git 状态与差异**：运行 `git status -s` 和 `git diff --stat` 查看变更。

2. **生成 Commit Message 并提交**：
   - 根据变更内容，用简洁规范的 Conventional Commits 格式生成 commit message（例如 `feat: ...`、`fix: ...`、`chore: ...`）。
   - 然后依次执行：
     - `git add -A`
     - `git commit -m "这里填上一步生成的message"` — 务必用实际 message，不要用占位符
     - `git push -u origin HEAD`

3. 汇报 commit hash 和 push 结果。
