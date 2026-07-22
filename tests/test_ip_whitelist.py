"""IP 白名单解析与判定。"""

from __future__ import annotations

from pathlib import Path

from backend.src.ip_whitelist import client_ip_allowed, parse_allowed_networks


def test_parse_allow_lines_and_comments(tmp_path: Path) -> None:
    conf = tmp_path / "allowed_ips.conf"
    conf.write_text(
        "# home\n"
        "allow 1.2.3.4;\n"
        "allow 10.0.0.0/8;  # office\n"
        "deny all;\n"
        "not a valid line\n",
        encoding="utf-8",
    )
    nets = parse_allowed_networks(conf)
    assert len(nets) == 2
    assert client_ip_allowed("1.2.3.4", nets)
    assert client_ip_allowed("10.1.2.3", nets)
    assert not client_ip_allowed("8.8.8.8", nets)


def test_missing_file_means_deny_all(tmp_path: Path) -> None:
    nets = parse_allowed_networks(tmp_path / "missing.conf")
    assert nets == []
    assert not client_ip_allowed("1.2.3.4", nets)
