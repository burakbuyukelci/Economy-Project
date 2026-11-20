# Veri sözlüğü ve tanımlar

> Durum: Bölüm 1-10 sözleşmeyle (schemas v1.0.0), Bölüm 11 fiyat verisi indirmesiyle (`snap_2026-11-20_v1`), Bölüm 12
> düzeltme katmanıyla (`snap_2026-11-20_v2`, güncel/varsayılan sürüm) yazıldı.
> Temel/makro/haber veri setleri eklendikçe yeni bölümler gelecek.

## 1. Tarih ve `as_of` kuralı
- Tüm tarihler **saat dilimsiz düz tarihtir** (`YYYY-MM-DD`). Saat bilgisi yalnızca haber/KAP için ayrı
  alanda (`published_time`, `HH:MM` yerel saat) tutulur ve filtrelemede kullanılmaz.
- **`as_of` DAHİLDİR:** araca giren her satır için `date <= as_of`. `as_of = 2026-09-10` ise 10 Eylül
  satırı dahil, 11 Eylül ve sonrası hariç.
- `start`/`end` parametreleri `as_of`'u aşarsa araç `as_of`'a keser ve `AS_OF_CLAMPED` uyarısı verir.
- Karar günü `t`, `t+1` bilgisini kullanamaz (signal shifting): backtest'te sinyal `t`'de üretilir, işlem en
  erken `t+1`'de gerçekleşir (`signal_lag_days >= 1`, şemada `0` reddedilir).

## 2. Birimler
- Getiri/oran alanları `_pct` (yüzde, 0-100 ölçeği; 12.5 = %12,5) veya `_pp` (yüzde puan farkı) ile biter.
  `hit_rate_pct`, `occurrence_rate_pct` de yüzdedir (0-100).
- Basit getiri: `p_t / p_{t-h} - 1`, fiyat alanı varsayılan `adj_close`.
- Tanımsız istatistik (n=0) `null` döner; 0 yazılmaz.
- Sharpe: günlük getiri, risksiz oran `SHARPE_RISK_FREE_RATE` (config, 0), yıllıklandırma `sqrt(252)`.

## 3. Ufku dolmamış olaylar
İleri getiri ufku (`h` işlem günü) için olay `t` günündeki bir olay, `t+h` işlem günü `as_of`'tan sonraya
düşüyorsa **o ufkun istatistiğine katılmaz**; `n_excluded_incomplete_horizon` olarak raporlanır ve
`INCOMPLETE_HORIZON_EXCLUDED` uyarısı verilir. Olay kaydında `forward_returns[].complete = false`, `return_pct = null`.

## 4. `touch_mode` (Bollinger bant teması)
| touch_mode | Alt bant teması | Üst bant teması |
|---|---|---|
| `close` (varsayılan) | `close <= alt_bant` | `close >= üst_bant` |
| `low` | `low <= alt_bant` | `high >= üst_bant` |

- Bant değeri `t` günündeki kapanışa kadar olan veriyle hesaplanır (bant `t` günü dahil, `t+1` yok).
- `BB_MID_TEST`: `close` modunda `close[t-1]` ile `close[t]` orta bandın farklı taraflarında; `low` modunda
  `low[t] <= orta_bant <= high[t]`.
- `low` modu daha fazla (gün içi) temas yakalar; olay sayısı `close` modundan büyük veya eşit olur.
- İleri getiri her iki modda da **olay günü kapanışından** ölçülür (olay incelemesi; işlem varsayımı değil).
- Başarı (`reversal_success`): alt bant/dip olaylarında `close[t+h] > close[t]`, üst bant/tepe olaylarında
  `close[t+h] < close[t]`. Eşitlik başarı sayılmaz.
- `reversal_strength_pct` (MFE): ufuk içindeki kapanışlar boyunca beklenen yönde en büyük hareket, `t` kapanışına göre.

## 5. Maliyet modeli
- `transaction_cost_bps`: **tek yön, bacak başına** (varsayılan 20 bps). `slippage_bps`: bacak başına
  (varsayılan 5 bps). **VARSAYIM:** 5 bps slippage kaynaklı bir ölçüm değil, basit bir varsayımdır
  (proje dokümanı §18 "simple slippage assumptions"); ekip onayladı, parametreyle değiştirilebilir ve
  rapora varsayım olarak yazılmalıdır. Değerler `config/settings.py` içindedir.
- Bir tur (alım + satım) toplam maliyeti: `round_trip_cost_pct = 2 × (transaction_cost_bps + slippage_bps) / 100`
  (varsayılanla `2 × 25 / 100 = 0,50` yüzde puan). Tur maliyeti **bir kez, tur başına** düşülür.
- `cost_adjusted_*` alanları = brüt değer − `round_trip_cost_pct` (ortalama alan istatistiklerinde olay başına
  düşüm ortalamaya aynen yansır). Kullanılan model her sonuçta `cost_model` alanında yazılıdır.
- Haftanın günü örüntüsünde tur = TRIGGER haftasında OUTCOME günleri için tek giriş + tek çıkış.

## 6. Sektör/peer karşılaştırması
- **Peer grup**, `config/universe.csv` `peer_group` sütunudur. `sector_label` yalnızca bilgi amaçlı serbest
  metindir ve hesapta kullanılmaz. Araç parametresi `sector` = `peer_group` kimliği (enum).
- Her hisse yalnızca **bir** peer grubundadır. 11 hisse tek başına kalır (`peer_group_size = 1`):
  `SOLO_PEER_GROUP` uyarısı verilir, sektör medyanı/rank anlamsızdır (`insufficient_peers = true`).
  `peer_group_size = 2` ise `SMALL_PEER_GROUP` uyarısı verilir.
- **Sektör medyanı grubun TÜM üyeleri (değerlendirilen hisse dahil) üzerinden hesaplanır.** Bu, her sonuçta
  `benchmark_definition` alanında açıkça yazılır: `{type: "peer_median", includes_subject_stock: true,
  price_field: "adj_close", return_type: "simple", peer_group, members}`.
- `lag_score_pp = hisse getirisi − sektör medyan getirisi` (yüzde puan). Laggard: `lag_score_pp <= -lag_threshold_pp`;
  leader: `>= +lag_threshold_pp` (varsayılan eşik `LAG_THRESHOLD_PP_DEFAULT`, config).
- **`sector_strength`** (config'te eşikler): `sector_median_vs_xu100_pp = sektör medyan getirisi − XU100 getirisi`
  aynı pencerede. `>= SECTOR_STRONG_MIN_VS_XU100_PP` (2,0) → `STRONG`; `<= SECTOR_WEAK_MAX_VS_XU100_PP` (−2,0) → `WEAK`;
  arası `NEUTRAL`. Kullanılan eşikler `strength_thresholds` alanında döner. **Eşikler ilk öneridir, kalibre edilmelidir.**

## 8. `stability_verdict` (test_weekday_pattern)
`n_trigger_weeks`: TRIGGER koşulu tutan hafta sayısı (TRIGGER günü yoksa tüm tam haftalar). Eşikler config'te:
`MIN_WEEKDAY_IS_TRIGGER_WEEKS = 10`, `MIN_WEEKDAY_OOS_TRIGGER_WEEKS = 5`. Sıra (ilk eşleşen kazanır):
1. IS `n_trigger_weeks` < IS eşiği → `INSUFFICIENT_DATA` (`IS_TOO_FEW`).
2. IS yeterli, `p_value_adjusted >= alpha` (veya hesaplanamadı) → `UNSTABLE` (`IS_NOT_SIGNIFICANT`).
3. IS anlamlı, OOS `n_trigger_weeks` < OOS eşiği → `INSUFFICIENT_DATA` (`OOS_TOO_FEW`).
4. Aksi halde (b)–(e) denetlenir; hepsi geçerse `STABLE`, değilse `UNSTABLE` + kodlar:
   - (b) OOS ile IS `outcome_mean_diff_vs_unconditional_pct` aynı işaretli, değilse `OOS_SIGN_FLIP`
   - (c) OOS `cost_adjusted_outcome_mean_return_pct > 0`, değilse `OOS_COST_ADJ_NOT_POSITIVE`
   - (d) OOS `hit_rate_pct >= 50`, değilse `OOS_HIT_RATE_TOO_LOW`
   - (e) |OOS fark| >= 0,5 × |IS fark|, değilse `OOS_EFFECT_TOO_SMALL` (yalnızca (b) geçtiyse değerlendirilir)

Notlar: OOS için anlamlılık testi koşulmaz (örneklem küçük, güç düşük). `cost_adjusted_outcome_mean_return_pct`
**yönlüdür** (OUTCOME yönü DOWN ise `-ortalama - tur maliyeti`). **Verdict ne olursa olsun tüm sayısal alanlar
hesaplanabildiği sürece dolu döner** (yalnızca n=0 iken `null`). `verdict_codes` makine okunur nedenler,
`verdict_reason` her kod için sayılı açıklamadır. STABLE bile işlem yapılabilir demek değildir;
`HISTORICAL_ONLY` uyarısı kalır. Uygulama: `tools/stability.py::weekday_stability_verdict`.

## 9. `oos_degradation_flag` (rank_sector_relative_strength, detect_reversal_events, run_backtest)
Ufuk başına, IS ve OOS `HorizonStats` karşılaştırılır (uygulama: `tools/stability.py::oos_degradation`):
- `split_date` yoksa `null`.
- OOS tamamlanmış olay sayısı < `MIN_OOS_EVENTS` (config, **varsayım: 5**) → `false` + `OOS_TOO_SMALL` uyarısı.
- Aksi halde `true`, eğer **(OOS maliyet sonrası ort. ≤ 0 iken IS maliyet sonrası ort. > 0)** veya
  **(IS isabet oranı − OOS isabet oranı > 15 yüzde puan, `OOS_DEGRADATION_HIT_RATE_DROP_PP`)**; değilse `false`.
- `true` olduğunda araç `OOS_DEGRADATION` uyarısı ekler.

## 10. Ufku dolmamış pencereler ve şema doğrulaması
`complete = false` olan her ileri pencerede (`forward_returns[]`, `reactions[]`) tarih alanı (`window_end_date`)
**ve tüm getiri alanları `null`** olmak zorundadır; şema bunu reddederek zorlar. `complete = true` iken tarih/getiri
dolu olmalı ve `validate_envelope` tarihin `as_of` sonrasına düşmediğini ayrıca denetler (`as_of` günü dahil).

## 11. Fiyat verisi (günlük OHLCV)

### 11.1 Kaynak ve kapsam
- **Kaynak:** Yahoo Finance, `yfinance 1.8.0` ile (`scripts/download_prices.py`). Resmî/lisanslı bir veri değildir;
  hoca bunu açıkça serbest bıraktı (hoca_qa.md S2) ve belgelenmesi şart koştu.
- **Semboller:** 30 hisse `<TICKER>.IS` (config/universe.csv); endeks **`XU100.IS`**. `^XU100` Yahoo'da bulunamadı
  (404 / "no data"); `XU100.IS` doğrulandı ve kullanılıyor.
- **Aralık:** 2023-01-02 → 2026-11-20 (indirme günü). İndirme 2023-01-01'den başlar çünkü indikatörlerin ısınması
  (KAMA, Ichimoku 52 gün, Supertrend, 200 günlük SMA) analiz penceresinden önce veri ister. **Analiz penceresi**
  ayrı bir parametredir (`analysis_start`, varsayılan **2024-01-01**, `config/settings.py::ANALYSIS_START_DEFAULT`).
  Ufku dolmamış/`as_of` kuralı her zaman geçerlidir; örnek test `as_of = 2026-09-10`.
- **Boyut:** 29.139 hisse satırı (hisse başına 971–972) + 969 XU100 satırı. Ham Yahoo indirmesi: `snap_2026-11-20_v1`
  (değişmez). **Güncel/varsayılan sürüm `snap_2026-11-20_v2`**: v1'den, tek bir belgeli düzeltmeyle (CCOLA, §12) türetildi;
  satır sayıları ve diğer tüm hisseler v1 ile birebir aynıdır.

### 11.2 Sütunlar (`stocks.parquet`; `index.parquet` aynı, `ticker` yok)
`ticker, date, open, high, low, close, adj_close, volume, dividends, stock_splits`. `date` saat dilimsiz düz tarih
(Yahoo'nun İstanbul yerel günü; UTC kayması yok).

### 11.3 Düzeltme (adjusted / unadjusted)
- **Varsayılan analiz fiyatı: `adj_close`** (Yahoo "Adj Close": bölünme + temettü düzeltmeli). Gerekçe: getiri,
  indikatör ve olay istatistikleri temettü/bölünme günlerinde sahte sıçrama görmesin.
- **`close` (ham) da saklanır** ve `price_adjustment = "unadjusted"` ile alınabilir. **Dikkat:** Yahoo gerçek "hiç
  düzeltilmemiş" fiyat vermez; `close/open/high/low` bölünme için düzeltilmiş, **temettü için düzeltilmemiştir**.
- Araçta `adjusted` modda **open/high/low/close = ham değer × (adj_close / close)** ve `close = adj_close` olur
  (ATR, Supertrend, Ichimoku gibi High/Low kullanan indikatörler tutarlı bir seriden hesaplansın diye).
  `unadjusted` modda Yahoo değerleri aynen döner. `adj_close` alanı her iki modda Yahoo'nun değeridir.
- **Hacim** düzeltilmez. `dividends` ve `stock_splits` Yahoo'nun kayıtlarıdır ve **güvenilir kabul edilmemelidir**
  (CCOLA örneği §11.5).

### 11.4 Eksik veri yönetimi
- **Hiçbir değer doldurulmaz** (forward-fill, interpolasyon yok). Atılan satırlar: `close/open/high/low/adj_close`
  NaN veya ≤ 0 olanlar ve yinelenen tarihler (son satır kalır). Bu indirmede atılan satır sayısı: **0**.
- **İndirme günü yarım mum:** indirme, seans sonundan (18:30 İstanbul) önce yapılırsa o güne ait satır atılır
  (gün içi veri sonradan değişir; tekrarlanabilirliği bozar). Bu indirme 20:29'da yapıldığı için 2026-11-20 satırı
  tutuldu. Bilinen not: **XU100'ün son gününde (2026-11-20) Yahoo hacmi `0`** döndü (muhtemelen gecikme).
- **Birleşik işlem takvimi** (`tools.common.trading_calendar`): bir gün, XU100'de **veya** hisselerin ≥ %50'sinde veri
  varsa işlem günüdür. Tek kaynağa (XU100) bağlanılmadı çünkü Yahoo'da gözlenen boşluklar kaynağa göre farklı:
  - **Her 25 Aralık** (2023, 2024, 2025): 30 hissede satır var, **XU100'de yok**. (BIST o gün açık.)
  - **2024-04-09:** XU100'de var, **21 hissede yok** (9 hissede var). Dini bayram arifesi yarım gün; veri boşluğu.
  - XU100 2023-02-08 satırı 2023-02-07 ile aynı kapanışı taşıyor (4505,30): bayat/kopya satır gibi görünüyor.
- Araçlar, istenen aralıkta (as_of'a kadar) takvime göre eksik günü `MISSING_TRADING_DAYS` uyarısıyla bildirir.
  **Göreli getiri hesaplarında (hisse − XU100)** iki serinin ortak günleri kullanılmalıdır; ortak olmayan gün
  doldurulmaz.

### 11.5 Fiyat sıçraması bayrakları (olası düzeltilmemiş bedelsiz/bölünme)
- **Kural:** `|günlük adj_close getirisi| > PRICE_JUMP_LIMIT_PCT (10) + PRICE_JUMP_TOLERANCE_PP (0,5)`. BIST günlük limiti
  ±%10'dur; ek 0,5 puan, tick yuvarlaması ve düzeltme katsayısı yuvarlamasını (ör. %10,0001) bayrak saymamak içindir.
  `adj_close` kullanılır: temettü günlerindeki ham düşüş (ISMEN 2025-03-28: ham −%15,13, `adj_close` −%3,62;
  AKBNK 2023-03-30: −%10,46 / −%1,30) bayraklanmaz.
- Bayraklar `manifest.json > price_jump_report` içindedir; `get_stock_history/get_index_history` aralıktaki
  (≤ as_of) bayrakları `PRICE_JUMP_OVER_LIMIT` uyarısı olarak döndürür; `check_data_quality` aynı kuralı uygular.
- **Şiddet (HARD / SOFT)** — `tools/price_quality.py::classify_price_jumps`: aynı gün, o gün verisi olan hisselerin
  **≥ %50'si** sıçradıysa **piyasa geneli olay → SOFT** (`PRICE_JUMP_OVER_LIMIT`, tek başına HARD_BLOCK yapmaz); aksi halde
  **hisseye özgü → HARD** (`WRONG_TICKER_OR_BROKEN_HISTORY`, olası düzeltilmemiş bedelsiz/bölünme) ve kapı **HARD_BLOCK**
  olur (`gate_from_issues`). Eşik `PRICE_JUMP_MARKET_WIDE_SHARE` (config). Veri önce `as_of` ile kesilir.
  (Tam `check_data_quality` aracı henüz yazılmadı; bu sınıflandırma onun fiyat bölümüdür.)
- **`snap_2026-11-20_v1` (ham Yahoo) üzerinde 31 bayrak:**
  1. **2023-02-15 (30 hisse, +%11,43 … +%22,17):** hepsinde önceki satır **2023-02-08** (7 günlük takvim boşluğu).
     6 Şubat 2023 depremi sonrası işlem durmasıyla uyumlu; nedeni bağımsız doğrulanmadı. Piyasa geneli (30/30) → **SOFT**.
     Analiz penceresinin (2024-01-01) **öncesinde**, yalnızca ısınma verisinde. v2'de de aynen durur (düzeltilmez).
  2. **CCOLA 2024-08-01: −%90,75** (846,00 → 78,27 ham) → **HARD_BLOCK** (v1'de). `adj_close` da düzeltilmemişti. Neden ve
     düzeltme: **§12**. v1'de bu hâliyle kalır (testle sabit); **v2'de düzeltilmiştir**.
- **`snap_2026-11-20_v2` üzerinde 30 bayrak:** hepsi 2023-02-15 (SOFT); **analiz penceresinde (2024-01-01 →) hiç bayrak yok**.
- Ham veride bölünme düzeltmesi başarılı olan örnekler: ASELS 2023-08-25, FROTO 2025-05-07, EREGL 2024-11-27 vb.
  (bayrak yok). 18 `stock_splits > 0` olayının tamamı §12.3'te kontrol edildi.

### 11.6 Snapshot sürümleme ve okuma
- `data/snapshots/<data_version>/{stocks.parquet, index.parquet, manifest.json}`; `data_version = snap_YYYY-MM-DD_vN`
  (aynı gün için N artar). **Mevcut sürümün üzerine yazılmaz**; yeni indirme yeni sürümdür.
- `data/snapshots/LATEST` güncel sürümü gösterir (**şu an `snap_2026-11-20_v2`**); `SNAPSHOT_VERSION` ortam değişkeni bunu ezer.
  `LATEST`, `config/price_corrections.csv` ve `manifest.json` dosyalarının sha256'sı başka manifest'lere yazıldığı için
  `.gitattributes` ile `eol=lf` sabitlenmiştir (Windows'ta CRLF'e çevrilmesin). `manifest.json`
  kaynak, sürüm, dosya sha256'ları, hisse başına satır/tarih aralığı, fiyat politikası ve sıçrama raporunu taşır.
- Araçlar yalnızca bu dosyaları okur; **ağ kullanmaz** (`tests/test_no_network_in_tools.py` bunu denetler).
  `data_version` her araç çıktısında ve `input_hash` içinde yer alır.
- Yeniden indirme: `python -m scripts.download_prices` (aynı komut `--start`, `--analysis-start`, `--allow-partial`).
  Yahoo geçmişi sonradan düzeltebildiği için iki indirme birebir aynı olmayabilir; bu yüzden sürümler saklanır.

### 11.7 Hangi sürüm ne için kullanılır
| Sürüm | Rol | Kullanım |
|---|---|---|
| **`snap_2026-11-20_v2`** | **Güncel / varsayılan.** `data/snapshots/LATEST` bunu gösterir. | Tüm araçlar, harness, deneyler, backtest, raporlar ve **eğitim verisi üretimi (`training/`)**. |
| `snap_2026-11-20_v1` | Ham Yahoo indirmesi; v2'nin kaynağı (izlenebilirlik). **Değişmez.** | Yalnızca (a) v2'yi yeniden üretmek ve (b) CCOLA'nın v1'de HARD_BLOCK'a düştüğünü gösteren / HARD-SOFT sınıflandırma testleri. |

- Araçlar varsayılan olarak `LATEST`'i (yani v2'yi) okur; kodda sabit sürüm yoktur (`tests/test_real_snapshot.py`
  bunu denetler). v1'i okumak için `SNAPSHOT_VERSION` ortam değişkeni veya `run_on(..., data_version=...)` gerekir; bu
  yalnızca yukarıdaki testler içindir.
- **Eğitim verisi yalnızca v2'den üretilir.** Her eğitim kaydı, kullandığı araç çıktılarındaki `data_version` değerini (v2)
  taşımalı; üreteç v1 (veya v2 dışı) bir `data_version` görürse kaydı reddetmelidir. v1'den üretilmiş herhangi bir
  analiz/eğitim çıktısı (ör. CCOLA'nın 2024-08-01'de −%90,75 düştüğü seri) **geçersiz** sayılır.
- Yeni bir veri sürümü (v3…) gelirse `LATEST` güncellenir ve eğitim verisi yeni sürümden yeniden üretilmelidir.

## 12. Fiyat düzeltme katmanı (`snap_2026-11-20_v2`)

### 12.1 İlke
Ham veri (v1) **asla değiştirilmez**. Düzeltme, `config/price_corrections.csv` tablosundan, **yeni bir sürüm olarak**
üretilir: `v2 = f(v1, csv)` (`python -m scripts.apply_price_corrections --src snap_2026-11-20_v1`). Betik deterministiktir
(duvar saati yok, rastgelelik yok; iki çalıştırma aynı parquet baytlarını ve aynı manifest'i üretir), kaynak v1'in
sha256'sını doğrular ve var olan sürümün üzerine yazmaz. Her kural için **belgeli bir kaynak** (`source`) zorunludur.

### 12.2 csv biçimi ve uygulama
`ticker, date_from, date_to, price_divisor, volume_multiplier, source` (tarih aralığı dahil; boş = sınırsız). Aralıktaki satırlarda
`open, high, low, close, adj_close, dividends` ÷ `price_divisor`, `volume` × `volume_multiplier`; `stock_splits` (Yahoo kaydı)
dokunulmaz. Çakışan kural, bilinmeyen ticker, ≤ 0 çarpan ve hiç satır etkilemeyen kural **hatadır**.
Manifest'e yazılanlar: `corrections_applied` (kural, etkilenen satır sayısı), `corrections_csv.sha256`,
`derived_from` (v1'in `manifest/stocks/index` sha256'ları), yeniden üretilmiş `price_jump_report`.

### 12.3 Tek kural: CCOLA
`CCOLA, date_to=2024-07-31, price_divisor=11, volume_multiplier=11, source=KAP bildirim 1323127` (392 satır etkilenir).
- **Kaynak:** yalnızca KAP bildirim 1323127: %1000 bedelsiz, sermaye 254.370.782 → 2.798.078.602 TL (tam 11 kat), bedelsiz pay
  alma hakkı 13.08.2024.
- **Veride gözlem (v1):** tek seviye değişimi 2024-07-31 → 2024-08-01 (close 846,00 → 78,27; hacim 691.171 → 3.966.028).
  08-01..08-12 arası 8 satır, fiyat ve hacimde 08-13 sonrasıyla **aynı ölçekte** (medyan close 70,50 vs 61,80; medyan hacim
  6,93 M vs 6,68 M; ≤ 07-31 medyanı 879,25 ve 0,58 M). 08-13'te ek sıçrama yok (+%0,31). Yani Yahoo serisindeki ölçek sınırı
  KAP'taki hak tarihinden 12 gün erken (08-01). 846/11 = 76,91, 08-01 kapanışı 78,27 (+%1,77, olağan günlük hareket).
- **Önemli sınırlama: 2024-08-01 … 2024-08-12 satırlarının GERÇEK ham (düzeltilmemiş) fiyatı hiçbir modda yoktur.**
  KAP'taki hak tarihine göre o günlerde işlem gören ham fiyat bedelsiz öncesi düzeydeydi (yaklaşık 11 kat yüksek), ama
  Yahoo bu satırları zaten bölünme-sonrası ölçekte verir ve düzeltme bunları değiştirmez. Bu yüzden CCOLA için `adjusted` **ve**
  `unadjusted` modların ikisi de o 8 günde (ve v2'de 2024-07-31 ve öncesinde) bölünme-düzeltilmiş fiyatı döndürür; gerçek
  işlem fiyatı değildir. Analiz bu seriyi **bölünme-düzeltilmiş getiri** serisi olarak kullanır.
- **Sınıflandırma:** v1'de CCOLA hisseye özgü sıçramayla **HARD_BLOCK**'a düşer (test: `tests/test_price_corrections.py`); v2'de
  analiz penceresinde bayrak yoktur ve kapı PASS'tir.

### 12.4 Bölünme (`stock_splits > 0`) süreklilik kontrolü: 30 hissenin 18 olayı
Her olay için: bölünme tarihinden önceki/sonraki 10 satırın medyan fiyat ve hacim oranı ve ±20 gün içindeki en büyük
|`adj_close` günlük getirisi (`tests/test_price_corrections.py::test_split_events_price_and_volume_continuity_in_v2`).
- **Fiyat:** 18 olayın 16'sında süreksizlik yok (medyan oranı 0,91–1,30; ±20 günde en büyük hareket ≤ %10). İstisnalar:
  **CCOLA** (v1'de −%90,75; v2'de düzeldi) ve **TRALT 2023-02-17** (bölünme 21:1 sürekli: medyan oranı 0,998; ±20 günde
  görülen +%19,74, bölünmeyle değil 2023-02-15 işlem durması sonrası açılışla ilgili).
- **Hacim:** düzeltilmemiş hacim izi yok (bölünme faktörü ≥ 3 olan hiçbir olayda sonra/önce hacim oranı faktörün yarısını aşmıyor;
  tüm oranlar 0,55–1,91, medyan 1,03). Hacim, Yahoo'da bölünmeye göre düzeltilmiş gelir.
- **Yahoo `stock_splits` tarihleri güvenilir değildir:** CCOLA'da kayıt (08-13) ile fiyat ölçeği değişimi (08-01) arasında 12 gün
  fark vardı. Tarih eşleşmesi için bu alana değil sıçrama raporuna ve KAP'a güvenin. Yeni bir bayrak çıkarsa kural
  eklemeden önce KAP'tan doğrulayın.
