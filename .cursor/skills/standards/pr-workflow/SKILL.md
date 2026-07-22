---
name: pr-workflow
description: 在需要创建或整理 Pull Request（标题、描述、检查项）时使用。触发词：PR、pull request、开分支、提 MR、评审。
---

# PR Workflow

当用户要求「开 PR」「写 PR 描述」「准备 review」时，遵循以下流程。

## 步骤
1. 确认改动已 commit 并 push 到功能分支（`cursor/...` 命名）。
2. 生成 PR 标题（Conventional Commits 风格）。
3. 生成 PR 描述，包含：
   - **概述**：这次改动做了什么。
   - **动机**：为什么需要。
   - **验证**：如何测试 / 验收标准。
4. 检查 PR 是否聚焦单一主题，过大时建议拆分。

## 注意
- 默认创建 draft PR，除非用户要求直接开正式 PR。
- 不合并 PR、不启用 auto-merge，除非用户明确要求。
