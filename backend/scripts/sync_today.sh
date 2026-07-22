#!/usr/bin/env bash
# 宝塔计划任务入口：交易日收盘后同步全部 enabled 标的并备份 DB
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi
mkdir -p logs backups/db data
python -m backend.src.sync --all-enabled --backup >> logs/sync.log 2>&1
