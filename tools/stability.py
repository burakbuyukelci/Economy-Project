"""Örneklem içi/dışı kararlılık kuralları (saf fonksiyonlar; ağ yok, veri okuma yok).

Kural metni: docs/data_dictionary.md §8 (stability_verdict) ve §9 (oos_degradation_flag).
"""
from __future__ import annotations

from config.settings import (
    MIN_OOS_EVENTS,
    MIN_WEEKDAY_IS_TRIGGER_WEEKS,
    MIN_WEEKDAY_OOS_TRIGGER_WEEKS,
    OOS_DEGRADATION_HIT_RATE_DROP_PP,
    WEEKDAY_OOS_MIN_EFFECT_RATIO,
    WEEKDAY_OOS_MIN_HIT_RATE_PCT,
)
from schemas.common import HorizonStats
from schemas.enums import Direction, StabilityVerdict, VerdictCode
from schemas.results import WeekdayPeriodResult


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def weekday_stability_verdict(
    in_sample: WeekdayPeriodResult,
    out_of_sample: WeekdayPeriodResult,
    outcome_direction: Direction,  # noqa: ARG001  (cost_adjusted zaten yönlü; ileride karışık yön için ayrılmış)
    alpha: float,
) -> tuple[StabilityVerdict, list[VerdictCode], str]:
    """Sıra: (i) IS n küçük -> INSUFFICIENT_DATA; (ii) IS anlamlı değil -> UNSTABLE;
    (iii) IS anlamlı ama OOS n küçük -> INSUFFICIENT_DATA; (iv) (b)-(e) kontrolü -> STABLE/UNSTABLE.
    """
    is_, oos = in_sample, out_of_sample

    # (i)
    if is_.n_trigger_weeks < MIN_WEEKDAY_IS_TRIGGER_WEEKS:
        return (StabilityVerdict.INSUFFICIENT_DATA, [VerdictCode.IS_TOO_FEW],
                f"IS_TOO_FEW: IS n_trigger_weeks={is_.n_trigger_weeks} < {MIN_WEEKDAY_IS_TRIGGER_WEEKS}")

    # (ii)
    p_adj = is_.p_value_adjusted
    if p_adj is None or p_adj >= alpha:
        return (StabilityVerdict.UNSTABLE, [VerdictCode.IS_NOT_SIGNIFICANT],
                f"IS_NOT_SIGNIFICANT: IS p_value_adjusted={p_adj} >= alpha={alpha}")

    # (iii)
    if oos.n_trigger_weeks < MIN_WEEKDAY_OOS_TRIGGER_WEEKS:
        return (StabilityVerdict.INSUFFICIENT_DATA, [VerdictCode.OOS_TOO_FEW],
                f"OOS_TOO_FEW: OOS n_trigger_weeks={oos.n_trigger_weeks} < {MIN_WEEKDAY_OOS_TRIGGER_WEEKS}")

    # (iv) (b)-(e)
    codes: list[VerdictCode] = []
    parts: list[str] = []
    is_diff = is_.outcome_mean_diff_vs_unconditional_pct
    oos_diff = oos.outcome_mean_diff_vs_unconditional_pct

    # (b) işaret uyumu
    if is_diff is None or oos_diff is None or _sign(is_diff) == 0 or _sign(is_diff) != _sign(oos_diff):
        codes.append(VerdictCode.OOS_SIGN_FLIP)
        parts.append(f"OOS_SIGN_FLIP: IS diff={is_diff}pp, OOS diff={oos_diff}pp")
    # (c) maliyet sonrası yönlü OOS getiri > 0
    ca = oos.cost_adjusted_outcome_mean_return_pct
    if ca is None or ca <= 0:
        codes.append(VerdictCode.OOS_COST_ADJ_NOT_POSITIVE)
        parts.append(f"OOS_COST_ADJ_NOT_POSITIVE: OOS cost_adjusted={ca}%")
    # (d) OOS isabet oranı
    hr = oos.hit_rate_pct
    if hr is None or hr < WEEKDAY_OOS_MIN_HIT_RATE_PCT:
        codes.append(VerdictCode.OOS_HIT_RATE_TOO_LOW)
        parts.append(f"OOS_HIT_RATE_TOO_LOW: OOS hit_rate={hr}% < {WEEKDAY_OOS_MIN_HIT_RATE_PCT}%")
    # (e) etki büyüklüğü: yalnızca (b) geçtiyse anlamlı (işaret ters ise zaten OOS_SIGN_FLIP raporlandı)
    if (
        VerdictCode.OOS_SIGN_FLIP not in codes
        and abs(oos_diff) < WEEKDAY_OOS_MIN_EFFECT_RATIO * abs(is_diff)  # type: ignore[arg-type]
    ):
        codes.append(VerdictCode.OOS_EFFECT_TOO_SMALL)
        parts.append(
            f"OOS_EFFECT_TOO_SMALL: |OOS diff|={abs(oos_diff)}pp < {WEEKDAY_OOS_MIN_EFFECT_RATIO} x |IS diff|={abs(is_diff)}pp"
        )

    if codes:
        return StabilityVerdict.UNSTABLE, codes, "; ".join(parts)
    return StabilityVerdict.STABLE, [], (
        f"STABLE: IS p_adj={p_adj} < alpha={alpha}; OOS diff={oos_diff}pp, cost_adjusted={ca}%, hit_rate={hr}%"
    )


def oos_degradation(
    in_sample: HorizonStats | None, out_of_sample: HorizonStats | None
) -> tuple[bool | None, bool]:
    """(oos_degradation_flag, oos_too_small).

    * IS veya OOS yoksa (split_date verilmemiş): (None, False).
    * OOS tamamlanmış olay sayısı < MIN_OOS_EVENTS: (False, True) -> çağıran OOS_TOO_SMALL uyarısı ekler.
    * Aksi halde True, eğer: (OOS maliyet sonrası ort <= 0 iken IS maliyet sonrası ort > 0)
      VEYA (OOS isabet oranı, IS isabet oranından > OOS_DEGRADATION_HIT_RATE_DROP_PP puan düşükse).
    """
    if in_sample is None or out_of_sample is None:
        return None, False
    if out_of_sample.n_events_complete < MIN_OOS_EVENTS:
        return False, True

    cost_rule = (
        in_sample.cost_adjusted_mean_return_pct is not None
        and out_of_sample.cost_adjusted_mean_return_pct is not None
        and in_sample.cost_adjusted_mean_return_pct > 0
        and out_of_sample.cost_adjusted_mean_return_pct <= 0
    )
    hit_rule = (
        in_sample.hit_rate_pct is not None
        and out_of_sample.hit_rate_pct is not None
        and (in_sample.hit_rate_pct - out_of_sample.hit_rate_pct) > OOS_DEGRADATION_HIT_RATE_DROP_PP
    )
    return bool(cost_rule or hit_rule), False
