# AGENTS.md

## Cursor Cloud specific instructions

本仓库是单一产品 `bc-zq`（比亚迪分时复盘归档）：FastAPI 后端 + React/Vite 前端 + 本地 SQLite 文件库（无独立 DB 进程）。标准命令见 `README.md` 与 `Makefile`（`make help`）。以下仅记录非显而易见的坑与澄清。

### 服务与运行
- 后端 API：`make api`（uvicorn `:8000`，`workers=1`）。健康检查在带前缀路径：`http://127.0.0.1:8000/zq/api/health`（`make health`）。
- 全站挂在 `BASE_PATH=/zq` 子路径下（`.env`），所以浏览器要开 `http://127.0.0.1:8000/zq/`，接口都是 `/zq/api/...`。
- 前端有两种运行方式，二选一：
  - 联调开发：`cd frontend && npm run dev` → `http://127.0.0.1:5173/zq/`，`/zq/api` 已代理到 `:8000`。
  - 经 API 同源访问：先 `make frontend-build`（产出 `frontend/dist/`，被 gitignore），API 才能在 `http://127.0.0.1:8000/zq/` 托管 UI。**构建步骤不在 update script 里**，需要经 API 看 UI 时手动跑一次。

### 数据与外部依赖（非显而易见）
- 行情来自东财公开 HTTP API，需**出站网络**。免费 `details` 接口**只返回「当前交易会话」**，无法按历史日期回补 —— 所以回放页只有你**实际同步过**的交易日才有数据。
- 拉数据的入口：UI「关注股票」页添加标的会 `sync_now` 立即同步当日；或 CLI `make sync-one CODE=002594` / `make sync`。
- 同步频控：同一标的有冷却（`SYNC_COOLDOWN_SECONDS` 等，见 `.env`），短时间重复会被 guard 跳过（`skipped`），前端可选 force 绕过。
- SQLite 单写：`make api` 固定 `workers=1`，勿加 workers 以免写锁冲突。库文件在 `data/archive.db`（gitignore），API 启动时会 `init_db()`（幂等）。

### 测试
- `.venv/bin/pytest -q`，纯单元测试，**不需要**网络或外部服务。
- 前端 typecheck 随 `npm run build`（`tsc --noEmit`）一起跑，无独立 lint 脚本。
