"""路径与运行配置：统一从项目根目录解析 data/backups/.env。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/config.py → 上两级为仓库根
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """可由 .env / 环境变量覆盖；生产 ECS 建议写绝对路径。"""

    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = ROOT_DIR / "data"
    backup_dir: Path = ROOT_DIR / "backups"
    db_path: Path = ROOT_DIR / "data" / "archive.db"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # 单域名子路径部署，如 /zq；空或 / 表示挂在域名根
    base_path: str = "/zq"
    http_timeout: float = 30.0
    # 生产建议 Nginx 白名单为主；True 时 FastAPI 再读同一份 ops/allowed_ips.conf 兜底
    ip_whitelist_enabled: bool = False
    ip_whitelist_path: Path = ROOT_DIR / "ops" / "allowed_ips.conf"
    # 手动同步频控（秒）：防东财限流；CLI 计划任务不受 evaluate_sync 约束
    sync_cooldown_seconds: int = 120
    sync_ok_reuse_seconds: int = 600
    sync_batch_gap_seconds: float = 2.0
    sync_request_gap_seconds: float = 0.4


settings = Settings()


def ensure_dirs() -> None:
    """幂等创建数据、备份、日志目录，避免首次运行因缺目录失败。"""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.backup_dir / "raw").mkdir(parents=True, exist_ok=True)
    (settings.backup_dir / "db").mkdir(parents=True, exist_ok=True)
    (ROOT_DIR / "logs").mkdir(parents=True, exist_ok=True)
