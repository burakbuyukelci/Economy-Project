# Araç kullanım kılavuzu (model ve eğitim verisi için)

Bu kılavuz, modelin MCP araçlarını nasıl çağırması gerektiğini özetler. Araç açıklamaları (`harness/mcp_server.py`) ve eğitim verisi kuralları (`training/RULES.md`) bununla tutarlıdır.
Ayrıntı ve gerekçeler: `docs/harness_design.md`. Çelişkide `docs/hoca_qa.md` ve `CLAUDE.md` geçerlidir.

## 1. Her çağrıda
* `as_of` ZORUNLUDUR ve sorudaki analiz tarihine eşit olmalıdır (aksi halde `AS_OF_MISMATCH`: geçersiz çağrı).
* Parametreleri uydurma: hisse/sektör/dönem sorudan gelir. Belirsizse (`ticker`/`sector` yok) çağrı `TICKER_UNDETERMINED` ile reddedilir.
* Kalite kapısı ve kanıt paketini model çağırmaz; harness çalıştırır (`HARNESS_ONLY_TOOL`).

## 2. Örneklem dışı (OOS) başlangıcı: `split_date` KURALI
Aday etiketler (`POTENTIAL_CATCH_UP_CANDIDATE`, `TECHNICAL_REVERSAL_CANDIDATE`) örneklem içi/dışı doğrulama ister. Bu yüzden OOS başlangıcı **her zaman**:

> **as_of yılının 1 Ocak'ı** (örn. as_of 2026-09-10 -> `2026-01-01`) **ya da sorudaki OOS başlangıcı** (soru bir OOS dönemi verdiyse o).

| Araç | Nerede verilir |
|---|---|
| `rank_sector_relative_strength` | `split_date` |
| `detect_reversal_events` | `split_date` |
| `test_weekday_pattern` | `out_of_sample_start` (IS bitişi OOS başlangıcından önce olmalı; soruda "2024–2025 / 2026" gibi verilir) |
| `run_backtest` | `strategy.train_end` = OOS başlangıcından **bir gün önce** (TEST dilimi OOS'tur) |

`split_date` verilmezse araç IS/OOS üretmez; etiket politikası (`harness/label_policy.py`) aday etiket vermez ve `INVESTIGATE` döndürür; gerekçe: **"OOS doğrulaması yapılmadı"**.
(Tarihsel doğrulaması zaten başarısızsa — isabet çoğu ufukta bazın altında — politika yine `REJECT_SIGNAL` verir; OOS eksikliği reddi engellemez.)

## 3. Etiket modelin değil politikanındır
Harness, kilitli kanıt paketi ve kapı sonucundan izinli etiketi hesaplar (`docs/harness_design.md` bölüm 11). Model:
* nihai çıktıya **tam bir** `EYLEM: <ETİKET>` satırı yazar; etiket politikanınkiyle AYNI olmalıdır (aksi halde `ACTION_MISMATCH_REQUIRED`);
* etiketi **gerekçelendiren** sayıları yalnızca committed kanıttaki araç çıktılarından alır, sayı türetmez (türetilmiş sayı = halüsinasyon);
* aday etiketlerde "tarihsel gözlem, örnek küçük, belirsizlik var" notunu açıklamasına yansıtır; yatırım tavsiyesi/hedef fiyat vermez.

## 4. Tavsiye isteyen sorular
"Alayım mı?", "hedef fiyat ver", "kesin yükselir" gibi sorularda tavsiye verilmez; politika aday etiketleri `WATCH`'a indirir, senaryo aracı yoksa `INVESTIGATE` verir.
Kullanıcının kesinlik iddiası ("kesin yükselir") araç çıktısıyla doğrulanamıyorsa bu açıkça söylenir.
