# 比亚迪分时复盘归档

收盘后从东财拉取个股当日分时 + 成交明细，本地 SQLite 归档，Web 回放。

## 快速开始（本机开发）

```bash
cd /path/to/bc-zq
make bootstrap                    # venv + 依赖 + .env + 建库
make sync-one CODE=002594         # 交易日拉一只样例
make frontend-build               # 或改 UI 后重建
make api                          # uvicorn :8000 workers=1
```

浏览器打开 http://127.0.0.1:8000/zq/  
前端开发联调：`cd frontend && npm run dev` → http://127.0.0.1:5173/zq/（`/zq/api` 代理到 `:8000`）。

等价手写命令见下方「Makefile 对照」。

**零基础上线 / 发版（逐步点宝塔）：请按 [`ops/上线与发版手册.md`](ops/上线与发版手册.md) 操作。**  
技术向细节见 `init.md` 第九节。

## 部署流程总览

同机部署：**每日同步 cron + FastAPI(uvicorn) + Nginx `/zq/` 反代**。数据在 `data/`、`backups/`，发版永不覆盖。

```text
首次上线                日常发版                 每日收盘
─────────              ─────────               ─────────
make bootstrap         make deploy             make sync
配置 .env / 白名单      （备份→依赖→前端）        （宝塔 16:00）
Supervisor 托管 API    重启 Supervisor
Nginx include 片段     make health
验收清单（init.md 9.8）
```

### 1）首次上线（ECS + 宝塔）

```bash
cd /www/wwwroot/bc-zq   # 或 git clone 后的项目根
make bootstrap
# 编辑 .env：DATA_DIR/DB_PATH/BASE_PATH=/zq 等用绝对路径
# 编辑 ops/allowed_ips.conf：allow 你的公网IP; … deny all;
```

| 步骤 | 做什么 |
|------|--------|
| Supervisor | 启动命令：`.venv/bin/uvicorn backend.src.api:app --host 127.0.0.1 --port 8000 --workers 1` |
| Nginx | 粘贴 `ops/nginx-site.snippet.conf`（`/zq/` → `:8000`），`include` 白名单 |
| 计划任务 | Shell，每天 16:00：`/www/wwwroot/bc-zq/backend/scripts/sync_today.sh` |
| 安全组 | 放行 **80**；**勿**对公网放行 8000 |

生产访问：`http://ECS公网IP/zq/`。Nginx 把 `/zq/` 反代到 uvicorn，`.env` 中 `BASE_PATH=/zq`。

### 2）日常发版（防丢库）

```bash
cd /www/wwwroot/bc-zq
# 推荐一键（可选先 pull、再重启）
DEPLOY_GIT_PULL=1 \
DEPLOY_RESTART_CMD='supervisorctl restart byd-api' \
  make deploy

# 仅备份 + migrate（不改代码时）
make pre-deploy
make version
make health   # → http://127.0.0.1:8000/zq/api/health
```

`make deploy` 顺序：`pre_deploy`（带时间戳备份 + migrate）→ `pip install` → `frontend` 构建 → 可选重启。  
**禁止**用本机空库 / 整包上传覆盖服务器 `data/`、`backups/`。

### 3）生产访问控制（IP 白名单）

公网以 **Nginx IP 白名单** 为主（`init.md` 9.5a）：

```bash
# bootstrap 已从 example 复制；否则：
cp ops/allowed_ips.conf.example ops/allowed_ips.conf
# 改 allow 行 → 宝塔站点 include → 重载 Nginx
```

日常开通：宝塔改 `ops/allowed_ips.conf` 增加 `allow 你的公网IP;`，重载 Nginx。  
可选：`.env` 设 `IP_WHITELIST_ENABLED=true`，FastAPI 读同一文件作兜底。

### Makefile 对照

| 命令 | 作用 |
|------|------|
| `make help` | 列出全部快捷目标 |
| `make bootstrap` | 首次环境 |
| `make deploy` | 发版全流程 |
| `make pre-deploy` | 仅备份 + migrate |
| `make sync` / `make sync-one CODE=…` | 收盘同步 |
| `make frontend-build` | 仅前端 |
| `make api` / `make health` / `make version` | 启 API / 探活 / schema |

脚本入口：`backend/scripts/deploy.sh`、`pre_deploy.sh`、`sync_today.sh`。

## 目录

- `backend/` API 与每日同步（含关注股增删、手动同步、同步历史）
- `backend/scripts/deploy.sh` 一键发版；`pre_deploy.sh` 备份 + 迁移；`sync_today.sh` 收盘任务
- `Makefile` 上述流程的快捷入口
- `frontend/` React + Ant Design；构建产物在 `frontend/dist/`（gitignore，服务器上 build）
- `ops/上线与发版手册.md` 首日上线 + 日常发版（零基础逐步操作）
- `ops/` Nginx 白名单片段、`robots.txt`
- `data/archive.db` SQLite（勿随发版覆盖）
- `backups/raw/` 原始 JSON；`backups/db/` 库备份
- `init.md` 完整方案（含宝塔部署与验收清单）

## 测试

```bash
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## 说明

- 成交明细接口仅返回**当前交易日**；需每日收盘后同步。
- 量单位：手；分价由明细聚合。
