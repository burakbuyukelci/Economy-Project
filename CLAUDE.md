# CSE-481 — Integrated BIST 100 Agentic Financial Analytics Harness

İki kişilik ekip ödevi (Akdeniz Üniversitesi, Dr. Alper Özcan). Eğitim/araştırma amaçlıdır; broker bağlantısı, gerçek emir, kişisel yatırım tavsiyesi YOKTUR.

## Kaynak dokümanlar (önce bunları oku)
- `docs/proje_dokumani.txt` — resmi proje dokümanı (PDF'in metni). Bölüm numaraları aşağıda buna atıf yapar.
- `docs/hoca_qa.md` — hocanın ek açıklamaları ve "kendi LLM'ini geliştir" duyurusu. **Proje dokümanıyla çelişirse bu dosya geçerlidir.**
- `docs/ornek_test_sorulari.txt` — canlı testte sorulacak soruların örnekleri. Final test: benzer ama FARKLI hisse/sektör/tarihler.

## Temel ilke
LLM yorumlar ve açıklar. Python araçları hesaplar. Harness kontrol eder. Backtest doğrular. Model yerel çalışır.
Notlandırma = fine-tune edilmiş yerel LLM'in canlı testi. Ölçülenler: sayısal halüsinasyon, hatalı araç çağrısı, kanıtsız sonuç, kanıt bütünlüğü/tekrarlanabilirlik, kural ihlali, look-ahead bias.

## DEĞİŞMEZ KURALLAR (her kod değişikliğinde uy)
1. **`as_of` kuralı:** Her araç `as_of` (analiz tarihi) parametresi alır. `as_of` sonrası hiçbir fiyat/bilanço/makro/haber satırı araca GİREMEZ (veri katmanında kesilir, `enforce_as_of()` ile). Karar günü t, t+1 bilgisini kullanamaz (signal shifting).
2. **Ufku dolmamış olaylar:** İleri getiri ufku (1/3/5/10/20 gün) `as_of` sonrasına taşan olaylar o ufkun istatistiğine katılmaz. Çıktıda `n_excluded_incomplete_horizon` olarak raporlanır.
3. **Araçlar çalışma zamanında ağ kullanmaz.** Veri `scripts/download_*.py` ile bir kez indirilir, `data/snapshots/` altında sürümlenir (parquet/CSV + `data_version`). Araçlar yalnızca snapshot'tan okur.
4. **Final sistemde bulut AI API'si yok** (OpenAI/Anthropic/Google vb.). Model yerelde çalışır (Ollama / llama.cpp / vLLM / HF Transformers).
5. **Yatırım tavsiyesi ve hedef fiyat yok.** Çıktı eylemi yalnızca şu enum'dan olabilir:
   `HOLD, WATCH, INVESTIGATE, POTENTIAL_CATCH_UP_CANDIDATE, TECHNICAL_REVERSAL_CANDIDATE, FUNDAMENTAL_IMPROVEMENT_CANDIDATE, REJECT_SIGNAL, ANALYSIS_UNSAFE`.
   Kalite kapısı çıktıları: `PASS, PASS_WITH_WARNINGS, INVESTIGATE, ANALYSIS_UNSAFE, HARD_BLOCK`.
6. **Sayılar yalnızca araç çıktısından gelir.** Açıklamada araç çıktısında bulunmayan sayı yazılamaz (sayı doğrulayıcı bunu denetler).
7. **Bilanço verisi KAP açıklama tarihine (`disclosure_date`) göre hizalanır**, dönem sonuna göre değil. Ana analiz TMS 29 sonrası dönemler (2025 ve sonrası) içindir; öncesi için karşılaştırılamazlık uyarısı verilir. Banka için sanayi oranları kullanılmaz.
8. **Determinizm:** Aynı girdi → aynı çıktı. Rastgelelik varsa sabit seed. Her araç çıktısına `input_hash` konur.
9. **Veri dokümantasyonu:** Her veri seti için kaynak, tarih aralığı, uygulanan düzeltme (adjusted/unadjusted), eksik veri yönetimi `docs/data_dictionary.md` içine yazılır.
10. **Dürüstlük:** Az olay (`n_events` < `MIN_EVENTS`, config'te, varsayılan 20 — ekip değiştirebilir), tek hisseli sektör, eksik makro veri, örneklem dışı bozulma → `warnings` alanında açıkça yazılır. "Kesin yükselir/iyi bilanço = fiyat artar" gibi nedensellik iddiası üretilmez.
11. Çoklu test riski, örneklem içi/dışı ayrımı ve işlem maliyeti her örüntü testinde raporlanır.
12. **Eğitim verisi yalnızca v2 snapshot'tan üretilir.** Eğitim kayıtlarındaki `data_version` v2 olmalıdır (`snap_2026-11-20_v2`); v1'den üretilen çıktı geçersizdir ve eğitim setine alınmaz. Eğitim verisinin harness'e özgü diğer kuralları (OOS `split_date` kuralı, etiketin `label_policy`'den gelmesi, doğrulama) için `training/RULES.md`'ye bak.
13. **Her oturum `git pull --rebase` ve `pytest` ile başlar.** Testler geçmeden yeni işe başlanmaz.
14. **Force push yasaktır.**
15. **Hızlı kip:** (a) Mekanik işlerde (sözleşmeye göre araç yazmak, test, dokümantasyon, tekrar eden desen) kısa plan yaz ama onay BEKLEME, hemen başla. (b) Şu durumlarda DUR ve sor: `schemas/`, `config/` veya `CLAUDE.md` değişikliği gerekiyor; sonuçları veya etiketi etkileyen, makul iki alternatifi olan bir tasarım kararı; bir hata iki denemede çözülmüyor; değişmez kurallardan biriyle çelişki; kullanıcının sağlaması gereken veri/anahtar/ağ. (c) `pytest` yeşil ve `git pull --rebase` temiz ise kendi bölgendeki commit'leri sormadan push et (force yok). Dal birleştirme ve paylaşılan bölge değişikliği yine onay ister. (d) Her iş sonunda tek kısa rapor: ne yapıldı, gerçek değerler, kararlar/varsayımlar, testler, push edilenler.

## Araç sözleşmesi (`schemas/`)
Tüm araçlar aynı zarfı döndürür:
```json
{
  "tool": "rank_sector_relative_strength",
  "params": {"sector": "Retail Trade", "horizon": 20, "as_of": "2026-09-10"},
  "as_of": "2026-09-10",
  "data_version": "snap_2026-11-20_v1",
  "input_hash": "…",
  "results": {},
  "n_events": null,
  "n_excluded_incomplete_horizon": 0,
  "warnings": [],
  "status": "OK"
}
```
Araçlar (proje dokümanı §22): get_stock_history, get_index_history, calculate_indicators, detect_reversal_events, find_support_resistance, rank_sector_relative_strength, test_weekday_pattern, get_fundamental_metrics, calculate_fundamental_change, get_macro_context, get_news_events, get_speech_features, run_backtest, check_data_quality, build_evidence_bundle.
`schemas/` klasörünü insan onayı olmadan DEĞİŞTİRME; iki bilgisayar bu sözleşmeye göre paralel çalışır.

## Repo yapısı
```
CLAUDE.md
docs/                 kaynak dokümanlar + data_dictionary.md
schemas/              ortak JSON/pydantic sözleşmesi, enum'lar  (ORTAK — birlikte değişir)
config/               universe.csv, sector/peer map, MIN_EVENTS vb.  (ORTAK)
data/snapshots/       indirilmiş, sürümlü veri
scripts/              download_*.py (tek ağ erişimi olan yer)
tools/                deterministik araçlar              ← BİLGİSAYAR 1
harness/              MCP sunucusu, durum makinesi, evidence, gate, memory, log/replay   ← BİLGİSAYAR 2
training/             eğitim verisi üretimi, QLoRA, değerlendirme   ← BİLGİSAYAR 2
experiments/          A–E harness deneyleri
reports/              senaryo raporları
tests/
```
- **Bilgisayar 1** (`tools/`, `scripts/`, snapshot): veri, indikatörler, olay tespiti, sektör, haftanın günü, backtest, bilanço/makro yükleme.
- **Bilgisayar 2** (`harness/`, `training/`, `experiments/`): MCP sunucusu, mock araçlar, durum makinesi, evidence/gate/log, sayı doğrulayıcı, eğitim verisi, fine-tune, değerlendirme.
Kendi bölgenin dışındaki dosyaları değiştirme; gerekirse bana söyle.

## Çalışma biçimi (Claude Code için)
- Bana **Türkçe** cevap ver; kod, değişken ve dosya adları İngilizce. Yorumlar kısa ve Türkçe olabilir.
- Büyük bir iş başlamadan önce **kısa bir plan çıkar ve onayımı bekle.**
- Her modülün sonunda, ne yaptığını ve neden yaptığını **somut bir örnekle** (gerçek değişken değerleriyle, adım adım) açıkla. Biz öğrenciyiz ve sunumda her satırı savunmamız gerekecek; anlamadığımız kod istemiyoruz.
- Önce test, sonra kod mantığıyla çalış: özellikle look-ahead testleri (`as_of` sonrası veri sızıntısı), ufku dolmamış olay testi, determinizm testi yaz. `pytest` ile çalıştır.
- Küçük ve sık commit at. Sır/anahtar (EVDS API key vb.) commit'leme; `.env` kullan ve `.gitignore`'a ekle.
- İndikatörleri (KAMA, Supertrend, Ichimoku, Bollinger, RSI…) kendin yaz ve açıkla; varsa bir kütüphaneyle çapraz doğrulama testi ekle.
- Emin olmadığın veri kaynağı/seri kodu varsa tahmin etme, bana sor.
