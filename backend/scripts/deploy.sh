#!/usr/bin/env bash
# 日常发版：备份库 → 迁移 → 装依赖 → 构建前端 →（可选）重启 API。
# 用法（项目根）：
#   ./backend/scripts/deploy.sh
#   DEPLOY_GIT_PULL=1 ./backend/scripts/deploy.sh          # 先 git pull
#   DEPLOY_RESTART_CMD='supervisorctl restart byd-api' ./backend/scripts/deploy.sh
#
# 注意：勿用本机空 data/ 覆盖服务器；本脚本不触碰 data/、backups/。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
else
  echo "[deploy] 缺少 .venv，请先：python3 -m venv .venv && pip install -r requirements.txt" >&2
  exit 1
fi

mkdir -p logs backups/db data

if [[ "${DEPLOY_GIT_PULL:-0}" == "1" ]]; then
  echo "[deploy] git pull…"
  git pull --ff-only
fi

echo "[deploy] pre_deploy（备份 + migrate）…"
./backend/scripts/pre_deploy.sh

echo "[deploy] pip install…"
pip install -r requirements.txt -q

if command -v npm >/dev/null 2>&1; then
  echo "[deploy] 构建前端…"
  (
    cd frontend
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
    npm run build
  )
else
  echo "[deploy] 未找到 npm，跳过前端构建（请本机构建后同步 frontend/dist）" >&2
fi

if [[ -n "${DEPLOY_RESTART_CMD:-}" ]]; then
  echo "[deploy] 重启：${DEPLOY_RESTART_CMD}"
  # shellcheck disable=SC2086
  eval ${DEPLOY_RESTART_CMD}
else
  echo "[deploy] 未设置 DEPLOY_RESTART_CMD；请手动重启 Supervisor / uvicorn。"
  echo "         例：DEPLOY_RESTART_CMD='supervisorctl restart byd-api' ./backend/scripts/deploy.sh"
fi

echo "[deploy] schema_version=$(python -m backend.src.db version)"
echo "[deploy] 健康检查：curl -s http://127.0.0.1:8000/zq/api/health"
echo "[deploy] done."
