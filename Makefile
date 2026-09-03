# 快捷运维命令（在项目根执行 make <target>）
# 生产目录示例：/www/wwwroot/bc-zq

.PHONY: help bootstrap deploy pre-deploy sync sync-one sync-margin frontend-build api health version

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

help:
	@echo "常用目标："
	@echo "  make bootstrap       # 首次：venv + 依赖 + .env + 建库"
	@echo "  make deploy          # 发版：备份/迁移 + pip + 前端 build"
	@echo "  make pre-deploy      # 仅备份库 + schema migrate"
	@echo "  make sync            # 收盘同步分时（全部 enabled）并备份 DB"
	@echo "  make sync-one CODE=002594  # 同步单只分时"
	@echo "  make sync-margin     # 仅同步两融（计划任务 10:10）"
	@echo "  make frontend-build  # 仅构建前端"
	@echo "  make api             # 前台启动 uvicorn（开发/临时）"
	@echo "  make health          # 本机健康检查"
	@echo "  make version         # 打印 schema 版本"
	@echo ""
	@echo "发版可选环境变量（传给脚本）："
	@echo "  DEPLOY_GIT_PULL=1 make deploy"
	@echo "  DEPLOY_RESTART_CMD='supervisorctl restart byd-api' make deploy"

# 首次上机：环境与空库（不拉行情；交易日再 make sync）
# 需要系统 python3 ≥ 3.10；旧系统自带 pip 9.x 装不上现代 fastapi
bootstrap:
	@python3 -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python ≥ 3.10，当前: %s；请用宝塔安装 3.10+ 后再执行" % sys.version.split()[0]'
	@test -d $(ROOT)/.venv || python3 -m venv $(ROOT)/.venv
	$(ROOT)/.venv/bin/pip install -U pip setuptools wheel
	$(ROOT)/.venv/bin/pip install -r $(ROOT)/requirements.txt
	@test -f $(ROOT)/.env || cp $(ROOT)/.env.example $(ROOT)/.env
	@test -f $(ROOT)/ops/allowed_ips.conf || cp $(ROOT)/ops/allowed_ips.conf.example $(ROOT)/ops/allowed_ips.conf
	@mkdir -p $(ROOT)/logs $(ROOT)/backups/db $(ROOT)/data
	cd $(ROOT) && $(ROOT)/.venv/bin/python -m backend.src.db init
	@echo "[bootstrap] 完成。请编辑 .env 与 ops/allowed_ips.conf，再配置 Supervisor + Nginx。"

# 环境变量由调用方导出后自然继承，勿在此拆 DEPLOY_RESTART_CMD（含空格）
deploy:
	$(ROOT)/backend/scripts/deploy.sh

pre-deploy:
	$(ROOT)/backend/scripts/pre_deploy.sh

sync:
	$(ROOT)/backend/scripts/sync_today.sh

sync-one:
	@test -n "$(CODE)" || (echo "用法: make sync-one CODE=002594" >&2; exit 1)
	cd $(ROOT) && $(ROOT)/.venv/bin/python -m backend.src.sync --code $(CODE) --backup

# 两融独立任务（生产建议宝塔每天 10:10）
sync-margin:
	$(ROOT)/backend/scripts/sync_margin.sh

frontend-build:
	cd $(ROOT)/frontend && npm ci && npm run build

# workers=1：SQLite 避免多进程写锁
api:
	cd $(ROOT) && $(ROOT)/.venv/bin/uvicorn backend.src.api:app --host 127.0.0.1 --port 8000 --workers 1

health:
	curl -sS http://127.0.0.1:8000/zq/api/health; echo

version:
	cd $(ROOT) && $(ROOT)/.venv/bin/python -m backend.src.db version
