# 比亚迪分时复盘归档（byd-intraday-archive）

> 目标：把券商软件「当日分时页」冻成快照，收盘后本地长期保存，随时按交易日回看。  
> 粒度：**A 档**——与免费行情软件一致的分笔/几秒级成交明细（非 Level-2 逐笔）。


## 一、要解决什么问题

券商客户端对个股「当日」通常展示：

- 分时价格线（约 9:30–11:30、13:00–15:00）
- 分时成交量柱
- 成交明细列表（时间 / 价 / 量 / 方向）
- 分价表（按价位汇总成交量）

过了当天（或仅保留近约 5 日），这些界面级数据会被收掉或合并，无法再按「当日页」复盘。  
本项目只做一件事：**每日收盘后把上述内容入库，并提供本地回放页。**

不做：实时行情、Level-2 逐笔、全市场量化库、复杂策略回测框架。


## 二、产品范围

| 项 | 约定 |
|----|------|
| 标的 | 首发：比亚迪 `002594.SZ`；后续可配置多只 |
| 更新时机 | 交易日收盘后（建议 ≥ 15:30，稳妥可用 16:00） |
| 明细粒度 | **A**：分笔/几秒汇总明细（买盘/卖盘/中性），对齐免费版成交明细 |
| 分时图 | 由明细聚合为 1 分钟点，或接口直接给 1 分钟；休市中间不断线连接 |
| 分价表 | 由当日明细 `GROUP BY price` 聚合，不单独采集 |
| 查看方式 | Web 回放页：选日期 → 复刻分时页 |
| 开发机 | macOS / Linux 本地开发与联调 |
| 生产部署 | **阿里云 ECS + 宝塔面板**（前后端同机或分目录部署） |

**非目标**

- 盘中实时刷新
- 通达信全市场日线/板块库（如 tdx2db）
- 付费 Level-2 逐笔


## 三、数据模型（够画券商当日页即可）

### 3.1 表结构（SQLite）

```sql
-- 关注股票
CREATE TABLE symbols (
  code       TEXT PRIMARY KEY,   -- 002594
  name       TEXT NOT NULL,      -- 比亚迪
  market     TEXT NOT NULL,      -- SZ / SH
  enabled    INTEGER DEFAULT 1
);

-- 日摘要（顶部行情条）
CREATE TABLE daily_summary (
  code         TEXT NOT NULL,
  trade_date   TEXT NOT NULL,    -- YYYY-MM-DD
  pre_close    REAL,
  open         REAL,
  high         REAL,
  low          REAL,
  close        REAL,
  volume       REAL,             -- 手或股，入库时统一并写清单位
  amount       REAL,             -- 元
  PRIMARY KEY (code, trade_date)
);

-- 成交明细（核心，A 档分笔）
CREATE TABLE ticks (
  code         TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  seq          INTEGER NOT NULL, -- 当日顺序号，保证稳定排序
  time         TEXT NOT NULL,    -- HH:MM:SS
  price        REAL NOT NULL,
  volume       REAL NOT NULL,    -- 与 daily 统一单位
  amount       REAL,
  side         TEXT,             -- B / S / N（买/卖/中性）
  PRIMARY KEY (code, trade_date, seq)
);

-- 1 分钟分时点（画图用；可由 ticks 聚合，也可接口直写）
CREATE TABLE minutes (
  code         TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  minute       TEXT NOT NULL,    -- HH:MM（交易分钟）
  price        REAL NOT NULL,    -- 该分钟末价 / 均价，与券商分时线对齐时固定一种算法
  volume       REAL NOT NULL,
  amount       REAL,
  PRIMARY KEY (code, trade_date, minute)
);

-- 同步日志
CREATE TABLE sync_log (
  code         TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  status       TEXT NOT NULL,    -- ok / fail / partial
  tick_count   INTEGER,
  minute_count INTEGER,
  message      TEXT,
  synced_at    TEXT NOT NULL,
  PRIMARY KEY (code, trade_date)
);
```

### 3.2 派生：分价（查询即可，可不落表）

```sql
SELECT price, SUM(volume) AS volume
FROM ticks
WHERE code = '002594' AND trade_date = '2026-07-21'
GROUP BY price
ORDER BY price;
```

若回放页查询频繁，可在同步成功后物化一张 `price_volume` 表，逻辑同上。


## 四、系统架构

```
                    ┌──────────────────────────────────┐
                    │  阿里云 ECS（宝塔面板）              │
                    │  时区：Asia/Shanghai               │
                    └──────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│ 宝塔计划任务      │         │ 后端 API         │         │ Nginx（宝塔站点） │
│ 交易日 16:00     │         │ FastAPI/uvicorn  │◄────────│ 前端静态 + 反代   │
│ 跑 sync 拉东财   │────────►│ :8000（内网）     │         │ 80 对外（HTTP）  │
└─────────────────┘         └────────┬────────┘         └─────────────────┘
                                     ▼
                            ┌─────────────────┐
                            │ SQLite + raw 备份 │
                            │ /www/wwwroot/... │
                            └─────────────────┘
```

数据流不变：收盘同步 → 入库 → Web 回放（选股/选日看分时、量、明细、分价）。


## 五、数据源约定（A 档）— 已实测（2026-07-21，标的 002594）

原则：**每个交易日收盘后、数据还在「当日」窗口时拉全天**，本地永久保存。免费源**不能**按任意历史日期回补成交明细。

### 5.1 可行性结论

| 需求 | 免费源能否实现 | 说明 |
|------|----------------|------|
| 当日分时价+量（1 分钟） | ✅ 能 | 东财 `trends2` 当日约 240 点；`ndays=5` 可取近 5 日（与券商窗口同量级） |
| 当日成交明细（A 档分笔） | ✅ 能 | 东财 `details` 当日可一次取全天（实测约 4700+ 条，含时间/价/量/方向） |
| 任意历史日的成交明细 | ❌ 不能 | `date=` 参数无效，始终返回当日；无可靠免费历史分笔 |
| 任意历史日的 1 分钟 | ❌ 基本不能 | 东财 1 分钟 K 的 `beg/end` 实测被忽略，只回当日；新浪约 5 日窗口 |
| 分价表 | ✅ 能（派生） | 有当日 `ticks` 即可 `GROUP BY price` |

**结论：不需要为「从今天起往后存」另找付费源。**  
必须换/加源的情况只有：① 要回补启用日之前的明细；② 东财接口长期失效；③ 不能接受漏跑一天就永远缺那天明细。

### 5.2 推荐主源（直接 HTTP，不必依赖 akshare 历史分笔）

| 数据 | 接口 | 注意 |
|------|------|------|
| 成交明细 | `https://push2.eastmoney.com/api/qt/stock/details/get?secid=0.002594&pos=0&mpi=2000&...` | **仅当日**；收盘后尽快拉；字段形如 `时间,价,量,笔数?,方向` |
| 1 分钟分时 | `https://push2.eastmoney.com/api/qt/stock/trends2/get?secid=0.002594&ndays=1&...` | 当日完整分时；历史最多再用 `push2his` + `ndays=5` 补近 5 日分钟 |
| 日摘要 | 东财日线 / 行情接口 | 开高低收、昨收 |

**不要依赖**：akshare `stock_zh_a_tick_tx` / 腾讯历史分笔下载（接口长期不稳定或已失效，不能当主路径）。

### 5.3 实现约束

1. 同步窗口：建议交易日 **15:15–16:30**；错过且跨到下一交易日，当日明细通常无法再从免费源取回。
2. 字段映射写死在适配器（`side` → B/S/N）。
3. 先写 `backups/raw/{code}/{trade_date}.json`，再入库。
4. 同日幂等覆盖；失败写 `sync_log` 并告警。
5. 启用时可用 `trends2&ndays=5` **一次性**回填近 5 日分钟线；明细仍只能从启用日起逐日攒。
6. 若日后要「补很久以前的明细」，再评估付费源（掘金/Tushare 等），不阻塞 P0。


## 六、分时线怎么画（与券商对齐）

交易时段（主板连续竞价）：

- 上午：`09:30`–`11:30`
- 下午：`13:00`–`15:00`
- 中间休市：**断开**，不要用直线把 11:30 连到 13:00

分钟点生成（推荐）：

1. 优先用接口返回的 1 分钟分时（若有且与软件一致）。
2. 否则用 `ticks`：每个交易分钟取**该分钟最后一笔价**为 `price`，`SUM(volume)` 为 `volume`。
3. 无成交的分钟：价沿用上一分钟价，量记 `0`（或按券商习惯处理，项目内固定一种）。

日摘要：开高低收、昨收尽量用官方日线字段，避免仅从分笔推算误差。


## 七、回放页（最小 UI）

一页即可，布局对齐券商当日页：

```
[股票选择] [交易日选择] [上一交易日] [下一交易日] [刷新] [同步与股票]

┌──────────────────────────────┬─────────────┐
│  分时价格线                   │  分价表      │
│  （9:30–15:00，休市断开）      │  价 | 量     │
├──────────────────────────────┤             │
│  分时成交量柱                 │             │
└──────────────────────────────┴─────────────┘
┌────────────────────────────────────────────┐
│  成交明细（可滚动）：时间 价 量 方向          │
└────────────────────────────────────────────┘
```

「同步与股票」侧栏：手动同步当前/全部、增删关注股、查看 sync 历史。  
相关 API：`POST /api/sync`、`GET /api/sync/logs`、`POST|PATCH|DELETE /api/symbols`。

技术建议（生产按前后端分离，便于宝塔部署）：

| 层 | 推荐 | 说明 |
|----|------|------|
| 后端 | FastAPI + uvicorn | 回放 API + 关注股管理 + 手动同步 |
| 前端 | 静态 HTML/Vue/React 构建产物 | Nginx 托管；图表可用 ECharts |
| 开发联调 | 本机 `uvicorn` + 前端 dev server | 与生产同 API 契约 |

个人自用访问控制采用 **Nginx IP 白名单**（见第九节 9.5a）：只有名单内公网 IP 能打开页面与 API；开通时在宝塔改 `ops/allowed_ips.conf` 后重载 Nginx 即可。


## 八、项目结构（建议）

```
project/
├── init.md
├── README.md
├── .env.example
├── requirements.txt
├── data/
│   └── archive.db
├── backups/
│   ├── raw/
│   └── db/
├── ops/                     # 运维：IP 白名单 + Nginx 片段
│   ├── allowed_ips.conf.example
│   ├── allowed_ips.conf     # 生产实文件（gitignore，部署时从 example 复制）
│   ├── nginx-site.snippet.conf
│   └── robots.txt
├── backend/                 # 后端（API + sync）
│   ├── src/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── fetch/eastmoney.py
│   │   ├── aggregate.py
│   │   ├── sync.py
│   │   ├── ip_whitelist.py  # 可选：与 Nginx 同文件的应用层兜底
│   │   └── api.py           # FastAPI 入口
│   └── scripts/
│       ├── sync_today.sh    # 宝塔计划任务入口
│       ├── pre_deploy.sh    # 发版前备份 + migrate
│       └── deploy.sh        # 一键发版（备份→依赖→前端）
├── Makefile                 # make bootstrap / deploy / sync …
├── frontend/                # 前端
│   ├── dist/                # 构建产物（gitignore；服务器上 npm run build）
│   └── ...
└── logs/
    └── sync.log
```

ECS 上建议目录（与宝塔习惯对齐）：

```
/www/wwwroot/bc-zq/
├── backend/
├── frontend/dist/           # 或单独站点根目录
├── ops/                     # allowed_ips.conf + robots.txt
├── data/
├── backups/
├── logs/
├── .venv/                   # Python 虚拟环境
└── .env
```


## 九、阿里云 ECS + 宝塔面板部署

> 目标：同机部署「每日同步任务 + 后端 API + 前端回放页」。以下为运维约定，编码 AI 实现时需保证可按此上线。  
> **给不懂技术的同事逐步操作**：见 [`ops/上线与发版手册.md`](ops/上线与发版手册.md)（首日上线 + 日常发版）。

### 9.1 云资源与安全组

1. 购买 ECS（建议：2 核 2G 起，系统盘 ≥ 40G；系统选 CentOS / Ubuntu / Alibaba Cloud Linux）。
2. **时区必须为 `Asia/Shanghai`**（A 股收盘与 cron 依赖此时区）：

```bash
timedatectl set-timezone Asia/Shanghai
timedatectl   # 确认
```

3. 安全组放行：
   - `22`（SSH，建议仅自己的 IP）
   - `80`（HTTP Web；浏览器访问 `http://ECS公网IP/zq/`）
   - **不要**对公网放行 `8000`（API 只给本机 Nginx 反代）

### 9.2 安装宝塔面板

按[宝塔官网](https://www.bt.cn)文档安装对应系统脚本，安装后：

1. 登录面板 → 安装 **Nginx**、**Python 项目管理器**（或仅用系统 Python 3.10+）。
2. 不必强依赖 MySQL：本项目默认 **SQLite**。
3. 面板「安全」中修改默认入口、绑定面板 SSL、限制面板 IP（可选但推荐）。

### 9.3 上传代码与 Python 环境

1. 宝塔 → 文件 → 创建 `/www/wwwroot/bc-zq/`，上传或 `git clone` 项目。
2. SSH 进入目录创建虚拟环境并安装依赖：

```bash
cd /www/wwwroot/bc-zq
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

3. 复制 `.env.example` → `.env`，至少配置：

```ini
DATA_DIR=/www/wwwroot/bc-zq/data
BACKUP_DIR=/www/wwwroot/bc-zq/backups
DB_PATH=/www/wwwroot/bc-zq/data/archive.db
API_HOST=127.0.0.1
API_PORT=8000
# 可选：FastAPI 再读同一白名单文件作兜底（Nginx 仍是主门禁）
IP_WHITELIST_ENABLED=false
IP_WHITELIST_PATH=/www/wwwroot/bc-zq/ops/allowed_ips.conf
```

4. 初始化库：

```bash
source .venv/bin/activate
python -m backend.src.db init
python -m backend.src.sync --code 002594   # 若当日为交易日
```

### 9.4 后端：常驻 API（Supervisor / 宝塔进程守护）

推荐用宝塔「Supervisor 管理器」或「Python 项目」托管 uvicorn，保证开机自启。

启动命令示例：

```bash
/www/wwwroot/bc-zq/.venv/bin/uvicorn backend.src.api:app \
  --host 127.0.0.1 --port 8000 --workers 1
```

注意：

- `host` 绑 `127.0.0.1`，仅本机访问。
- SQLite 用 **1 worker**，避免多进程写库锁冲突（读多写少；写主要在 cron）。
- 进程用户建议与 Nginx/站点用户一致或可读 `data/`、`backups/`。

健康检查：本机 `curl http://127.0.0.1:8000/zq/api/health`。

### 9.5 前端：宝塔网站 + Nginx 反代

1. 宝塔 → 网站 → 添加站点：「域名」栏填 **ECS 公网 IP**。
2. 网站根目录指向前端构建产物，例如：`/www/wwwroot/bc-zq/frontend/dist`。
3. 站点设置 → 配置文件：参考仓库 `ops/nginx-site.snippet.conf`，至少包含 **IP 白名单 include** + `/zq/` 反代（路径按 ECS 实际目录改）：

```nginx
# 整站门禁：未在名单内的公网 IP → 403
include /www/wwwroot/bc-zq/ops/allowed_ips.conf;

location = /robots.txt {
    root /www/wwwroot/bc-zq/ops;
    default_type text/plain;
}

location = /zq {
    return 301 /zq/;
}

location ^~ /zq/ {
    proxy_pass http://127.0.0.1:8000/zq/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
}
```

4. **访问控制以 IP 白名单为准**（见下节 9.5a），不要依赖「密码访问」作为主方案。  
   Nginx 的 `/zq/` 须写成 `location ^~ /zq/`，否则宝塔默认的 js/css 正则可能抢走静态资源导致 404。

前端构建（在开发机或 ECS 上）：

```bash
cd frontend && npm ci && npm run build
# 将 dist/ 同步到网站根目录（若 Nginx 由后端托管静态则可省略单独站点根）
```

### 9.5a IP 白名单（主访问控制）

> 目标：只有你维护的公网 IP 能打开回放页与 API；开通/收回用宝塔改一个文件即可。

**首次部署**

```bash
cd /www/wwwroot/bc-zq
cp ops/allowed_ips.conf.example ops/allowed_ips.conf
# 编辑 allowed_ips.conf：把 allow 行改成你当前公网 IP，保留末尾 deny all;
```

`ops/allowed_ips.conf` 示例：

```nginx
# 家宽出口
allow 1.2.3.4;
# 公司出口（可选多行）
# allow 5.6.7.8;

deny all;
```

站点 Nginx 配置里必须有：

```nginx
include /www/wwwroot/bc-zq/ops/allowed_ips.conf;
```

保存站点配置后 **重载 Nginx**。未在名单内的访问返回 **403**。

**日常开通（换网络 / 新 IP）**

1. 在待访问设备上查公网 IP：浏览器打开 https://ip.sb 或 https://ifconfig.me  
2. 宝塔 → **文件** → `/www/wwwroot/bc-zq/ops/allowed_ips.conf`  
3. 增加一行：`allow 你的IP;`（旧 IP 可注释掉，勿删 `deny all;`）  
4. 保存 → 宝塔 Nginx **重载**（或「软件商店 → Nginx → 重载」）  
5. 用该网络打开站点验证；不需要改业务代码、不必重启 uvicorn（Nginx 门禁即时生效）

**可选应用层兜底**

- `.env` 设 `IP_WHITELIST_ENABLED=true`，FastAPI 读取**同一份** `ops/allowed_ips.conf`。  
- 仅当请求经本机 Nginx 反代时信任 `X-Real-IP`；名单文件变更后下次请求自动重载，无需重启进程。  
- 主防线仍是 Nginx；8000 继续只绑 `127.0.0.1`。

**注意**

| 项 | 说明 |
|----|------|
| 认公网 IP | 不要写局域网 `192.168.x.x` |
| 家宽 / 手机流量常变 | IP 变了就按上面步骤改文件；用完可注释掉临时行 |
| 别把自己锁死 | 改名单前确认宝塔面板仍可进；可先从面板所在网络的 IP 写进白名单 |
| 防爬 | `ops/robots.txt` 全站 `Disallow`；真正挡爬靠白名单 403 |

### 9.6 宝塔计划任务（每日收盘同步）— 最关键

宝塔 → 计划任务 → 添加：

| 项 | 建议值 |
|----|--------|
| 任务类型 | Shell 脚本 |
| 任务名称 | bc-zq-sync |
| 执行周期 | 每天 `16:00`（或 `15:30`；仅需交易日生效时可在脚本内判断） |
| 脚本内容 | 见下 |

```bash
#!/bin/bash
# 推荐直接调仓库脚本（内部 --all-enabled --backup，日志写 logs/sync.log）
/www/wwwroot/bc-zq/backend/scripts/sync_today.sh
```

要点：

1. 计划任务时区随系统；已设 `Asia/Shanghai` 才能对准 A 股收盘。
2. 打开宝塔任务「保存日志」，失败可在面板查看。
3. 可加第二条任务：每周清理过旧的 `backups/db/`（保留近 N 份）。
4. 首次上线后，下一交易日人工确认 `sync_log` 与回放页有新数据。

### 9.7 磁盘、备份、迁移与发版

| 项 | 建议 |
|----|------|
| 数据目录 | `data/`、`backups/` **永不**被发版覆盖；与代码目录可同机但勿整包上传冲掉 |
| 宝塔备份 | 开启网站/目录备份；核心是 **SQLite + raw JSON** |
| schema 版本 | 表 `schema_meta.version`；启动时 `init_db`→`migrate` 只向前升级，禁止删库重建 |
| 告警 | sync 失败写日志；可选 webhook（P2） |

**发版标准流程（防丢数据）**

```bash
cd /www/wwwroot/bc-zq
# 一键：备份+migrate → pip → 前端 build →（可选）重启
DEPLOY_GIT_PULL=1 \
DEPLOY_RESTART_CMD='supervisorctl restart byd-api' \
  make deploy
# 等价拆步：./backend/scripts/pre_deploy.sh → pip / npm build → 重启 Supervisor
```

新增表字段时：在 `backend/src/db.py` 的 `MIGRATIONS` 增加下一版本函数（通常 `ALTER TABLE … ADD COLUMN`），并把 `TARGET_SCHEMA_VERSION` +1；**不要**删 `archive.db`。

回滚库：从 `backups/db/archive_pre_deploy_*.db` 拷回 `data/archive.db`（先停 API）。

### 9.8 部署验收清单

- [ ] `timedatectl` 为上海时区
- [ ] 已从 `ops/allowed_ips.conf.example` 复制并配置 `ops/allowed_ips.conf`
- [ ] 站点 Nginx 已 `include` 白名单文件并重载
- [ ] 白名单内 IP 可打开回放页；名单外 IP 访问为 403
- [ ] `/zq/api/health` 经 Nginx 可访问（`http://ECS公网IP/zq/api/health`，非直接 8000）；名单外同样 403
- [ ] `python -m backend.src.db version` 输出 ≥ 1
- [ ] 手动执行一次 `pre_deploy.sh` 或 sync 脚本成功，`backups/db/` 有文件
- [ ] 宝塔计划任务列表中能看到 16:00 任务
- [ ] `data/archive.db` 与 `backups/raw/` 有当日文件
- [ ] 安全组未对公网开放 8000
- [ ] 发版约定：先 `pre_deploy.sh`，且不同步覆盖 `data/`


## 十、每日流程

### 10.1 首次（本机或 ECS）

```bash
# 1. 建库、写入 symbols（002594 比亚迪）
python -m backend.src.db init

# 2. 同步最近一个交易日（验证链路）
python -m backend.src.sync --code 002594 --date 2026-07-21

# 3. 启动 API，打开前端，目视与券商当日页对照
uvicorn backend.src.api:app --host 127.0.0.1 --port 8000
```

验收标准（与券商同日对比）：

- [ ] 分时走势形态大体一致（允许免费源与券商之间轻微差异）
- [ ] 成交量柱高峰位置一致
- [ ] 明细条数同量级，方向分布合理
- [ ] 分价高低价区量能分布一致

### 10.2 每日增量

```bash
# 交易日 16:00（生产用宝塔计划任务，见第九节）
python -m backend.src.sync --all-enabled
cp -a data/archive.db backups/db/archive_$(date +%Y%m%d).db
```

本机 cron 示例（开发用；**生产以宝塔计划任务为准**）：

```bash
0 16 * * 1-5 cd /path/to/project && ./backend/scripts/sync_today.sh >> logs/sync.log 2>&1
```


## 十一、风险与对策

| 风险 | 对策 |
|------|------|
| 免费接口改版 / 限流 | 原始 JSON 备份；适配器可替换；失败进 sync_log |
| 漏跑一天 | 宝塔计划任务 + 日志告警；支持补跑；分钟/明细无法从日线反推 |
| ECS 时区不是上海 | 部署清单强制 `Asia/Shanghai`，否则 16:00 任务错位 |
| API 公网裸奔 | 只监听 127.0.0.1；Nginx 反代 + `ops/allowed_ips.conf` IP 白名单 |
| 发版覆盖 / 改表丢数据 | `pre_deploy.sh` 先备份；`schema_meta`+migrate 向前升级；禁止删库重建 |
| SQLite 多进程写锁 | uvicorn workers=1；sync 与 API 错开重写窗口 |
| 与券商像素级不完全一致 | A 档免费源本身有差异；以「可复盘」为准 |
| 仅存比亚迪不够 | `symbols` 加行即可 |
| 误用 tdx2db 全市场方案 | 本项目不依赖 tdx2db |


## 十二、实现优先级

| 顺序 | 内容 | 完成定义 |
|------|------|----------|
| P0 | SQLite + 单日拉取入库（002594） | 库中有 ticks / minutes / daily_summary |
| P0 | 后端 API + 前端回放页 | 选日可看价、量、明细、分价 |
| P1 | 每日同步脚本 + raw/db 备份 | 本机 / ECS 均可跑通 |
| P1 | 宝塔部署 + Nginx IP 白名单 | 按第九节验收；名单外 403；改 `ops/allowed_ips.conf` 即可开通 |
| P2 | 失败告警、多股票 | 可扩展 |


## 十三、总结

| 问题 | 答案 |
|------|------|
| 存什么？ | A 档成交明细 + 1 分钟分时 + 日摘要；分价由明细聚合 |
| 何时存？ | 收盘后，非实时；生产用宝塔每天 16:00 任务 |
| 怎么看？ | Web 回放页；生产 ECS + 宝塔；仅白名单公网 IP 可访问 |
| 数据源？ | 东财当日接口；从启用日起逐日攒 |
| 和 tdx2db？ | 无关 |

确认本方案后，即可按 P0 → P1 开工实现。
