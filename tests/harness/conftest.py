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
    """Gerçek calculate_indicators: THYAO RSI + Bollinger + Supertrend, as_of 10.09.2026 (last_n_rows=5: 1.2.0 varsayılanı 0)."""
    if not (SNAPSHOT_ROOT / "LATEST").exists():
        pytest.skip("data/snapshots yok")
    from tools import calculate_indicators

    env = calculate_indicators.run({"ticker": "THYAO", "indicators": ["RSI", "BOLLINGER", "SUPERTREND"],
                                    "end": AS_OF, "as_of": AS_OF, "last_n_rows": 5})   # 1.2.0 varsayılanı 0; recent_rows testleri 5 ister
    assert env["status"] == "OK"
    return env


@pytest.fixture(scope="session")
def retail_rank() -> dict:
    """Gerçek rank_sector_relative_strength: retail, as_of 10.09.2026, split_date YOK (IS/OOS ve OOS bayrağı None)."""
    if not (SNAPSHOT_ROOT / "LATEST").exists():
        pytest.skip("data/snapshots yok")
    from tools import rank_sector_relative_strength

    env = rank_sector_relative_strength.run({"sector": "retail", "horizon": 20, "as_of": AS_OF})
    assert env["status"] == "OK"
    return env


@pytest.fixture(scope="session")
def retail_rank_split() -> dict:
    """Aynı çağrı, split_date=2026-01-01 (as_of yılının başı): IS/OOS dolu, 20g'de OOS_DEGRADATION."""
    if not (SNAPSHOT_ROOT / "LATEST").exists():
        pytest.skip("data/snapshots yok")
    from tools import rank_sector_relative_strength

    env = rank_sector_relative_strength.run({"sector": "retail", "horizon": 20, "as_of": AS_OF,
                                             "split_date": "2026-01-01"})
    assert env["status"] == "OK"
    return env


WEEKDAY_PATTERN = ([{"weekday": d, "direction": "DOWN", "role": "TRIGGER"} for d in ("MON", "TUE", "WED")]
                   + [{"weekday": d, "direction": "UP", "role": "OUTCOME"} for d in ("THU", "FRI")])


def weekday_params(ticker: str, **over) -> dict:
    """Örnek soru 2'nin örüntüsü: Pzt-Sal-Çar düşüş, ardından Per-Cum yükseliş; IS 2024-2025, OOS 2026 (split 2026-01-01)."""
    return {"as_of": AS_OF, "ticker": ticker, "pattern": WEEKDAY_PATTERN, "in_sample_start": "2024-01-01", "in_sample_end": "2025-12-31",
            "out_of_sample_start": "2026-01-01", "out_of_sample_end": AS_OF, **over}


def _real_weekday(ticker: str) -> dict:
    if not (SNAPSHOT_ROOT / "LATEST").exists():
        pytest.skip("data/snapshots yok")
    from tools import test_weekday_pattern

    env = test_weekday_pattern.run(weekday_params(ticker))
    assert env["status"] == "OK"
    return env


@pytest.fixture(scope="session")
def thyao_weekday() -> dict:
    """Gerçek test_weekday_pattern THYAO (karar UNSTABLE: IS_NOT_SIGNIFICANT)."""
    return _real_weekday("THYAO")


@pytest.fixture(scope="session")
def asels_weekday() -> dict:
    """Gerçek test_weekday_pattern ASELS (karar INSUFFICIENT_DATA: IS_TOO_FEW)."""
    return _real_weekday("ASELS")
