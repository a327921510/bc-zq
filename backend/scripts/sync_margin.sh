#!/usr/bin/env bash
# 宝塔计划任务入口：次日早上补拉两融（建议 10:10；交易所约 8:30–9:05 更新 T-1）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi
mkdir -p logs backups/db data
python -m backend.src.sync --all-enabled --margin-only >> logs/sync_margin.log 2>&1
