"""Sayı doğrulayıcı (madde 4): modelin cevabındaki her SAYISAL İDDİA araç çıktısında var mı?

CLAUDE.md kural 6: sayılar yalnızca araç çıktısından gelir. Bu modül SAF bir fonksiyon kümesidir
(oturum/MCP bağımlılığı yok; `verify_session` yalnızca ince bir yardımcıdır).

Akış:  metin --maskele--> --çıkar--> iddialar --izin listesi / havuz / kanıt kümesi--> sınıflandır --> rapor

1. MASKELEME (sayı SAYILMAYANLAR): tanımlayıcılar (XU100, 2025Q1, BB_LOWER_20_2.0, RSI_14, E7, snap_..._v2, kap-0001),
   URL'ler, saatler, [1] dipnotları, satır başı liste numaraları ("1)", "2."), "2. çeyrek" gibi sıra sayıları.
2. ÇIKARMA: tarihler (10.09.2026, 2026-09-10, 10 Eylül 2026), yüzde (%8,5 / 8,5% / yüzde 8,5), puan (8,5 puan / pp),
   düz sayılar (1.234,56 / 8,5 / 8.5 / 1,234.56), ölçek kelimeleri (38,4 milyon). "1.234" gibi belirsiz biçimler İKİ adayla tutulur.
3. SINIFLANDIRMA (her iddia için, sırayla):
   ALLOWLISTED   kullanıcı sorusunda ya da (herhangi bir) araç çağrısı parametresinde AYNEN geçiyor -> iddia sayılmaz, paydaya girmez
   HALLUCINATION hiçbir araç çıktısında (zarf `results`) yok                       (hocanın metriği)
   UNEVIDENCED   araç çıktısında var ama kilitli committed_evidence_set'te yok      (yumuşak uyarı, "kanıtsız")
   SUPPORTED     araç çıktısında var (ve varsa committed kümede de var)

YUVARLAMA KURALI. İddia d ondalıkla yazıldıysa, havuzdaki p değeri d basamağa YARIDAN YUKARI (Decimal, ikili kayan nokta
hatası yok) yuvarlanınca yazılan sayıya eşitse eşleşir. Eşleşme türleri:
   EXACT          p yazılan sayıya sayısal olarak eşit ("8,50" == 8.5)
   ROUNDED        d >= 1 ve yalnızca yuvarlanınca eşit           (44,83 <- 44.8273)
   ROUNDED_COARSE d == 0 ve p tam sayı DEĞİL, yuvarlanınca eşit   ("8" <- 8.46)   [tam sayı yalnızca aynı tam sayıyla EXACT eşleşir]
   SIGN_RELAXED   yalnızca işaret farkıyla eşleşir ("8,5 puan geride" <- -8.5); yön hatası sayı halüsinasyonu sayılmaz
   DATE           tarih eşleşmesi
Birim aramaz: %8,5 ile 8,5 aynı değerdir (alan adı/birim eşlemesi yok).

TÜRETİLMİŞ SAYILAR (14/22 -> %64): araç çıktısında yoksa HALÜSİNASYON'dur. Rapor, aynı cevaptaki DİĞER (desteklenen)
sayılardan türeyip türemediğine bakıp `derivation_hint` yazar; ipucu sayıyı AKLAMAZ, yalnızca "model kendi hesapladı" der.

BİLİNEN SINIRLAR: küçük tam sayılar (1, 2, 3 …) havuzda tesadüfen bulunabilir (oran alt sınırdır); kelimeyle yazılan sayılar
("yüzde sekiz") çıkarılmaz; yön (arttı/azaldı) denetlenmez; "20 gün" gibi soru sayısı aynı zamanda araç değeriyse izin listesinde sayılır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any, Iterable, NamedTuple

BUNDLE_TOOL = "build_evidence_bundle"

VERDICTS = ("SUPPORTED", "UNEVIDENCED", "HALLUCINATION", "ALLOWLISTED", "ALLOWLISTED_POLICY")
_RANK = {"EXACT": 0, "ROUNDED": 1, "ROUNDED_COARSE": 2}  # küçük = daha güçlü eşleşme

_SCALES = {"bin": Decimal(10) ** 3, "milyon": Decimal(10) ** 6, "milyar": Decimal(10) ** 9, "trilyon": Decimal(10) ** 12,
           "thousand": Decimal(10) ** 3, "million": Decimal(10) ** 6, "billion": Decimal(10) ** 9}
_MONTHS = {"ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8,
           "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12}


# =============================== 1. maskeleme ===============================
def tr_lower(s: str) -> str:
    """Türkçe küçük harf (İ->i, I->ı); uzunluğu korur (span'lar bozulmaz)."""
    s = s.replace("İ", "i").replace("I", "ı")
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in s)


_MASKS: tuple[re.Pattern[str], ...] = tuple(re.compile(p, f) for p, f in (
    (r"https?://\S+|www\.\S+", 0),                                   # URL
    (r"\bsnap_\d{4}-\d{2}-\d{2}_v\d+\b", 0),                          # veri sürümü
    (r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+(?:\.\d+)?)+", 0),       # BB_LOWER_20_2.0, RSI_14, SUPERTREND_10_3.0
    (r"\b\d{4}(?:Q[1-4]|H[12]|FY)\b", 0),                             # 2025Q1, 2026H1
    (r"\b[A-Za-z]+\d+[A-Za-z0-9]*\b", 0),                             # XU100, E7, RSI14
    (r"\b[A-Za-z]{2,}-\d+\b", 0),                                     # kap-0001, COVID-19
    (r"\b(?=[0-9]*[a-f])[0-9a-f]{16,}\b", 0),                         # hash (en az bir harf: 16+ haneli düz sayı değil)
    (r"(?<![\d.,])\d{1,2}:\d{2}(?::\d{2})?(?!\d)", 0),                # saat
    (r"\[\s*\d+(?:\s*[,–\-]\s*\d+)*\s*\]", 0),                        # [1] [2,3] dipnotu
    (r"^[ \t]*(?:[-*•>]\s+)?(?:\d{1,2}[.)]|\(\d{1,2}\))(?=\s)", re.M),  # satır başı liste numarası
    (r"(?<![\d.,])\d{1,2}\.(?=\s+[a-zçğıöşü])", 0),                   # "2. çeyrek" sıra sayısı
))


def mask(text: str) -> str:
    """Sayı sayılmayacak bölgeleri aynı uzunlukta boşlukla değiştirir (satır sonları korunur; span'lar kaymaz)."""
    for pat in _MASKS:
        text = pat.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), text)
    return text


# =============================== 2. çıkarma ===============================
class Candidate(NamedTuple):
    value: Decimal      # işaret ve ölçek dahil gerçek değer
    decimals: int       # YAZILAN ondalık basamak sayısı (mantis)
    scale: Decimal      # 1, 10^3 (bin), 10^6 (milyon) …
    mantissa: Decimal   # yazıldığı gibi (işaretli); value = mantissa * scale


@dataclass(frozen=True)
class NumberClaim:
    raw: str
    kind: str                       # "number" | "percent" | "pp" | "date"
    candidates: tuple[Candidate, ...]
    date: date | None               # kind == "date" ise (geçersiz tarihte None)
    start: int
    end: int


_MONTH_ALT = "|".join(_MONTHS)
_SCALE_ALT = "|".join(_SCALES)
_CLAIM_RE = re.compile(rf"""
    (?P<iso>(?<![\d.\-/])(?P<iy>\d{{4}})-(?P<im>\d{{1,2}})-(?P<id>\d{{1,2}})(?!\d))
  | (?P<dmy>(?<![\d.,\-/])(?P<dd>\d{{1,2}})[./](?P<dm>\d{{1,2}})[./](?P<dy>\d{{4}})(?!\d))
  | (?P<trd>(?<![\d.,])(?P<td>\d{{1,2}})\s+(?P<tm>{_MONTH_ALT})\s+(?P<ty>\d{{4}})(?!\d))
  | (?P<num>
        (?P<sign>(?<![\w.,])[-−–+])?
        (?P<pre>%\s?|yüzde\s+)?
        (?<![\d])(?P<digits>
              [1-9]\d{{0,2}}(?:\.\d{{3}})+(?:,\d+)?
            | [1-9]\d{{0,2}}(?:,\d{{3}})+(?:\.\d+)?
            | \d+(?:[.,]\d+)?
        )(?![\d])
        (?P<post>\s?%)?
        (?P<scale>\s?(?:{_SCALE_ALT})(?![a-zçğıöşü]))?
        (?P<unit>\s(?:yüzde\s+puan|puan|pp)(?![a-zçğıöşü]))?
    )
""", re.X)


def _candidates_from_digits(digits: str, sign: int, scale: Decimal) -> tuple[tuple[Decimal, int], ...]:
    """Yazılış -> (mantis, ondalık basamak) adayları. Belirsiz biçimler (1.234 / 1,234) iki aday verir."""
    out: list[tuple[Decimal, int]] = []
    if re.fullmatch(r"[1-9]\d{0,2}(?:\.\d{3})+(?:,\d+)?", digits):          # Türkçe binlik (+ ondalık virgül)
        if "," in digits:
            ip, dp = digits.split(",")
            out.append((Decimal(ip.replace(".", "") + "." + dp), len(dp)))
        else:
            out.append((Decimal(digits.replace(".", "")), 0))                # binlik okuma
            if digits.count(".") == 1:
                out.append((Decimal(digits), 3))                             # ondalık okuma (1.234 = 1,234)
    elif re.fullmatch(r"[1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?", digits):        # İngilizce binlik
        if "." in digits:
            ip, dp = digits.split(".")
            out.append((Decimal(ip.replace(",", "") + "." + dp), len(dp)))
        else:
            out.append((Decimal(digits.replace(",", "")), 0))
            if digits.count(",") == 1:
                out.append((Decimal(digits.replace(",", ".")), 3))           # 1,234 = 1,234 (Türkçe ondalık)
    else:
        sep = "," if "," in digits else ("." if "." in digits else None)
        if sep:
            ip, dp = digits.split(sep)
            out.append((Decimal(ip + "." + dp), len(dp)))
        else:
            out.append((Decimal(digits), 0))
    return tuple((m * sign, d) for m, d in out)


def extract_claims(text: str) -> list[NumberClaim]:
    """Metindeki sayısal iddiaları KONUM sırasıyla döndürür (maskelenenler hariç)."""
    low = tr_lower(mask(text))
    claims: list[NumberClaim] = []
    for m in _CLAIM_RE.finditer(low):
        raw = text[m.start():m.end()]
        if m.group("iso") or m.group("dmy") or m.group("trd"):
            if m.group("iso"):
                y, mo, d = int(m.group("iy")), int(m.group("im")), int(m.group("id"))
            elif m.group("dmy"):
                y, mo, d = int(m.group("dy")), int(m.group("dm")), int(m.group("dd"))
            else:
                y, mo, d = int(m.group("ty")), _MONTHS[m.group("tm")], int(m.group("td"))
            try:
                dt: date | None = date(y, mo, d)
            except ValueError:
                dt = None
            claims.append(NumberClaim(raw, "date", (), dt, m.start(), m.end()))
            continue
        sign = -1 if m.group("sign") in ("-", "−", "–") else 1
        scale_word = (m.group("scale") or "").strip()
        scale = _SCALES[scale_word] if scale_word else Decimal(1)
        cands = tuple(Candidate(mant * scale, d, scale, mant)
                      for mant, d in _candidates_from_digits(m.group("digits"), sign, scale))
        kind = "percent" if (m.group("pre") or m.group("post")) else ("pp" if m.group("unit") else "number")
        claims.append(NumberClaim(raw, kind, cands, None, m.start(), m.end()))
    return claims


# =============================== 3. havuz ===============================
class Source(NamedTuple):
    tool: str
    path: str
    input_hash: str
    value: str


def _dec(x: Any) -> Decimal | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(repr(x)) if x == x and x not in (float("inf"), float("-inf")) else None
    return None


class _Pool:
    """Sayı ve tarih havuzu. Aramalar deterministik: eklenme sırası korunur."""

    def __init__(self) -> None:
        self._entries: list[tuple[Decimal, Source]] = []
        self._exact: dict[Decimal, list[Source]] = {}
        self._rounded: dict[tuple[int, Decimal], dict[Decimal, list[Source]]] = {}
        self.dates: dict[date, list[Source]] = {}

    def add_number(self, value: Decimal, src: Source) -> None:
        self._entries.append((value, src))
        self._exact.setdefault(value, []).append(src)
        self._rounded.clear()

    def add_date(self, d: date, src: Source) -> None:
        self.dates.setdefault(d, []).append(src)

    def add_tree(self, node: Any, *, tool: str, input_hash: str, path: str = "") -> None:
        """Bir JSON ağacının tüm sayı/tarih yapraklarını ekler (dize yapraklarındaki sayılar dahil)."""
        if isinstance(node, dict):
            for k, v in node.items():
                self.add_tree(v, tool=tool, input_hash=input_hash, path=f"{path}.{k}" if path else str(k))
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                self.add_tree(v, tool=tool, input_hash=input_hash, path=f"{path}[{i}]")
        elif isinstance(node, str):
            for c in extract_claims(node):
                src = Source(tool, path, input_hash, c.raw)
                if c.kind == "date":
                    if c.date is not None:
                        self.add_date(c.date, src)
                else:
                    for cand in c.candidates:
                        self.add_number(cand.value, src)
        else:
            v = _dec(node)
            if v is not None:
                self.add_number(v, Source(tool, path, input_hash, str(node)))

    # ---- arama ----
    def _rounded_index(self, d: int, scale: Decimal) -> dict[Decimal, list[Source]]:
        key = (d, scale)
        if key not in self._rounded:
            idx: dict[Decimal, list[Source]] = {}
            q = Decimal(1).scaleb(-d)
            with localcontext() as ctx:
                ctx.prec = 80
                for value, src in self._entries:
                    try:
                        qq = (value / scale).quantize(q, rounding=ROUND_HALF_UP)
                    except InvalidOperation:
                        continue
                    idx.setdefault(qq, []).append(src)
            self._rounded[key] = idx
        return self._rounded[key]

    def _lookup(self, mant: Decimal, d: int, scale: Decimal) -> tuple[str, list[Source]] | None:
        exact = self._exact.get(mant * scale)
        if exact:
            return "EXACT", exact
        hits = [s for s in self._rounded_index(d, scale).get(mant, []) if s not in self._exact.get(mant * scale, [])]
        if hits:
            return ("ROUNDED_COARSE" if d == 0 else "ROUNDED"), hits
        return None

    def find(self, claim: NumberClaim) -> "Match | None":
        best: Match | None = None
        for cand in claim.candidates:
            for relaxed, mant in ((False, cand.mantissa), (True, -cand.mantissa)):
                if relaxed and cand.mantissa == 0:
                    continue
                got = self._lookup(mant, cand.decimals, cand.scale)
                if got is None:
                    continue
                rounding, sources = got
                m = Match(rounding, relaxed, tuple(sources[:3]))
                if best is None or m.order < best.order:
                    best = m
                if not relaxed:
                    break  # bu aday için işaretli eşleşme bulundu; işaret gevşetmeye gerek yok
        return best


@dataclass(frozen=True)
class Match:
    rounding: str          # EXACT | ROUNDED | ROUNDED_COARSE
    sign_relaxed: bool
    sources: tuple[Source, ...]

    @property
    def kind(self) -> str:
        return "SIGN_RELAXED" if self.sign_relaxed else self.rounding

    @property
    def order(self) -> tuple[int, int]:
        return (1 if self.sign_relaxed else 0, _RANK[self.rounding])


# =============================== 4. rapor ===============================
@dataclass
class ClaimResult:
    claim: NumberClaim
    verdict: str
    match_kind: str | None = None          # EXACT | ROUNDED | ROUNDED_COARSE | SIGN_RELAXED | DATE | None
    rounding: str | None = None            # SIGN_RELAXED durumunda altta yatan yuvarlama türü
    sources: list[Source] = field(default_factory=list)
    derivation_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"raw": self.claim.raw, "kind": self.claim.kind, "start": self.claim.start, "end": self.claim.end,
                "verdict": self.verdict, "match_kind": self.match_kind, "rounding": self.rounding,
                "sources": [s._asdict() for s in self.sources], "derivation_hint": self.derivation_hint}


@dataclass
class VerificationReport:
    claims: list[ClaimResult]
    tier2_enabled: bool

    def _n(self, verdict: str) -> int:
        return sum(1 for r in self.claims if r.verdict == verdict)

    @property
    def n_allowlisted(self) -> int:
        return self._n("ALLOWLISTED")

    @property
    def n_allowlisted_policy(self) -> int:
        """Modele gösterilen politika bloğunda (eşik sayıları vb.) geçen ve araç çıktısında bulunmayan sayılar; ayrı sayılır."""
        return self._n("ALLOWLISTED_POLICY")

    @property
    def n_claims(self) -> int:
        return len(self.claims) - self.n_allowlisted - self.n_allowlisted_policy

    @property
    def n_supported(self) -> int:
        return self._n("SUPPORTED")

    @property
    def n_unevidenced(self) -> int:
        return self._n("UNEVIDENCED")

    @property
    def n_hallucinated(self) -> int:
        return self._n("HALLUCINATION")

    @property
    def n_hallucinated_derivable(self) -> int:
        return sum(1 for r in self.claims if r.verdict == "HALLUCINATION" and r.derivation_hint)

    def _matched(self) -> list[ClaimResult]:
        return [r for r in self.claims if r.verdict in ("SUPPORTED", "UNEVIDENCED")]

    @property
    def n_exact(self) -> int:
        return sum(1 for r in self._matched() if r.match_kind == "EXACT")

    @property
    def n_rounded(self) -> int:
        return sum(1 for r in self._matched() if r.match_kind == "ROUNDED")

    @property
    def n_rounded_coarse(self) -> int:
        return sum(1 for r in self._matched() if r.match_kind == "ROUNDED_COARSE")

    @property
    def n_rounded_total(self) -> int:
        return self.n_rounded + self.n_rounded_coarse

    @property
    def n_sign_relaxed(self) -> int:
        return sum(1 for r in self._matched() if r.match_kind == "SIGN_RELAXED")

    @property
    def numerical_hallucination_rate(self) -> float:
        """desteklenmeyen sayı / toplam sayısal iddia (izin listesi paydaya girmez)."""
        return self.n_hallucinated / self.n_claims if self.n_claims else 0.0

    @property
    def unevidenced_rate(self) -> float:
        return self.n_unevidenced / self.n_claims if self.n_claims else 0.0

    def by_raw(self, raw: str) -> ClaimResult:
        return next(r for r in self.claims if r.claim.raw == raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_claims": self.n_claims, "n_allowlisted": self.n_allowlisted,
            "n_allowlisted_policy": self.n_allowlisted_policy, "n_supported": self.n_supported,
            "n_unevidenced": self.n_unevidenced, "n_hallucinated": self.n_hallucinated,
            "n_hallucinated_derivable": self.n_hallucinated_derivable,
            "n_exact": self.n_exact, "n_rounded": self.n_rounded, "n_rounded_coarse": self.n_rounded_coarse,
            "n_rounded_total": self.n_rounded_total, "n_sign_relaxed": self.n_sign_relaxed,
            "numerical_hallucination_rate": self.numerical_hallucination_rate, "unevidenced_rate": self.unevidenced_rate,
            "tier2_enabled": self.tier2_enabled, "claims": [r.to_dict() for r in self.claims],
        }


# =============================== 5. türetilmiş sayı ipucu ===============================
def _fmt(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _derivation_hint(claim: NumberClaim, operands: list[tuple[Decimal, Decimal]]) -> str | None:
    """Hedef sayı, aynı cevaptaki iki DİĞER sayıdan (a/b*100, a/b, (a-b)/b*100, a-b, a+b, a*b) türüyor mu?

    operands: (yazılan, havuzdaki) çiftleri. Hem havuz hem yazılan değerlerle denenir. Yalnızca İPUCU: sayıyı aklamaz."""
    if not claim.candidates:
        return None
    cand = claim.candidates[0]
    q = Decimal(1).scaleb(-cand.decimals)
    target = abs(cand.mantissa)
    ops = (("{a}/{b}*100", lambda a, b: a / b * 100 if b else None), ("{a}/{b}", lambda a, b: a / b if b else None),
           ("({a}-{b})/{b}*100", lambda a, b: (a - b) / b * 100 if b else None),
           ("{a}-{b}", lambda a, b: a - b), ("{a}+{b}", lambda a, b: a + b), ("{a}*{b}", lambda a, b: a * b))
    with localcontext() as ctx:
        ctx.prec = 60
        for variant in (1, 0):  # 1: havuz değerleri, 0: yazılan değerler
            vals = [pair[variant] for pair in operands]
            for i, a in enumerate(vals):
                for j, b in enumerate(vals):
                    if i == j:
                        continue
                    for tmpl, fn in ops:
                        res = fn(a, b)
                        if res is None:
                            continue
                        try:
                            ok = abs(res / cand.scale).quantize(q, rounding=ROUND_HALF_UP) == target
                        except InvalidOperation:
                            continue
                        if ok:
                            expr = tmpl.format(a=_fmt(a), b=_fmt(b))
                            return f"{expr}={format(res.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')}"
    return None


# =============================== 6. ana fonksiyon ===============================
# results dışında, zarfın kendisinde bulunan sayı taşıyan alanlar (havuz yolu: "n_events", "warnings[2]" …)
_ENVELOPE_LEVEL = ("n_events", "n_excluded_incomplete_horizon", "warnings")


def _usable(env: dict[str, Any]) -> bool:
    return (env.get("status") == "OK" and str(env.get("tool")) != BUNDLE_TOOL and isinstance(env.get("results"), dict))


def _text_pool(text: str, tag: str) -> _Pool:
    """Bir metindeki (soru, politika bloğu) sayı ve tarihlerin havuzu; kaynak etiketi `tag`."""
    pool = _Pool()
    for c in extract_claims(text or ""):
        if c.kind == "date":
            if c.date is not None:
                pool.add_date(c.date, Source(tag, "", "", c.raw))
        else:
            for cand in c.candidates:
                pool.add_number(cand.value, Source(tag, "", "", c.raw))
    return pool


def _build_allowlist(question: str, envelopes: Iterable[dict[str, Any]]) -> tuple[set[Decimal], set[date]]:
    pool = _text_pool(question, "question")
    for env in envelopes:
        if str(env.get("tool")) != BUNDLE_TOOL:
            pool.add_tree(env.get("params") or {}, tool="params", input_hash=str(env.get("input_hash", "")))
    return set(pool._exact), set(pool.dates)


def _committed_pool(evidence: list[dict[str, Any]]) -> _Pool:
    pool = _Pool()
    for item in evidence:
        eid = str(item.get("evidence_id", ""))
        h = str(item.get("source_input_hash", ""))
        pool.add_tree(item.get("statement") or "", tool="evidence", input_hash=h, path=f"{eid}.statement")
        for i, v in enumerate(item.get("values") or []):
            pool.add_tree(v.get("value") if isinstance(v, dict) else v, tool="evidence", input_hash=h,
                          path=f"{eid}.values[{i}]")
    return pool


def verify_numbers(text: str, *, envelopes: Iterable[dict[str, Any]], question: str = "",
                   committed_evidence: list[dict[str, Any]] | None = None, policy_text: str = "") -> VerificationReport:
    """Cevap metnindeki sayısal iddiaları denetler.

    envelopes          oturumdaki tüm araç zarfları (yalnızca status=OK ve build_evidence_bundle olmayanlar havuza girer)
    question           kullanıcı sorusu (izin listesi)
    committed_evidence kilitli paketin committed_evidence_set'i; None => 2. seviye (KANITSIZ) kapalı
    policy_text        modele GÖSTERİLEN politika bloğunun metni (etiket, gerekçe kodları, eşik sayıları). Buradaki sayılar araç
                       çıktısında yoksa HALLUCINATION yerine ALLOWLISTED_POLICY olur (ayrı sayılır, paydaya girmez); araç kanıtı
                       her zaman önce gelir. Boş metin => özellik kapalı (D′ ve A–C: model bloğu görmez)
    """
    envs = list(envelopes)
    pool = _Pool()
    for env in envs:
        if _usable(env):
            tool, h = str(env["tool"]), str(env.get("input_hash", ""))
            pool.add_tree(env["results"], tool=tool, input_hash=h)
            # zarf düzeyi alanlar da araç çıktısıdır: model uyarı metnini ("ham laggard ... toplam 398") ve sayaçları alıntılar
            pool.add_tree({k: env[k] for k in _ENVELOPE_LEVEL if env.get(k) is not None}, tool=tool, input_hash=h)
    allow_nums, allow_dates = _build_allowlist(question, envs)
    committed = _committed_pool(committed_evidence) if committed_evidence is not None else None
    policy = _text_pool(policy_text, "policy")
    policy_nums, policy_dates = set(policy._exact), set(policy.dates)

    def by_policy(claim: NumberClaim) -> ClaimResult | None:
        if claim.kind == "date":
            hit = claim.date is not None and claim.date in policy_dates
        else:
            hit = any(c.value in policy_nums for c in claim.candidates)
        return ClaimResult(claim, "ALLOWLISTED_POLICY", sources=[Source("policy", "", "", claim.raw)]) if hit else None

    results: list[ClaimResult] = []
    for claim in extract_claims(text):
        if claim.kind == "date":
            if claim.date is not None and claim.date in allow_dates:
                results.append(ClaimResult(claim, "ALLOWLISTED"))
                continue
            srcs = pool.dates.get(claim.date) if claim.date is not None else None
            in_committed = bool(srcs) and (committed is None or (claim.date in committed.dates))
            if not in_committed:
                rescued = by_policy(claim)
                if rescued is not None:
                    results.append(rescued)
                    continue
            if not srcs:
                results.append(ClaimResult(claim, "HALLUCINATION"))
                continue
            results.append(ClaimResult(claim, "SUPPORTED" if in_committed else "UNEVIDENCED", "DATE",
                                       sources=list(srcs[:3])))
            continue
        if any(c.value in allow_nums for c in claim.candidates):
            results.append(ClaimResult(claim, "ALLOWLISTED"))
            continue
        match = pool.find(claim)
        in_committed = match is not None and (committed is None or committed.find(claim) is not None)
        if not in_committed:
            rescued = by_policy(claim)
            if rescued is not None:
                results.append(rescued)
                continue
        if match is None:
            results.append(ClaimResult(claim, "HALLUCINATION"))
            continue
        results.append(ClaimResult(claim, "SUPPORTED" if in_committed else "UNEVIDENCED", match.kind,
                                   rounding=match.rounding, sources=list(match.sources)))

    # türetilmiş sayı ipucu: yalnızca halüsinasyonlar için, aynı cevaptaki diğer (desteklenen/izinli) sayılardan
    operands: list[tuple[int, tuple[Decimal, Decimal]]] = []
    for idx, r in enumerate(results):
        if r.verdict == "HALLUCINATION" or r.claim.kind == "date" or not r.claim.candidates:
            continue
        written = r.claim.candidates[0].value
        pooled = written
        if r.sources:
            try:
                pooled = Decimal(r.sources[0].value)
            except InvalidOperation:
                pooled = written
        operands.append((idx, (written, pooled)))
    for idx, r in enumerate(results):
        if r.verdict == "HALLUCINATION" and r.claim.kind != "date" and r.claim.candidates:
            others = [pair for i, pair in operands[:40] if i != idx]
            if len(others) >= 2:
                r.derivation_hint = _derivation_hint(r.claim, others)
    return VerificationReport(results, tier2_enabled=committed is not None)


def verify_session(session: Any, text: str) -> VerificationReport:
    """Bir HarnessSession için: oturum zarfları + soru + (kilitliyse) committed_evidence_set + (gösterildiyse) politika bloğu."""
    committed = None
    bundle = getattr(session, "bundle", None)
    if bundle is not None and bundle.locked:
        committed = bundle.snapshot()["committed_evidence_set"]
    return verify_numbers(text, envelopes=[r.envelope for r in session.store.records], question=session.question,
                          committed_evidence=committed, policy_text=getattr(session, "policy_text", "") or "")
