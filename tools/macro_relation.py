"""get_macro_context.relate_to hesabı (şema 1.5.0): makro dönüşümü x ile hisse blok getirisi y arasındaki ilişki. SAF fonksiyonlar (ağ yok, snapshot okumaz).

ÖRNEKLEM (docs/data_dictionary.md §22.2):
  * İşlem günleri = hissenin snapshot'taki günleri (<= eff_end, as_of'a kesilmiş). Başlangıç çapası s0 = start'a eşit/sonraki ilk işlem günü.
  * Çapalar g_k = s0 + k * horizon. Blok k = (g_k, g_(k+1)]: ÖRTÜŞMEZ (örtüşme n_obs'u şişirirdi). Son artık (< horizon gün) KISMİ bloktur:
    istatistiğe girmez ve n_excluded_incomplete_horizon = 1 olarak raporlanır (kural 2).
  * y_k = hissenin adj_close getirisi g_k -> g_(k+1) (%).
  * x_k = makro dönüşümü, makro değerleri g_k - lag ve g_(k+1) - lag işlem günlerinde (lag 0: eş zamanlı; lag = horizon: bir önceki blok = öncü, look-ahead yok).
    Makro değeri bir günde = o güne kadar YAYIMLANMIŞ son gözlem (ileri taşıma; tatil ve tatil dışı boşlukta da). Makro geçmişi yoksa blok atılır.
  * Örneklem içi / dışı: blok bitişi < split_date -> IS; blok başlangıç çapası >= split_date -> OOS; split'i kesen blok yalnızca "full"e girer.

İSTATİSTİK: Pearson korelasyonu (birimsiz), OLS eğimi (y pp / x birimi), x>0 ve x<0 gruplarında ve koşulsuz ortalama/medyan getiri (uzun pozisyon, tur maliyeti düşülmüş),
permütasyon p-değeri (B=10000, sabit tohum 481, çift yönlü, korelasyon istatistiği; scipy yok) ve Bonferroni (p x n_tests_declared).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from config.settings import MIN_EVENTS, MIN_OOS_EVENTS
from schemas.common import SampleWindow
from schemas.enums import MacroTransform
from schemas.results import MacroRelation, RelationGroupStats, RelationWindowResult

N_PERMUTATIONS = 10_000
PERMUTATION_SEED = 481
OOS_MIN_CORR_RATIO = 0.5   # VARSAYIM: |OOS korelasyon| < 0.5 x |IS korelasyon| ya da işaret tersi -> bozulma
ROUND = 4
P_ROUND = 6
_CHUNK = 1_000


def _r(x: float) -> float:
    return float(np.round(x, ROUND)) + 0.0   # -0.0 -> 0.0


def perm_pvalue_corr(x: np.ndarray, y: np.ndarray, n_perm: int = N_PERMUTATIONS, seed: int = PERMUTATION_SEED) -> float | None:
    """Çift yönlü permütasyon p-değeri: P(|r(x, karışık y)| >= |r gözlenen|), (count + 1) / (B + 1). n < 3 veya sabit seri -> None."""
    n = len(x)
    if n < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    zx = (x - x.mean()) / x.std()
    zy = (y - y.mean()) / y.std()
    r_obs = abs(float(np.mean(zx * zy)))
    rng = np.random.default_rng(seed)
    count = 0
    for start in range(0, n_perm, _CHUNK):
        m = min(_CHUNK, n_perm - start)
        perms = rng.permuted(np.tile(zy, (m, 1)), axis=1)
        r = np.abs((perms * zx).mean(axis=1))
        count += int((r >= r_obs - 1e-12).sum())   # 1e-12: kayan nokta eşitliği (kusursuz ilişkide gözlenen de sayılır)
    return (count + 1) / (n_perm + 1)


def _group(y: np.ndarray, cost_pct: float) -> RelationGroupStats:
    if len(y) == 0:
        return RelationGroupStats(n=0)
    mean = _r(y.mean())
    return RelationGroupStats(n=int(len(y)), mean_return_pct=mean, median_return_pct=_r(np.median(y)),
                              cost_adjusted_mean_return_pct=_r(mean - cost_pct))


def window_stats(x: np.ndarray, y: np.ndarray, window: SampleWindow, n_incomplete: int, *, n_tests: int, alpha: float, cost_pct: float) -> RelationWindowResult:
    n = len(x)
    corr = beta = None
    if n >= 3 and np.std(x) > 0 and np.std(y) > 0:
        corr = float(np.clip(np.corrcoef(x, y)[0, 1], -1.0, 1.0))
    if n >= 3 and np.std(x) > 0:
        beta = float(np.cov(x, y, bias=True)[0, 1] / np.var(x))
    p_raw = perm_pvalue_corr(x, y)
    p_raw = round(p_raw, P_ROUND) if p_raw is not None else None   # düzeltilmiş p yuvarlanmış ham p'den türer (zarf içi tutarlılık)
    p_adj = round(min(1.0, p_raw * n_tests), P_ROUND) if p_raw is not None else None
    return RelationWindowResult(
        window=window, n_obs=n, n_excluded_incomplete_horizon=n_incomplete,
        correlation=_r(corr) if corr is not None else None, beta=_r(beta) if beta is not None else None,
        p_value_raw=p_raw, p_value_adjusted=p_adj, significant_after_correction=(p_adj < alpha) if p_adj is not None else None,
        macro_up=_group(y[x > 0], cost_pct), macro_down=_group(y[x < 0], cost_pct), unconditional=_group(y, cost_pct))


@dataclass(frozen=True)
class Blocks:
    x: np.ndarray
    y: np.ndarray
    anchor_pos: np.ndarray      # blok başlangıç çapasının işlem günü konumu
    end_pos: np.ndarray         # blok bitişinin konumu
    n_incomplete: int           # kısmi artık blok (0/1)


def macro_value_on(days: np.ndarray, m_dates: np.ndarray, m_vals: np.ndarray) -> np.ndarray:
    """Her işlem günü için o güne kadar yayımlanmış SON makro gözlemi (ileri taşıma); gözlem yoksa NaN."""
    idx = np.searchsorted(m_dates, days, side="right") - 1
    out = np.full(len(days), np.nan)
    ok = idx >= 0
    out[ok] = m_vals[idx[ok]]
    return out


def build_blocks(days: np.ndarray, prices: np.ndarray, macro_on_day: np.ndarray, *, start: date, horizon: int, lag_days: int,
                 transform: MacroTransform) -> Blocks:
    """Örtüşmeyen bloklar (modül docstring'i). `days`: datetime64[D] işlem günleri (<= eff_end), `macro_on_day`: macro_value_on çıktısı."""
    s0 = int(np.searchsorted(days, np.datetime64(start), side="left"))
    n = len(days)
    if s0 >= n:
        return Blocks(np.array([]), np.array([]), np.array([], int), np.array([], int), 0)
    n_full = (n - 1 - s0) // horizon
    leftover = (n - 1 - s0) - n_full * horizon
    xs, ys, a_pos, b_pos = [], [], [], []
    for k in range(n_full):
        a, b = s0 + k * horizon, s0 + (k + 1) * horizon
        ma, mb = a - lag_days, b - lag_days
        if ma < 0 or np.isnan(macro_on_day[ma]) or np.isnan(macro_on_day[mb]) or prices[a] <= 0:
            continue
        if transform == MacroTransform.PCT_CHANGE:
            if macro_on_day[ma] <= 0:
                continue
            x = (macro_on_day[mb] / macro_on_day[ma] - 1.0) * 100.0
        else:
            x = macro_on_day[mb] - macro_on_day[ma]
        xs.append(x)
        ys.append((prices[b] / prices[a] - 1.0) * 100.0)
        a_pos.append(a)
        b_pos.append(b)
    return Blocks(np.array(xs, float), np.array(ys, float), np.array(a_pos, int), np.array(b_pos, int), 1 if leftover > 0 else 0)


def _window(days: np.ndarray, pos: np.ndarray, fallback: date) -> SampleWindow:
    if len(pos) == 0:
        return SampleWindow(start=fallback, end=fallback)
    return SampleWindow(start=days[pos.min()].astype("datetime64[D]").astype(object), end=days[pos.max()].astype("datetime64[D]").astype(object))


def oos_flag(is_res: RelationWindowResult, oos_res: RelationWindowResult) -> tuple[bool, bool]:
    """(bozulma bayrağı, OOS_TOO_SMALL). OOS n_obs < MIN_OOS_EVENTS -> (False, True). Aksi halde işaret tersi ya da zayıflama (<0.5x)."""
    if oos_res.n_obs < MIN_OOS_EVENTS:
        return False, True
    ci, co = is_res.correlation, oos_res.correlation
    if ci is None or co is None:
        return False, False
    flipped = (ci > 0) != (co > 0) and ci != 0 and co != 0
    return bool(flipped or abs(co) < OOS_MIN_CORR_RATIO * abs(ci)), False


def compute_relation(spec, days: np.ndarray, prices: np.ndarray, macro_on_day: np.ndarray, *, start: date, eff_end: date,
                     n_tests: int, alpha: float, cost_pct: float) -> tuple[MacroRelation, dict]:
    """Tek RelationSpec için MacroRelation + yardımcı bilgi {'oos_too_small': bool}."""
    b = build_blocks(days, prices, macro_on_day, start=start, horizon=spec.horizon, lag_days=spec.lag_days, transform=spec.transform)
    kw = dict(n_tests=n_tests, alpha=alpha, cost_pct=cost_pct)
    full = window_stats(b.x, b.y, _window(days, np.concatenate([b.anchor_pos, b.end_pos]) if len(b.x) else b.anchor_pos, start), b.n_incomplete, **kw)
    is_res = oos_res = None
    flag = None
    info = {"oos_too_small": False}
    if spec.split_date is not None:
        sd = np.datetime64(spec.split_date)
        end_dates = days[b.end_pos] if len(b.x) else np.array([], dtype="datetime64[D]")
        anchor_dates = days[b.anchor_pos] if len(b.x) else np.array([], dtype="datetime64[D]")
        is_m, oos_m = end_dates < sd, anchor_dates >= sd
        is_res = window_stats(b.x[is_m], b.y[is_m], _window(days, np.concatenate([b.anchor_pos[is_m], b.end_pos[is_m]]) if is_m.any() else b.anchor_pos[is_m], start), 0, **kw)
        oos_res = window_stats(b.x[oos_m], b.y[oos_m], _window(days, np.concatenate([b.anchor_pos[oos_m], b.end_pos[oos_m]]) if oos_m.any() else b.anchor_pos[oos_m], spec.split_date), b.n_incomplete, **kw)
        flag, info["oos_too_small"] = oos_flag(is_res, oos_res)
    last = days[b.end_pos.max()].astype("datetime64[D]").astype(object) if len(b.x) else None
    rel = MacroRelation(ticker=spec.ticker, macro_series=spec.macro_series, horizon=spec.horizon, lag_days=spec.lag_days, transform=spec.transform,
                        full=full, in_sample=is_res, out_of_sample=oos_res, oos_degradation_flag=flag, sample_last_date=last)
    info["few_events"] = full.n_obs < MIN_EVENTS
    return rel, info
