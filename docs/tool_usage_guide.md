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

## 5. Göstergeler (`calculate_indicators`): hafif varsayılanlar (şema 1.2.0)
Varsayılan çıktı küçüktür; bağlam penceresini ve hash'i gereksiz büyütmemek için **ihtiyacın kadarını iste**:
* `last_n_rows` varsayılanı **0** (son satırlar gelmez). `latest` bölümü (as_of günü değerleri ve durumlar) her zaman gelir ve kanıtın başlığıdır. Son günlerin seyri gerekiyorsa `last_n_rows` ver (en çok 30; yalnızca gereken kadar); `recent_rows` kanıta girmez, yalnızca modele görünür.
* `include_columns_meta` varsayılanı **False** (kolon açıklamaları yok). Kolon anlamı gerekmedikçe açma.
* `value_columns` ile yalnızca gereken kolonları seç (örn. `["RSI_14", "BB_LOWER_20_2.0"]`); bilinmeyen ad `INVALID_PARAMS` verir ve mesajda geçerli adlar yazar.
* `invalid_columns_at_as_of`: as_of gününde değeri hesaplanamayan (ısınma) kolonlar; bunlar için sayı yazma.

## 6. `rank_sector_relative_strength`: havuz ve hisse bazlı kırılım (şema 1.2.0)
Tarihsel catch-up sayıları iki düzeydedir ve karıştırılmamalıdır:
* **Havuz** (`historical_catch_up`): grubun tüm üyelerinin bağımsız olayları birlikte. `n_raw_laggard_observations` = cooldown ÖNCESİ ham hisse-günü (örn. 398), `n_independent_events` = cooldown (`cooldown_days`) sonrası kabul edilen olay (örn. 44).
* **Hisse bazlı** (`per_ticker`): her hissenin kendi payı (örn. BIMAS 9, MAVI 21, MGROS 14; toplam 44). Soruda tek bir hisse varsa o hissenin sayısı yazılır; havuz sayısı o hissenin olay sayısı diye sunulmaz.
* Sonuç ölçütü (`outcome_benchmark_definition`): peer medyanı, değerlendirilen hisse HARİÇ. Hisse bazlı bloklarda IS/OOS yoktur (hisse başına 9–21 olay bölünemez); IS/OOS yalnızca havuz bloğundadır.
* Sayıları aynen kullan: ham ve bağımsız sayıyı toplama/oranlama; türetilmiş sayı halüsinasyon sayılır.

## 7. `test_weekday_pattern` ve çoklu test
Örüntü (kaç gün içerirse içersin) tek bir hipotezdir ve tek bir p-değeri üretir; `n_tests_declared` varsayılanı 1'dir. Aynı oturumda aynı hisse/dönem için başka örüntüler de denendiyse (farklı gün kombinasyonları, farklı yönler, conditioning varyantları) `n_tests_declared` denenen toplam örüntü sayısına ayarlanmalıdır; araç önceki denemeleri bilemez. `p_value_adjusted = min(1, p_value_raw × n_tests_declared)` ve karar bu değere dayanır. Her zarfta `MULTIPLE_TESTING_RISK` uyarısı bulunur; açıklamada bu risk anılmalıdır.

## 8. `get_macro_context` ve `relate_to` (şema 1.5.0)
Makro serileri (`USDTRY`, `EURTRY`, `TCMB_FUNDING_COST`, `CPI_*`) için `series` ver; "kur ile hisse getirisi arasındaki ilişki" soruları için `relate_to` ZORUNLUDUR (ilişkiyi araç hesaplar, sen hesaplama).
* Kur için iki ilişki iste: `lag_days` 0 (eş zamanlı) ve `lag_days` 5 (öncü: kur hisseden önce bilinir); `horizon` 5; `split_date` OOS kuralı (as_of yılının 1 Ocak'ı ya da sorudaki OOS başlangıcı); `n_tests_declared` = ilişki sayısı.
* Faiz için `TCMB_FUNDING_COST` ve `transform: LEVEL_DIFF`. **Bu seri politika faizi DEĞİLDİR**, TCMB'nin fiili ağırlıklı ortalama fonlama maliyetidir; açıklamada böyle adlandır. `TCMB_POLICY_RATE`, `FED_*` veri setinde yok.
* Aylık TÜFE serileri `relate_to`'da desteklenmez (`UNSUPPORTED_RELATION`).
* Karar `p_value_adjusted` ve örneklem dışı kararlılığa dayanır; `significant_after_correction` false ise ilişki anlamlı değildir. İlişki gözlemdir, nedensellik değildir. Son (kısmi) blok `n_excluded_incomplete_horizon` ile dışlanır: eksik veri olarak belirt.
* Kullanıcı "kesin yükselir" derse bu iddia ilişki sonuçlarıyla doğrulanmıyorsa açıkça "doğrulanmamıştır" de; tavsiye ve hedef fiyat verme.
