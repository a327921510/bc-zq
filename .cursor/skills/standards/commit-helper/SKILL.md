---
name: commit-helper
description: 为已 git add 的暂存改动生成符合主流规范（Conventional Commits）的 commit 文案，供开发者参考取用；默认只读、不自动 add/commit。适用于任意语言与项目类型（前端/后端/移动端/桌面端，Python/Java/Node/TypeScript/Go 等）。触发词：commit、提交、写 commit message、生成提交信息、暂存后出文案、提交前总结 diff、conventional commit。
---

# Commit Helper（通用）

当用户要求「生成 commit / 写提交信息 / 提交前总结 diff」时，**只读已暂存改动并起草 commit 文案**，交给用户参考取用。

## 核心边界（务必遵守）

- **默认只读**：不替用户 `git add`、不执行 `git commit` / `git push` / `git commit --amend` / force push、不改 git config。仅当用户明确要求时才执行相应操作。
- **暂存区是唯一依据**：commit 文案只描述 `git diff --cached` 的内容；未暂存改动仅用于「遗漏提示」。
- **不假设项目结构**：type/scope/语言风格从当前仓库自适应推断（见 Step 2），不写死任何目录或框架。

## 执行流程

### Step 1：并行收集上下文

在仓库根目录同一轮并行执行：

```bash
git status --short
git diff --cached --stat
git diff --cached --name-status
git diff --cached
git diff --stat
git log -15 --format='%s%n%b%n---'
```

- `git diff --cached`：本次提交的全部内容（**唯一依据**）。改动很大时，先看 `--stat`/`--name-status` 摸清范围，再按需细读关键文件的 diff。
- `git diff --stat`：未暂存改动，用于遗漏提示。
- `git log`：学习本仓库既有的 type / scope / subject 语言与措辞风格，尽量对齐。

> 边界态：不在 git 仓库、处于 merge/rebase 冲突中、仓库无任何提交历史时，先如实说明情况再决定是否继续。

### Step 2：探测仓库既有规范

按存在与否调整输出，**已有约定优先于本文默认**：

- `commitlint.config.*` / `.commitlintrc*` / `package.json` 中 commitlint 配置 → 遵循其 type/scope/长度限制。
- `.gitmessage` / commit 模板、`CONTRIBUTING`/`CHANGELOG` 的历史风格 → 对齐。
- `git log` 若普遍使用 gitmoji、特定 scope 词表或固定语言 → 沿用。
- 未探测到明确约定时，采用下方「Commit 规范」默认值。

### Step 3：检查暂存区

**暂存区为空则停止生成**，提示用户先自行暂存：

```markdown
## 暂存区为空

当前没有 `git add` 的内容。请先暂存本次要提交的改动，再让我生成文案：

    git add <path>        # 或用 IDE 的「源代码管理 → 暂存更改」

一次提交对应一个逻辑改动。暂存完成后再说「生成 commit 文案」即可。
```

暂存区有内容则继续，并做**遗漏 / 风险检查**（只提示，不自动处理）：

| 检查项 | 处理 |
|---|---|
| `git diff` 有相关改动但未 staged | 列出未暂存文件，提示「是否遗漏 / 是否属于本次提交」 |
| 同一逻辑只暂存了部分文件 | 提醒可能不完整（如改了公共模块却漏 add 引用方） |
| staged 含构建产物 / 生成物 / 依赖目录（如 `dist/`、`build/`、`node_modules/`、编译输出） | **警告**：通常不应提交，建议 `git restore --staged <path>` |
| staged 含 `.env*` / 密钥 / token / 凭证 / `*.local.*` | **警告**：不应提交，建议撤出暂存 |
| staged 含注释掉的校验、本地 bypass、调试 `console.log` / `print` / `debugger` | 在「风险提示」列出，建议不要进 commit |

### Step 4：判断是否需要拆分

阅读**全部** staged diff，归纳「做了什么、为什么」。若已暂存内容包含**多个互不相关的逻辑主题**（如「修 bug」+「无关重构」+「改文档」混在一起）：

- **主动建议拆分成多个 commit**，为每个主题各给一条 message，并给出各自的 `git add`/`git reset` 分组建议（供用户参考，不自动执行）。
- 若为单一主题，直接给一条 message。

### Step 5：起草 message（见下方规范），按固定模板输出

## 输出模板

```markdown
## 暂存范围
- `path/a`（新增/修改/删除）— 一句话摘要
- ...

## 提示（无则省略本节）
- ⚠️ 未暂存：`path/x` — 与本次改动相关，可能遗漏
- ⚠️ 风险：`dist/...` 疑似构建产物 / 含调试代码 / `.env` 等，建议撤出暂存

## 建议 commit message
（若建议拆分，则按主题分别给出多组「建议 message + 提交命令」）

【可直接复制】
\`\`\`
<type>(<scope 可选>): <中文 subject>

<body 可选：2-4 条 bullet，说明行为变化与动机>

<footer 可选：BREAKING CHANGE / Closes #123>
\`\`\`

**类型/范围说明：** 一句话解释为何选该 type、scope。

## 提交命令（需用户自行执行，Agent 默认不提交）

bash / zsh：
\`\`\`bash
git commit -m "$(cat <<'EOF'
<完整 message>
EOF
)"
\`\`\`

PowerShell：
\`\`\`powershell
@'
<完整 message>
'@ | Set-Content -Encoding utf8 .git\COMMIT_MSG.tmp; git commit -F .git\COMMIT_MSG.tmp; Remove-Item .git\COMMIT_MSG.tmp
\`\`\`

或先写入文件再提交（跨平台通用）：`git commit -F <消息文件>`
```

## Commit 规范（默认值）

格式：`type(scope): subject`，可选 body 与 footer。**scope 可选**。

### type（完整集合）

| type | 场景 |
|---|---|
| `feat` | 新功能 / 新页面 / 新接口对接（**新增与功能迭代都归 feat，不额外区分**） |
| `fix` | 修复 bug、回归、渲染/鉴权/请求等问题 |
| `docs` | 仅文档 |
| `style` | **仅代码格式**（空格、分号、格式化），不改逻辑。**注意：UI/页面视觉改动不是 `style`，按效果归 `feat` 或 `fix`** |
| `refactor` | 行为不变的结构调整、删旧链路 |
| `perf` | 性能优化 |
| `test` | 新增或调整测试 |
| `build` | 构建系统或外部依赖（打包工具、依赖版本、Dockerfile 等） |
| `ci` | CI 配置与脚本（workflow、流水线等） |
| `chore` | 杂项：脚本、工具链、配置、`.cursor` 规则等（不属于以上类别） |
| `revert` | 回滚某次提交 |

> 环境变量 / 构建工具配置变更：影响构建/依赖用 `build`，属 CI 配置用 `ci`，其余杂项配置用 `chore`——按实际归属选择，不要一律塞 `chore`。

### scope

- **可选**。需要时从改动路径自适应推断（如顶层目录名、包名、受影响模块），取「文件最多或最能代表本次改动核心」的区域。
- 无明显单一区域或改动分散时可省略 scope。

### subject

- **固定中文**，技术术语可保留英文。
- 1 行、尽量 ≤72 字，说**目的 / 解决什么问题**，而非罗列文件名。
- 禁止空洞：`修改`、`更新`、`fix bug`、`优化代码`。
- 与本仓库近期 `git log` 的措辞风格保持一致。

### body（可选）

- 用 bullet 说明**用户/行为可感知的变化与动机**（为什么这么做），而非逐个列文件。
- 单文件、单一主题可省略 body。

### footer（可选）

- 破坏性变更：type 后加 `!`（如 `feat!:`）**并**在 footer 写 `BREAKING CHANGE: <说明>`。
- 关联工单：`Closes #123` / `Refs #123`（按仓库习惯）。

## 示例

```
feat(auth): 登录支持手机号验证码，替换旧密码流程

- 新增验证码发送与校验接口对接
- 登录页去掉密码输入，改为验证码优先
```

```
fix(list): 列表请求失败后延迟重试，避免连续触发

- 首次失败后退避 1s 再试，最多 3 次
```

```
build(deps): 升级构建工具链至新大版本

- 迁移打包配置，移除已废弃选项

BREAKING CHANGE: 最低 Node 版本要求提升，需重装依赖
```

```
refactor: 抽离公共请求封装，移除各页面重复拦截逻辑
```

## 输出前自检

```
□ 已确认 staged 非空；为空则只提示、不杜撰 message
□ message 仅描述 git diff --cached 中的内容
□ 未暂存的相关文件已在「提示」中列出
□ 多主题已建议拆分并各给 message
□ type 归类正确（构建/CI/样式语义无误，UI 视觉未误标为 style）
□ subject 为中文、非空、非「修改/更新」
□ 破坏性变更已加 `!` 与 BREAKING CHANGE
□ 未擅自 git add / git commit
```
