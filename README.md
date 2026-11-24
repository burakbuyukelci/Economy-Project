# CSE-481 — BIST 100 Ajan Tabanlı Finansal Analiz Harness'i ve İnce Ayarlı Yerel LLM

Akdeniz Üniversitesi, CSE-481 Mühendislik Ekonomisi (Dr. Alper Özcan). Eğitim ve araştırma amaçlıdır: **broker bağlantısı, gerçek emir ve kişisel yatırım tavsiyesi yoktur.**

> **LLM yorumlar ve açıklar. Python araçları hesaplar. Harness kontrol eder. Backtest doğrular. Model yerel çalışır.**

Sistem; 30 BIST hissesi için dört zorunlu senaryoyu (sektör catch-up, haftanın günü örüntüsü, teknik dönüş, çeyreklik bilanço ve fiyat tepkisi) ve makro bağlamı (kur–hisse ilişkisi) deterministik araçlarla hesaplar. Küçük bir yerel model (Gemma 3 4B, QLoRA ile ince ayarlı) soruyu anlar, doğru aracı doğru parametreyle çağırır ve **yalnızca araç çıktısındaki sayılara** dayanarak, **yalnızca izinli eylem kümesinden** bir sonuç verir. Bulut yapay zekâ API'si kullanılmaz.

## Değişmez kurallar (özet; tam liste `CLAUDE.md`)
`as_of` sonrası hiçbir veri araca girmez · ufku dolmamış olaylar istatistiğe katılmaz (`n_excluded_incomplete_horizon`) · araçlar çalışma zamanında ağ kullanmaz (veri `data/snapshots/` altında sürümlü) · sayı yalnızca araç çıktısından gelir (sayı doğrulayıcı) · eylem yalnızca `HOLD, WATCH, INVESTIGATE, POTENTIAL_CATCH_UP_CANDIDATE, TECHNICAL_REVERSAL_CANDIDATE, FUNDAMENTAL_IMPROVEMENT_CANDIDATE, REJECT_SIGNAL, ANALYSIS_UNSAFE` · bilanço KAP açıklama tarihine göre hizalanır · aynı girdi → aynı çıktı (`input_hash`).

## Kurulum
Python 3.12 (3.11 uyumlu). Windows örneği:
```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt     # tam sürümler: requirements.lock
.venv\Scripts\python.exe -m pytest -q                               # beklenen: tümü geçer (≈2800 test, ≈3 dk)
```
Ağ yalnızca `scripts/download_*.py` içindedir (veri bir kez indirilir). EVDS (TCMB) için `.env` dosyasına `EVDS_API_KEY` yazın (`.env.example`; **commit edilmez**).

## Dizin yapısı
| Klasör | İçerik |
|---|---|
| `schemas/` | Ortak sözleşme: araç zarfı, parametre/sonuç şemaları, enum'lar (sürüm 1.5.0; `schema_changelog.md`) |
| `config/` | Evren (`universe.csv`: 30 hisse, peer grupları), eşikler (`settings.py`) |
| `data/snapshots/` | Sürümlü veri: fiyat `snap_2026-11-20_v2`, bilanço `fundamentals_2026-11-23_v2`, makro `macro_2026-11-09_v2` |
| `scripts/` | `download_prices.py`, `download_fundamentals.py`, `download_macro.py` (tek ağ erişimi) |
| `tools/` | 12 deterministik araç (+ harness içinde `build_evidence_bundle`) (gösterge, olay tespiti, destek/direnç, sektör sıralaması, haftanın günü, bilanço, makro + `relate_to`, backtest, veri kalitesi) |
| `harness/` | Durum makinesi (§23), kalite kapısı, kanıt paketi, sayı doğrulayıcı, eylem koruması, etiket politikası, MCP sunucusu, Ollama istemcisi |
| `training/` | Eğitim verisi üretimi (`build_dataset`), kurallar (`RULES.md`), Colab/Kaggle QLoRA betiği ve not defterleri |
| `experiments/` | A–E deney koşucusu, canlı demo (`ask`), karar kaydı ve tekrar oynatma (`replay`), Kaggle/Colab değerlendirme not defterleri |
| `tests/` | Birim, sözleşme, `as_of` sızıntı, ufku dolmamış olay, determinizm, genelleme testleri |
| `docs/` | Veri sözlüğü, harness tasarımı, araç kılavuzu, rapor taslağı ve sınırlamalar (`docs/report/`) |

## Hızlı kullanım
**Tek soru, yerel model (Ollama gerekir; modeli kurmak için `training/README.md` bölüm 4):**
```
python -m experiments.ask --model gemma3-bist-v23 --as-of 2026-09-10 --record reports/q5.json --log reports/q5.jsonl ^
  --question "Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın EREGL alayım mı? Hedef fiyat ver."
python -m experiments.replay reports/q5.json        # kayıtlı oturumu yeniden oynat: araç hash'leri, etiket, kanıt kilidi birebir aynı mı?
```
`ask` çıktısı: araç/durum izi, nihai cevap (`EYLEM:` satırı dahil), sayı/kural denetimi (halüsinasyon, kanıtsız sayı, ihlal), karar günlüğü. Profil `--profile A..E` (varsayılan D). İnsan incelemesi (profil E): `--review APPROVED|REJECTED --reviewer ad --reason "…"`.

**Modelsiz örnek zincirler** (öğretmen betiği, gerçek araçlar, 5 örnek soru): `python -m experiments.sample_runs` → `docs/sample_runs/`.

**Araçları doğrudan çağırmak:**
```python
from tools import get_macro_context
get_macro_context.run({"start": "2024-01-01", "end": "2026-09-10", "as_of": "2026-09-10", "series": ["USDTRY"],
                       "relate_to": [{"ticker": "EREGL", "macro_series": "USDTRY", "horizon": 5, "lag_days": 0, "split_date": "2026-01-01"}]})
```

## Eğitim ve değerlendirme (özet)
1. Veri: `python -m training.build_dataset --out data/training/v2_2` (600/50/100 oturum; yalnızca gerçek v2 araç çıktıları; etiket politikadan).
2. Eğitim (GPU): `training/kaggle/train_qlora_kaggle.ipynb` (Kaggle T4) ya da `training/colab/train_qlora.ipynb`. Paket: `python -m training.colab.make_bundle --data data/training/v2_2 --out colab_bundle.zip`.
3. Yerel kurulum: GGUF → `ollama create gemma3-bist-v23 -f training/ollama/Modelfile.v23` (nihai model v2.3) → `python -m experiments.check_template` (şablon denetimi zorunlu).
4. Değerlendirme: `experiments/kaggle/eval_ollama_kaggle.ipynb` (A–E × temel/ince ayarlı model). Metrikler: sayısal halüsinasyon, hatalı araç çağrısı, kanıtsız sonuç, kural ihlali, tekrarlanabilirlik.
Ayrıntı: `training/README.md`, `docs/harness_design.md` §14.

**Sonuç özeti** (nihai model v2.3; 40 test sorusu, A–E, Kaggle T4; tablolar `python -m experiments.eval_tables reports/eval_v2_3`): D profilinde teslim edilen cevap temel modelde 1/40, ince ayarlıda **30/40**; D/E'de teslim edilen cevaplarda sayı halüsinasyonu **%0**, kural ihlali **%0**, etiket = politika **%100**. Zayıf yönler: ~%25 oturum tur sınırında güvenle kesilir, canlı tekrarlanabilirlik %47, korumasız profillerde (B/C) model tek başına güvenilir değildir (`docs/report/report_draft.md` §9, `limitations.md` L35, L46–L49).

## Belgeler
`CLAUDE.md` (kurallar) · `docs/hoca_qa.md` (hoca açıklamaları, proje dokümanından önceliklidir) · `docs/data_dictionary.md` (her veri seti ve araç) · `docs/harness_design.md` · `docs/tool_usage_guide.md` · `docs/report/report_draft.md` ve `docs/report/limitations.md` (**bilinen sınırlamalar tek yerde**) · `reports/` (senaryo raporları).

## Bilinen sınırlamalar (kısa; tam liste `docs/report/limitations.md`)
Haber/KAP ve konuşma araçları yok · makro için politika faizi yok (TCMB fonlama maliyeti kullanılır) · bilanço verisi Yahoo kaynaklı ve KAP'a karşı doğrulanmamıştır · eğitimde aday etiketlerin (catch-up, bilanço iyileşmesi) örneği yok · küçük örneklem ve çoklu test riski (uyarı olarak raporlanır). Çıktılar **geçmiş kanıttır; gelecek getiri garantisi ve yatırım tavsiyesi değildir.**
