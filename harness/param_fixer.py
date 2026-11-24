"""Parametre düzeltici: modelin yalnızca BİÇİM hatası olan araç çağrılarını, araç çalışmadan önce deterministik olarak onarır.

Neden: v2.3 değerlendirmesinde D/E oturumlarının ~%25'i `TURN_LIMIT` ile kesildi; kesilenlerde model aynı geçersiz çağrıyı 40 kez tekrarladı
(örn. `get_fundamental_metrics period="Q3"`; geçerli biçim `2026Q3`). Model hata metninden biçimi çıkaramıyor.

Kurallar (değişmez):
  * Hata-güdümlü: yalnızca şema doğrulaması BAŞARISIZ olan çağrılara dokunulur; geçerli çağrı aynen geçer.
  * `as_of` kilitlidir: as_of ile ilgili hata varsa düzeltme YAPILMAZ (as_of kuralı).
  * Belirsizse düzeltme yok: dönem biçimi tek anlama geliyorsa, enum değeri büyük/küçük harf dışında birebir eşleşiyorsa onarılır; "son çeyrek", "latest" gibi
    anlamı tahmin gerektiren değerler onarılmaz (model orijinal hatayı görür).
  * Yılsız dönem ("Q3"): yıl = as_of yılı; dönem sonu as_of'tan sonraysa bir önceki yıl (as_of sonrası dönem seçilmez).
  * Sözleşmede olmayan alan (`extra_forbidden`) çıkarılır ve NOT edilir.
  * Sessiz değil: her düzeltme `notes` olarak döner; oturum bunu olaya, uyarıya ve araç zarfındaki gerçek `params`'a yansıtır (input_hash düzeltilmiş çağrıdan).
  * Tam doğrulanamayan sonuç döndürülmez: düzeltilmiş params hâlâ şemaya uymuyorsa `(None, [])`.
"""
from __future__ import annotations

import copy
import re
from datetime import date
from typing import Any

from pydantic import ValidationError

from schemas.common import FiscalPeriod  # noqa: F401  (desen kaynağı)
from schemas.enums import ToolName
from schemas.registry import validate_params

_PERIOD_PATTERN = r"^\d{4}Q[1-4]$"
_SEP = r"[\s_/\-]*"
_P_YEAR_FIRST = re.compile(rf"^\s*(\d{{4}}){_SEP}Q([1-4])\s*$", re.I)
_P_Q_FIRST = re.compile(rf"^\s*Q([1-4]){_SEP}(\d{{4}})\s*$", re.I)
_P_BARE = re.compile(r"^\s*Q([1-4])\s*$", re.I)
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_MAX_PASSES = 4


def _latest_ended_quarter(as_of: date) -> str:
    """as_of'a göre dönem sonu as_of'u aşmayan EN SON takvim çeyreği ("YYYYQn")."""
    for year in (as_of.year, as_of.year - 1):
        for q in (4, 3, 2, 1):
            month, day = _QUARTER_END[q]
            if date(year, month, day) <= as_of:
                return f"{year}Q{q}"
    return f"{as_of.year - 2}Q4"  # pragma: no cover


def _parse_period(raw: str, as_of: date) -> str | None:
    m = _P_YEAR_FIRST.match(raw)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    m = _P_Q_FIRST.match(raw)
    if m:
        return f"{m.group(2)}Q{m.group(1)}"
    m = _P_BARE.match(raw)
    if m:
        q = int(m.group(1))
        month, day = _QUARTER_END[q]
        year = as_of.year if date(as_of.year, month, day) <= as_of else as_of.year - 1
        return f"{year}Q{q}"
    return None


def _expected_values(err: dict[str, Any]) -> list[str]:
    """pydantic 'enum'/'literal_error' hatasındaki izinli değerler (ctx.expected: "'A', 'B' or 'C'")."""
    exp = (err.get("ctx") or {}).get("expected")
    return re.findall(r"'([^']*)'", exp) if isinstance(exp, str) else []


def _get(obj: Any, loc: tuple[Any, ...]) -> Any:
    for k in loc:
        obj = obj[k]
    return obj


def _set(obj: Any, loc: tuple[Any, ...], value: Any) -> None:
    parent = _get(obj, loc[:-1])
    parent[loc[-1]] = value


def _fix_one(err: dict[str, Any], params: dict[str, Any], as_of: date, tool: str, notes: list[str]) -> bool:
    loc = tuple(err["loc"])
    if not loc or "as_of" in [str(x) for x in loc]:
        return False                                           # as_of kilitli
    kind = err["type"]
    try:
        if kind == "extra_forbidden":
            parent = _get(params, loc[:-1])
            if isinstance(parent, dict) and loc[-1] in parent:
                del parent[loc[-1]]
                notes.append(f"{tool}: '{'.'.join(str(x) for x in loc)}' alanı bu araçta yok, çıkarıldı")
                return True
            return False
        value = _get(params, loc)
        if not isinstance(value, str):
            return False
        if kind == "string_pattern_mismatch" and (err.get("ctx") or {}).get("pattern") == _PERIOD_PATTERN:
            fixed = _parse_period(value, as_of)
            if fixed is None:
                return False
            if loc == ("period",) and _P_BARE.match(value) and fixed == _latest_ended_quarter(as_of):
                # yılsız "Q3" = "son çeyrek" anlamı: o çeyreğin bilançosu as_of'ta henüz açıklanmamış olabilir (KAP gecikmesi); tek anlamlı güvenli karşılık
                # `period` alanını hiç yazmamaktır (None = as_of'a kadar AÇIKLANMIŞ en son dönem). Hangi dönemin kullanıldığı araç çıktısında görünür.
                del params["period"]
                notes.append(f"{tool}: 'period' {value!r} = son çeyrek; alan çıkarıldı (as_of'a kadar açıklanmış en son dönem kullanılır)")
                return True
            _set(params, loc, fixed)
            notes.append(f"{tool}: '{'.'.join(str(x) for x in loc)}' {value!r} -> {fixed!r} (dönem biçimi YYYYQn)")
            return True
        if kind in ("enum", "literal_error"):
            want = value.strip().casefold()
            hits = [v for v in _expected_values(err) if v.casefold() == want]
            if len(hits) != 1:
                return False                                   # belirsiz/bilinmeyen: tahmin yok
            _set(params, loc, hits[0])
            notes.append(f"{tool}: '{'.'.join(str(x) for x in loc)}' {value!r} -> {hits[0]!r} (büyük/küçük harf)")
            return True
    except (KeyError, IndexError, TypeError):
        return False
    return False


def fix_params(tool: ToolName | str, params: dict[str, Any], as_of: date) -> tuple[dict[str, Any] | None, list[str]]:
    """(düzeltilmiş params, notlar). Düzeltilecek bir şey yoksa ya da tam onarılamazsa `(None, [])`. Girdi değiştirilmez."""
    work = copy.deepcopy(params)
    notes: list[str] = []
    name = ToolName(tool).value
    for _ in range(_MAX_PASSES):
        try:
            validate_params(tool, work)
        except ValidationError as exc:
            changed = False
            for err in exc.errors():
                changed |= _fix_one(err, work, as_of, name, notes)
            if not changed:
                return None, []
            continue
        return (work, notes) if notes else (None, [])
    return None, []


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def repair_tickers(params: dict[str, Any], question_tickers: list[str], universe: set[str]) -> tuple[dict[str, Any] | None, list[str]]:
    """Modelin yazım hatası yaptığı hisse kodunu ("ERGL" -> "EREGL") onarır; YALNIZCA şu koşullarda:
    kod evrende yok, sorudaki evren hisse kodlarından TAM BİRİ düzenleme uzaklığı <= 2 ile eşleşiyor. Belirsizse (iki aday) ya da uzaksa dokunulmaz.
    `ticker` / `tickers` / `universe` alanları ve iç içe `relate_to[*].ticker` taranır. Girdi değiştirilmez; değişiklik yoksa `(None, [])`."""
    work = copy.deepcopy(params)
    notes: list[str] = []

    def fix(value: str, where: str) -> str:
        if value in universe or len(value) < 3:
            return value
        cands = [q for q in question_tickers if _edit_distance(value.upper(), q) <= 2]
        if len(cands) != 1:
            return value
        notes.append(f"{where}: {value!r} evrende yok; sorudaki hisse kodu {cands[0]!r} olarak düzeltildi (yazım hatası)")
        return cands[0]

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if k == "ticker" and isinstance(v, str):
                    obj[k] = fix(v, f"{path}{k}")
                elif k in ("tickers", "universe") and isinstance(v, list):
                    obj[k] = [fix(x, f"{path}{k}[{i}]") if isinstance(x, str) else x for i, x in enumerate(v)]
                elif isinstance(v, (dict, list)):
                    walk(v, f"{path}{k}.")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}].")

    walk(work, "")
    return (work, notes) if notes else (None, [])
