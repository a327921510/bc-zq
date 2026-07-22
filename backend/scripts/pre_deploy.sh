#!/usr/bin/env bash
# 发版前：备份 SQLite（带时间戳，不覆盖）→ 跑 schema 迁移。
# 用法：在项目根执行 ./backend/scripts/pre_deploy.sh
# 注意：不要用本机空库覆盖服务器 data/；本脚本只备份与迁移现有库。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi
mkdir -p logs backups/db data

echo "[pre_deploy] backup…"
python -m backend.src.db backup --tag pre_deploy

echo "[pre_deploy] migrate…"
python -m backend.src.db migrate

echo "[pre_deploy] schema_version=$(python -m backend.src.db version)"
echo "[pre_deploy] done. 然后更新代码依赖并重启 uvicorn/Supervisor。"
