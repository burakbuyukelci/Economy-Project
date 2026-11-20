"""tests/harness için ortak fixture'lar: THYAO 10.09.2026 GERÇEK araç zarfları (snapshot'tan, mock değil)."""
from __future__ import annotations

from pathlib import Path

import pytest

AS_OF = "2026-09-10"
SNAPSHOT_ROOT = Path(__file__).resolve().parents[2] / "data" / "snapshots"


@pytest.fixture(scope="session")
def thyao_history() -> dict:
    """Gerçek get_stock_history: THYAO 08–10.09.2026 (kapanışlar 305.0, 301.0, 299.25)."""
    if not (SNAPSHOT_ROOT / "LATEST").exists():
        pytest.skip("data/snapshots yok")
    from tools import get_stock_history

    env = get_stock_history.run({"ticker": "THYAO", "start": "2026-09-08", "end": AS_OF, "as_of": AS_OF})
    assert env["status"] == "OK"
    return env


@pytest.fixture(scope="session")
def thyao_indicators() -> dict:
    """Gerçek calculate_indicators: THYAO RSI + Bollinger + Supertrend, as_of 10.09.2026."""
    if not (SNAPSHOT_ROOT / "LATEST").exists():
        pytest.skip("data/snapshots yok")
    from tools import calculate_indicators

    env = calculate_indicators.run({"ticker": "THYAO", "indicators": ["RSI", "BOLLINGER", "SUPERTREND"],
                                    "end": AS_OF, "as_of": AS_OF})
    assert env["status"] == "OK"
    return env
