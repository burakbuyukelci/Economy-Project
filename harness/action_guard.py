"""Eylem koruması (madde 5): nihai çıktının eylem etiketi ve yatırım tavsiyesi / hedef fiyat dili.

İki bağımsız denetim, tek rapor (`ActionGuardReport`):

1. EYLEM ETİKETİ — nihai çıktıda `EYLEM: <ETİKET>` (ya da `ACTION:`) satırı ZORUNLU ve etiket `AllowedAction` içinde olmalı.
   NO_ACTION / MULTIPLE_ACTIONS / ACTION_NOT_IN_ENUM / ACTION_MISMATCH_REQUIRED (güvenli hata yolunda ANALYSIS_UNSAFE zorunlu).
   Metin içinde geçen enum adı (örn. "WATCH olarak izlenebilir") etiket SAYILMAZ; yalnızca etiket satırı sayılır.
2. TAVSİYE DİLİ — al/sat emri, hedef fiyat, kesinlik/garanti ifadeleri (Türkçe + İngilizce). Kalıplar KOD DEĞİL VERİ:
   harness/lexicons/advice_phrases.json (kural başına positive/negative örnek; testler çalıştırır).

ALINTILANAN ÇÜRÜTME MUAFİYETİ. Ornek_test_sorulari Soru 5, modelin "'kesin yükselir' iddiası doğrulanmamıştır" demesini BEKLİYOR;
saf bir filtre bunu yanlış yakalar. Bir cümledeki kalıp(lar) yalnızca TÜM şu koşullarda muaftır (aksi halde cümledeki hepsi ihlal):
   * cümlede OLUMSUZLANMAMIŞ ve tırnak DIŞINDA bir çürütme/reddetme işareti var ("doğrulanmamıştır", "veremem", "garanti değildir" …);
     işaretten sonraki 3 sözcük içinde "değil" varsa (örn. "doğrulanmamış değil") işaret olumsuzlanmıştır => geçersiz;
   * cümledeki HER kalıp uygundur: AL/SAT kalıpları yalnızca TIRNAK İÇİNDEYSE; hedef fiyat / kesinlik kalıpları tırnak içindeyse,
     hemen ardından "iddia/ifade/söylem" geliyorsa ya da ≤4 sözcük yakınında bir REDDETME işareti varsa ("hedef fiyat veremem").
   Muaf kalıplar ihlal olmaz, `QUOTED_REFUTATION` notu düşer. Sınırlar: çürütme başka cümledeyse muafiyet yok; yalnızca
   "doğrulanmamış" gibi çürütme sözcüğü (iddia/ifade ya da tırnak olmadan) yetmez.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from harness.number_verifier import tr_lower
from schemas.enums import AllowedAction

LEXICON_PATH = Path(__file__).resolve().parent / "lexicons" / "advice_phrases.json"
ALLOWED = {a.value for a in AllowedAction}

_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u"})


def tr_fold(s: str) -> str:
    """Türkçe küçük harf + ASCII katlama (ç->c, ğ->g, ı->i, ö->o, ş->s, ü->u), 1:1 (span'lar kaymaz).

    Hem metne hem lang=tr kalıplarına uygulanır: 'KESİN YÜKSELİR', 'KESIN YUKSELIR' ve 'kesin yükselir' aynı eşleşir.
    Neden: model ASCII/büyük harfle yazarak ('IDDIASI', 'ALIN') kalıbı atlatamamalı."""
    return tr_lower(s).translate(_FOLD)


# =============================== rapor tipleri ===============================
@dataclass(frozen=True)
class Violation:
    code: str                       # NO_ACTION | MULTIPLE_ACTIONS | ACTION_NOT_IN_ENUM | ACTION_MISMATCH_REQUIRED | ADVICE_LANGUAGE | QUOTED_REFUTATION
    message: str
    rule_id: str | None = None
    category: str | None = None     # BUY_SELL | PRICE_TARGET | CERTAINTY
    phrase: str | None = None
    sentence: str | None = None
    start: int | None = None
    end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("code", "message", "rule_id", "category", "phrase", "sentence", "start", "end")}


@dataclass
class ActionGuardReport:
    action: AllowedAction | None
    violations: list[Violation] = field(default_factory=list)
    notes: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "action": self.action.value if self.action else None,
                "violations": [v.to_dict() for v in self.violations], "notes": [n.to_dict() for n in self.notes]}


# =============================== kalıp dosyası ===============================
@dataclass(frozen=True)
class Rule:
    id: str
    lang: str
    category: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class Lexicon:
    rules: tuple[Rule, ...]
    refusal: tuple[tuple[str, re.Pattern[str]], ...]
    refutation: tuple[tuple[str, re.Pattern[str]], ...]
    negation_after: tuple[tuple[str, re.Pattern[str]], ...]
    negation_before: tuple[tuple[str, re.Pattern[str]], ...]
    claim_nouns: tuple[tuple[str, re.Pattern[str]], ...]


def _pat(entry: dict[str, Any]) -> str:
    return tr_fold(entry["pattern"]) if entry["lang"] == "tr" else entry["pattern"]


def _flags(entry: dict[str, Any]) -> int:
    f = 0 if (entry.get("lang") == "tr" or entry.get("case_sensitive")) else re.IGNORECASE
    for name in entry.get("flags", []):
        f |= getattr(re, name)
    return f


def _compile_list(items: list[dict[str, Any]]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((e["lang"], re.compile(_pat(e), _flags(e))) for e in items)


@lru_cache(maxsize=1)
def load_lexicon(path: Path | None = None) -> Lexicon:
    data = json.loads((path or LEXICON_PATH).read_text(encoding="utf-8"))
    rules = tuple(Rule(r["id"], r["lang"], r["category"], re.compile(_pat(r), _flags(r))) for r in data["rules"])
    return Lexicon(rules, _compile_list(data["refusal_markers"]), _compile_list(data["refutation_markers"]),
                   _compile_list(data["negation_after"]), _compile_list(data["negation_before"]),
                   _compile_list(data["claim_nouns"]))


# =============================== 1. eylem etiketi ===============================
_ACTION_LINE = re.compile(r"^[ \t]*[>#*_\-\t ]*(?:eylem|action)\**[ \t]*[:：]\**[ \t]*(?P<v>[^\n]*?)[ \t]*$", re.I | re.M)
_EDGE = " \t*`'\"[]<>().,;:"


def extract_action(text: str) -> tuple[AllowedAction | None, list[Violation]]:
    lines = [m.group("v") for m in _ACTION_LINE.finditer(text)]
    if not lines:
        return None, [Violation("NO_ACTION", "nihai çıktıda 'EYLEM: <ETİKET>' satırı yok")]
    found: list[str] = []
    problems: list[Violation] = []
    for raw in lines:
        value = raw.strip(_EDGE)
        if not value:
            problems.append(Violation("NO_ACTION", "'EYLEM:' satırı boş"))
        elif re.fullmatch(r"[A-Za-z][A-Za-z_]*", value):
            if value in ALLOWED:
                found.append(value)
            elif value.upper() in ALLOWED:
                problems.append(Violation("ACTION_NOT_IN_ENUM",
                                          f"etiket büyük harfle yazılmalı: {value!r} -> {value.upper()!r}"))
            else:
                problems.append(Violation("ACTION_NOT_IN_ENUM", f"izinli eylem seti dışında: {value!r}"))
        else:
            labels = set(re.findall(r"[A-Z][A-Z_]+", raw))
            if len(labels) >= 2:
                problems.append(Violation("MULTIPLE_ACTIONS", f"tek etiket olmalı, birden çok etiket var: {sorted(labels)}"))
            else:
                problems.append(Violation("ACTION_NOT_IN_ENUM", f"satırda yalnızca etiket olmalı, bulunan: {raw!r}"))
    if len(set(found)) > 1:
        return None, [Violation("MULTIPLE_ACTIONS", f"birden çok farklı eylem etiketi: {sorted(set(found))}")]
    if problems:
        return None, problems
    return AllowedAction(found[0]), []


# =============================== 2. tavsiye dili ===============================
_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n[ \t]*\n+|\n(?=[ \t]*(?:[-*•#>]|\d{1,2}[.)]))")
_QUOTES = tuple(re.compile(p) for p in (
    r"“[^”\n]{1,300}”", r'"[^"\n]{1,300}"', r"«[^»\n]{1,300}»",
    r"(?<![\w'’‘])‘[^’\n]{1,100}’(?!\w)", r"(?<![\w'’‘])'[^'\n]{1,100}'(?!\w)",   # kesme işareti (THYAO'nun) tırnak DEĞİLDİR
))
_WORD = re.compile(r"\w+")
_AFTER_WORDS = 4
_NEG_AFTER_WORDS = 3
_NEG_BEFORE_WORDS = 2
_NOUN_WORDS = 2


@dataclass(frozen=True)
class _Hit:
    rule: Rule
    start: int
    end: int


@dataclass(frozen=True)
class _Marker:
    start: int
    end: int
    kind: str  # "refusal" | "refutation"


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for m in list(_SPLIT.finditer(text)) + [None]:
        end = m.start() if m else len(text)
        if text[pos:end].strip():
            spans.append((pos, end))
        pos = m.end() if m else len(text)
    return spans


def _words_after(text: str, pos: int, limit: int, n: int) -> list[re.Match[str]]:
    out: list[re.Match[str]] = []
    for w in _WORD.finditer(text, pos, limit):
        out.append(w)
        if len(out) == n:
            break
    return out


def _words_before(text: str, pos: int, floor: int, n: int) -> list[re.Match[str]]:
    return list(_WORD.finditer(text, floor, pos))[-n:]


def _search(entries: tuple[tuple[str, re.Pattern[str]], ...], orig: str, low: str, start: int, end: int) -> bool:
    return any(p.search(low if lang == "tr" else orig, start, end) for lang, p in entries)


def find_advice_language(text: str) -> tuple[list[Violation], list[Violation]]:
    """(ihlaller, notlar): tavsiye / hedef fiyat / kesinlik kalıpları ve muaf tutulan alıntılanan çürütmeler."""
    lex = load_lexicon()
    low = tr_fold(text)
    hits: list[_Hit] = []
    for rule in lex.rules:
        for m in rule.regex.finditer(low if rule.lang == "tr" else text):
            hits.append(_Hit(rule, m.start(), m.end()))
    if not hits:
        return [], []
    hits.sort(key=lambda h: (h.start, h.end))
    quotes = [m.span() for p in _QUOTES for m in p.finditer(text)]

    def in_quote(a: int, b: int) -> bool:
        return any(qs <= a and b <= qe for qs, qe in quotes)

    markers: list[_Marker] = []
    for kind, entries in (("refusal", lex.refusal), ("refutation", lex.refutation)):
        for lang, p in entries:
            for m in p.finditer(low if lang == "tr" else text):
                markers.append(_Marker(m.start(), m.end(), kind))

    def negated(mk: _Marker, se: int) -> bool:
        after = _words_after(low, mk.end, se, _NEG_AFTER_WORDS)
        if after and _search(lex.negation_after, text, low, mk.end, after[-1].end()):
            return True
        before = _words_before(low, mk.start, 0, _NEG_BEFORE_WORDS)
        return bool(before) and _search(lex.negation_before, text, low, before[0].start(), mk.start)

    violations: list[Violation] = []
    notes: list[Violation] = []
    for ss, se in _sentences(text):
        inside = [h for h in hits if ss <= h.start < se]
        if not inside:
            continue
        good = [mk for mk in markers if ss <= mk.start and mk.end <= se and not in_quote(mk.start, mk.end) and not negated(mk, se)]

        def eligible(h: _Hit) -> bool:
            if not good:
                return False
            if in_quote(h.start, h.end):
                return True
            if h.rule.category == "BUY_SELL":
                return False  # al/sat emri yalnızca tırnak içindeyse muaf
            nouns = _words_after(low, h.end, se, _NOUN_WORDS)
            if nouns and _search(lex.claim_nouns, text, low, h.end, nouns[-1].end()):
                return True
            after = _words_after(low, h.end, se, _AFTER_WORDS)
            a_lim = after[-1].end() if after else h.end
            before = _words_before(low, h.start, ss, _AFTER_WORDS)
            b_lim = before[0].start() if before else h.start
            return any(mk.kind == "refusal" and (
                (mk.start < h.end and h.start < mk.end)                 # kalıbın kendisini kapsıyor ("garanti değildir")
                or (h.end <= mk.start < a_lim)                            # "hedef fiyat veremem"
                or (b_lim < mk.end <= h.start)                            # "cannot provide a price target"
            ) for mk in good)

        sentence = " ".join(text[ss:se].split())
        exempt = all(eligible(h) for h in inside)
        for h in inside:
            phrase = text[h.start:h.end]
            if exempt:
                notes.append(Violation("QUOTED_REFUTATION", "tavsiye kalıbı alıntılanan/çürütülen iddia olarak geçiyor (muaf)",
                                       h.rule.id, h.rule.category, phrase, sentence, h.start, h.end))
            else:
                violations.append(Violation("ADVICE_LANGUAGE", f"yatırım tavsiyesi/hedef fiyat/kesinlik dili ({h.rule.category})",
                                            h.rule.id, h.rule.category, phrase, sentence, h.start, h.end))
    return violations, notes


# =============================== ana fonksiyon ===============================
def check_final_output(text: str, *, required_action: AllowedAction | str | None = None) -> ActionGuardReport:
    """Nihai çıktıyı denetler: tam bir izinli eylem etiketi + tavsiye dili yok.

    required_action: güvenli hata yolunda (kapı HARD_BLOCK/ANALYSIS_UNSAFE) ANALYSIS_UNSAFE zorunludur."""
    action, problems = extract_action(text)
    violations = list(problems)
    if action is not None and required_action is not None and action != AllowedAction(required_action):
        violations.append(Violation("ACTION_MISMATCH_REQUIRED",
                                    f"bu durumda eylem {AllowedAction(required_action).value} olmalı, {action.value} verildi"))
    advice, notes = find_advice_language(text)
    violations.extend(advice)
    return ActionGuardReport(action, violations, notes)
