"""Makro veri indirici: TCMB EVDS -> data/snapshots/macro_<tarih>_v<N>/ (AĞ KULLANAN TEK YER; araç çalışma zamanında ağ kullanmaz).

Anahtar: `.env` içindeki EVDS_API_KEY (commit edilmez; ekrana/log'a ASLA yazılmaz). Seri kodları aşağıdaki SERIES tablosundadır.
DOĞRULANMAMIŞ kodu tahmin etmeyiz: TCMB_POLICY_RATE kodu verilmeden indirilmez (`.env` -> EVDS_CODE_TCMB_POLICY_RATE).
Önce `python -m scripts.download_macro --verify` ile her serinin EVDS'de yanıt verdiğini kontrol edin.

Kullanım:
  python -m scripts.download_macro --list-series repo      # seri kodu keşfi (politika faizi kodunu bulmak için)
  python -m scripts.download_macro --verify
  python -m scripts.download_macro --date 2026-11-21 [--start 2023-01-01]

Yayın tarihi (publication_date) EVDS'de YOKTUR; sabit kurallarla türetilir (docs/data_dictionary.md §22):
  USDTRY/EURTRY/TCMB_POLICY_RATE: gözlem günü (TCMB gösterge kuru 15:30'da, faiz karar günü açıklanır).
  CPI_*: referans ayı izleyen ayın 3'ü (hafta sonuna denk gelirse sonraki iş günü; resmî tatil dikkate ALINMAZ).
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from config.settings import REPO_ROOT, SNAPSHOT_DIR

MACRO_VERSION_RE = re.compile(r"^macro_\d{4}-\d{2}-\d{2}_v\d+$")
EVDS_BASE_DEFAULT = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"  # DOĞRULANACAK: EVDS_BASE_URL ile değiştirilebilir
COLUMNS = ["series", "observation_date", "publication_date", "value"]

FUNDING_COST_NOTE = (
    "TCMB'nin fiili ağırlıklı ortalama fonlama maliyetidir (EVDS veri grubu bie_apifon, TP.APIFON4, günlük iş günü, %); politika faizi değil. "
    "EVDS notu: Toplam fonlamanın gerçekleşmediği günlerde AOFM verisi olarak bir hafta repo faiz oranı kullanılmaktadır. "
    "Mart-Ağustos 2026'da bir hafta vadeli repo ihaleleri ara verildiği için seri o dönemde %40'ta kalmıştır.")

# series -> EVDS kodu, formül (EVDS formulas: 1 = bir önceki döneme göre % değişim, 3 = yıllık % değişim), sıklık, açıklama
SERIES: dict[str, dict] = {
    "USDTRY": {"code": "TP.DK.USD.A.YTL", "formulas": None, "frequency": "daily", "desc": "USD/TRY döviz alış (gösterge kur)"},
    "EURTRY": {"code": "TP.DK.EUR.A.YTL", "formulas": None, "frequency": "daily", "desc": "EUR/TRY döviz alış (gösterge kur)"},
    # TÜFE: güncel seri 2025=100 bazlıdır (EVDS veri grubu bie_tukfiy2025). Eski TP.FG.J0 (2003=100) arşivlidir: 2023 sonrası 0 gözlem verir.
    "CPI_MONTHLY": {"code": "TP.TUKFIY2025.GENEL", "formulas": 1, "frequency": "monthly", "desc": "TÜFE genel endeks (2025=100), aylık % değişim"},
    "CPI_ANNUAL": {"code": "TP.TUKFIY2025.GENEL", "formulas": 3, "frequency": "monthly", "desc": "TÜFE genel endeks (2025=100), yıllık % değişim"},
    "TCMB_POLICY_RATE": {"code": None, "formulas": None, "frequency": "daily", "desc": "TCMB politika faizi (1 hafta repo) — KOD DOĞRULANMADI, İNDİRİLMEZ"},
    "TCMB_FUNDING_COST": {"code": "TP.APIFON4", "formulas": None, "frequency": "daily", "desc": "TCMB ağırlıklı ortalama fonlama maliyeti (%)",
                          "note": FUNDING_COST_NOTE},
}


# --- .env (bağımlılıksız, anahtarı yazdırmaz) ---------------------------------------------------------
def load_env(path: Path | None = None) -> None:
    p = path or (REPO_ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def series_code(name: str) -> str | None:
    return os.environ.get(f"EVDS_CODE_{name}") or SERIES[name]["code"]


# --- saf mantık (testlerde sınanır) ------------------------------------------------------------------
def parse_obs_date(s: str) -> date:
    """EVDS tarih biçimleri: 'dd-mm-yyyy' (günlük), 'yyyy-m' (aylık), 'yyyy-mm-dd'. Aylık -> AY SONU (referans ayı)."""
    s = s.strip()
    if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{4}", s):
        return datetime.strptime(s, "%d-%m-%Y").date()
    if re.fullmatch(r"\d{4}-\d{1,2}", s):
        y, m = (int(x) for x in s.split("-"))
        return (pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0)).date()
    return date.fromisoformat(s)


def publication_date(series: str, obs: date) -> date:
    if series.startswith("CPI_"):
        first_next = (pd.Timestamp(obs) + pd.offsets.MonthBegin(1))  # izleyen ayın 1'i
        d = first_next + timedelta(days=2)  # 3'ü
        while d.weekday() >= 5:  # hafta sonu -> sonraki iş günü (resmî tatil dikkate alınmaz)
            d += timedelta(days=1)
        return d.date()
    return obs


def parse_items(items: list[dict], series: str) -> pd.DataFrame:
    """EVDS 'items' listesi -> (series, observation_date, publication_date, value). Boş/'None' değerler atılır.

    Değer sütunu: 'Tarih' ve 'UNIXTIME' dışındaki TEK sütun (EVDS sütun adı kodun '_'li hâlidir; formül sonekli olabilir)."""
    rows = []
    for it in items:
        vals = [(k, v) for k, v in it.items() if k not in ("Tarih", "UNIXTIME")]
        if len(vals) != 1:
            raise ValueError(f"{series}: beklenmeyen EVDS satırı sütunları {sorted(it)}")
        v = vals[0][1]
        if v is None or str(v).strip() in ("", "None", "null"):
            continue
        obs = parse_obs_date(str(it["Tarih"]))
        rows.append({"series": series, "observation_date": pd.Timestamp(obs), "publication_date": pd.Timestamp(publication_date(series, obs)),
                     "value": float(v)})
    return pd.DataFrame(rows, columns=COLUMNS)


def write_macro_snapshot(df: pd.DataFrame, root: Path, version: str, meta: dict) -> Path:
    if not MACRO_VERSION_RE.match(version):
        raise ValueError(f"sürüm biçimi macro_YYYY-MM-DD_vN olmalı: {version}")
    d = Path(root) / version
    if d.exists():
        raise FileExistsError(f"{d} zaten var (snapshot'lar değişmez; yeni sürüm numarası kullanın)")
    d.mkdir(parents=True)
    out = df.sort_values(["series", "observation_date"]).reset_index(drop=True)
    out.to_parquet(d / "macro.parquet", index=False)
    info = {s: {"source": "TCMB/EVDS", "frequency": SERIES[s]["frequency"], "evds_code": series_code(s), "formulas": SERIES[s]["formulas"],
                "n_points": int((out["series"] == s).sum()), **({"note": SERIES[s]["note"]} if "note" in SERIES[s] else {}),
                "last_observation_date": str(out.loc[out["series"] == s, "observation_date"].max().date()) if (out["series"] == s).any() else None}
            for s in SERIES}
    manifest = {"data_version": version, "n_rows": int(len(out)), "series": info,
                "publication_rule": "FX/faiz: gözlem günü; TÜFE: izleyen ayın 3'ü (hafta sonu -> sonraki iş günü), resmî tatil yok sayılır", **meta}
    with open(d / "manifest.json", "w", encoding="utf-8", newline="\n") as fh:  # LF zorunlu (Windows)
        fh.write(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n")
    with open(Path(root) / "LATEST_MACRO", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(version + "\n")
    return d


# --- seri arama (saf yardımcılar; testlerde sınanır) -------------------------------------------------
_TR = str.maketrans({"İ": "i", "I": "i", "ı": "i", "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ö": "o", "Ö": "o", "ş": "s", "Ş": "s",
                     "ü": "u", "Ü": "u"})


def fold(s: object) -> str:
    """Türkçe harfleri ASCII'ye indirip küçültür: 'Politika Faizi' ~ 'politika faizi', 'İHALE' ~ 'ihale'."""
    return str(s).translate(_TR).lower()


def match_items(items: list[dict], keyword: str, fields: tuple[str, ...]) -> list[dict]:
    """`fields` alanlarından herhangi birinde (katlanmış) anahtar kelimeyi içeren öğeler. Boş anahtar -> hepsi."""
    k = fold(keyword)
    return [it for it in items if any(k in fold(it.get(f, "")) for f in fields)]


def describe_series(it: dict) -> str:
    """Bir serieList öğesi için tek satır: kod | ad | sıklık | başlangıç. Anahtar alanlar yoksa mevcut alan adlarını gösterir."""
    code, name = it.get("SERIE_CODE"), it.get("SERIE_NAME")
    if code is None and name is None:
        return f"(beklenmeyen alanlar: {sorted(it)})"
    return f"{code} | {name} | {it.get('FREQUENCY_STR', '?')} | {it.get('START_DATE', '?')}"


# --- ağ ----------------------------------------------------------------------------------------------
def evds_get(path: str) -> list | dict:  # pragma: no cover - ağ
    """Anahtarlı GET (anahtar başlıkta; ASLA yazdırılmaz). Hata durumunda yalnızca HTTP kodu yazılır."""
    import requests
    key = os.environ.get("EVDS_API_KEY", "").strip()
    if not key:
        raise SystemExit("EVDS_API_KEY yok: .env dosyasına yazın (bkz. .env.example)")
    base = os.environ.get("EVDS_BASE_URL", EVDS_BASE_DEFAULT).rstrip("/") + "/"
    r = requests.get(base + path, headers={"key": key}, timeout=60)
    if r.status_code != 200:
        raise SystemExit(f"EVDS HTTP {r.status_code} ({path.split('&')[0]}); anahtar/adres kontrol edin (yanıt gövdesi yazdırılmadı)")
    return r.json()


def list_series(keyword: str, max_groups: int = 8, max_series: int = 40) -> None:  # pragma: no cover - ağ
    """EVDS veri gruplarında anahtar kelimeyi arar; eşleşen gruplarda seri kodlarını listeler (kod keşfi için).

    Örn. `--list-series repo`: ad/kategori 'repo' içeren veri grupları ve içlerindeki SERIE_CODE'lar (politika faizi kodunu bulmak için)."""
    groups = evds_get("datagroups/mode=0&type=json")
    if isinstance(groups, dict):
        groups = groups.get("items", [])
    hits = match_items(groups, keyword, ("DATAGROUP_NAME", "DATAGROUP_NAME_ENG", "TOPIC_TITLE_TR", "CATEGORY_NAME"))
    if not hits:
        print(f"'{keyword}': veri grubu bulunamadı ({len(groups)} grup tarandı)")
        return
    print(f"'{keyword}': {len(hits)} veri grubu eşleşti (ilk {min(max_groups, len(hits))} gösteriliyor)")
    for g in hits[:max_groups]:
        gcode = g.get("DATAGROUP_CODE")
        print(f"\n== {gcode} | {g.get('DATAGROUP_NAME')}")
        ser = evds_get(f"serieList/type=json&code={gcode}")
        ser = ser.get("items", []) if isinstance(ser, dict) else ser
        for it in ser[:max_series]:
            print("  " + describe_series(it))
        if len(ser) > max_series:
            print(f"  (+{len(ser) - max_series} seri daha)")


def fetch_series(name: str, start: date, end: date) -> list[dict]:  # pragma: no cover - ağ
    import requests
    key = os.environ.get("EVDS_API_KEY", "").strip()
    if not key:
        raise SystemExit("EVDS_API_KEY yok: .env dosyasına yazın (bkz. .env.example)")
    code = series_code(name)
    if not code:
        raise SystemExit(f"{name}: seri kodu doğrulanmadı; .env içine EVDS_CODE_{name}=... yazın")
    base = os.environ.get("EVDS_BASE_URL", EVDS_BASE_DEFAULT).rstrip("/") + "/"
    params = {"series": code, "startDate": start.strftime("%d-%m-%Y"), "endDate": end.strftime("%d-%m-%Y"), "type": "json"}
    if SERIES[name]["formulas"]:
        params["formulas"] = SERIES[name]["formulas"]
    r = requests.get(base + "&".join(f"{k}={v}" for k, v in params.items()), headers={"key": key}, timeout=60)
    if r.status_code != 200:
        raise SystemExit(f"{name}: EVDS HTTP {r.status_code} (anahtar/kod/adres kontrol edin; yanıt gövdesi yazdırılmadı)")
    return r.json().get("items", [])


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - ağ
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--version-no", type=int, default=1)
    ap.add_argument("--verify", action="store_true", help="her seriden son 30 günü çek, satır sayısını yaz (yazmaz)")
    ap.add_argument("--list-series", metavar="ANAHTAR", help="EVDS veri gruplarında ara ve seri kodlarını listele (örn. repo, politika)")
    a = ap.parse_args(argv)
    load_env()
    if a.list_series:
        list_series(a.list_series)
        return
    end = date.fromisoformat(a.date)
    if a.verify:
        for name in SERIES:
            if not series_code(name):
                print(f"{name}: KOD YOK (atlandı)")
                continue
            window = 45 if SERIES[name]["frequency"] == "daily" else 120  # aylık gözlem ayın 1'ine damgalı: kısa pencere 0 satır döner
            items = fetch_series(name, end - timedelta(days=window), end)
            df = parse_items(items, name)
            print(f"{name}: {len(df)} gözlem; son: {df['observation_date'].max().date() if len(df) else '-'}; kod {series_code(name)}")
        return
    frames, notes = [], []
    for name in SERIES:
        if not series_code(name):
            notes.append(f"{name}: seri kodu verilmedi, indirilmedi")
            print(notes[-1])
            continue
        df = parse_items(fetch_series(name, date.fromisoformat(a.start), end), name)
        frames.append(df)
        print(f"{name}: {len(df)} gözlem")
    all_ = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    d = write_macro_snapshot(all_, SNAPSHOT_DIR, f"macro_{a.date}_v{a.version_no}", {"created": a.date, "start": a.start, "notes": notes})
    print(f"yazıldı: {d} ({len(all_)} satır)")


if __name__ == "__main__":  # pragma: no cover
    main()
