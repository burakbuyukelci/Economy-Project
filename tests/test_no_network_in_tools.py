"""CLAUDE.md kural 3: araçlar çalışma zamanında ağ kullanmaz. Ağ yalnızca scripts/ içinde."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = {"requests", "urllib", "urllib3", "http", "httpx", "aiohttp", "socket", "yfinance", "ftplib",
             "smtplib", "websocket", "websockets", "openai", "anthropic", "google"}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_tools_and_schemas_do_not_import_network_libraries():
    offenders = {}
    for folder in ("tools", "schemas", "config"):
        for py in (ROOT / folder).rglob("*.py"):
            bad = imported_roots(py) & FORBIDDEN
            if bad:
                offenders[str(py.relative_to(ROOT))] = sorted(bad)
    assert not offenders, offenders


def test_only_scripts_may_import_yfinance():
    assert "yfinance" in imported_roots(ROOT / "scripts" / "download_prices.py")
