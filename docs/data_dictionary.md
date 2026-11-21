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
- **Düzeltme geleceğe bağımlıdır (`as_of` notu):** `adj_close`, Yahoo'nun geriye dönük düzeltme tanımı gereği indirme günündeki (2026-11-20) tüm
  bölünme ve temettüleri geçmişe uygular. `as_of` SONRASINDA gerçekleşen bir temettü/bölünme, `as_of` öncesindeki TÜM `adj_close` seviyelerini
  aynı çarpanla ölçekler. İki gün arasındaki **getiri** bundan etkilenmez (çarpan sadeleşir); ölçekten bağımsız göstergeler (RSI, `%B`, KAMA eğimi,
  Supertrend yönü, Ichimoku konumu, hacim durumu) ve sektör getiri sıralamaları değişmez. Buna karşılık **mutlak seviyeler** (ATR, SMA/EMA/Bollinger
  bant değerleri, Supertrend çizgisi, Ichimoku çizgileri, destek/direnç fiyatları) bu çarpanla ölçeklenmiş gelir; `as_of` günündeki gerçek işlem
  fiyatı değildir ve ham `close` ile doğrudan karşılaştırılmamalıdır. Karar mantığı (olay tespiti, getiri) yalnızca ölçekten bağımsız büyüklüklere
  dayanır. Bu, veri kaynağının (Yahoo) bir özelliğidir ve araç katmanından giderilemez; gerçek ham fiyatlar için `unadjusted` mod kullanılır (§11.3, temettü
  düzeltmesi bu modda da uygulanmaz).

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
- **VERİ SINIRLAMASI (Yahoo'da bilinen boşluk): XU100, 25 Aralık günlerinde satır üretmiyor** (BIST o gün açık, 30 hissede satır var).
  Analiz penceresinde (2024-01-01 → `as_of = 2026-09-10`) bu **2024-12-25 ve 2025-12-25**'tir; `check_data_quality` XU100'ün bu iki günü için
  `n_missing_trading_days = 2` raporlar ama **uyarı üretmez** (kapıyı etkilemez). Gerekçe: boşluk kaynağın bilinen davranışıdır, düzeltilemez ve göreli
  getiriler zaten ortak günlerle hesaplanır (aşağıdaki madde). Bu bir veri doğruluğu iddiası değil, **kaynak sınırlamasının** kayda geçirilmesidir; XU100 üzerinden
  hesaplanan tek günlük göreli ölçüler bu iki günde yoktur (doldurulmaz).
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
  (Tam araç ve kapı kararı: §15.)
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

## 13. Göstergeler: formül, tohum, ısınma (`calculate_indicators`, `tools/indicators/`)
Kod: `tools/indicators/` (saf pandas/numpy). Varsayılan parametreler tek kaynaktan gelir: `schemas/params.py::IndicatorConfig`.
Durum eşikleri: `config/settings.py`, gerekçe `docs/calibration_thresholds.md`.

### 13.1 Genel ilkeler
- **Nedensellik / `as_of`:** `t` günündeki her değer yalnızca `<= t` verisinden hesaplanır. Araç, hesaptan ÖNCE tabloyu `as_of`'a keser
  (`enforce_as_of`); `as_of` sonrası satırlar hesaba hiç girmez (testler: `as_of` sonrası 1e6 kat aşırı satır eklenince `results`
  birebir aynı; gerçek snapshot'ı `as_of`'ta kesip çalıştırınca birebir aynı; kütüphanede "önek değişmezliği").
  Tek ileri bakan seri `chikou_plotted` (Ichimoku grafik Chikou'su) yalnızca kütüphanede vardır; araca ve sinyallere girmez.
- **Hesap, `start`'tan bağımsızdır:** gösterge snapshot'ın ilk barından (2023-01-02) `as_of`'a kadar hesaplanır; `start/end` yalnızca
  DÖNEN satırları sınırlar. `state_date` = `min(end, as_of)` günü veya öncesindeki son işlem günü (`start`'tan bağımsız); `recent_rows`
  yalnızca `>= start` olanlardır. Hafta sonu/tatil `as_of`'ta son işlem günü kullanılır (ör. 2024-01-01 → 2023-12-29).
- **Hafif zarf (şema 1.2.0):** varsayılan `last_n_rows = 0` ve `include_columns_meta = False`; yani yalnızca `latest` döner, `columns = []`
  (`columns_meta_included = false`). Isınmadaki (değeri `None`) kolonlar her durumda `invalid_columns_at_as_of` ile adıyla bildirilir; `first_valid_date`
  ve `INSUFFICIENT_HISTORY` uyarısı da seçilen kolonlar üzerindendir. `value_columns` verilirse `values` yalnızca o kolonları taşır (hesap aynı; bilinmeyen ad
  `INVALID_PARAMS`, hata metni bu çağrıda geçerli adları listeler); `states` istenen göstergelerden gelir, `value_columns`'tan bağımsızdır.
  Ölçüm (THYAO, `as_of = 2026-09-10`, 23 kolon, JSON karakter): hafif varsayılan 2 226; 1.1.0 varsayılanı (kolon meta + 5 satır) 9 124; yalnız `RSI` hafif 1 514.
  Gerekçe: küçük yerel modelin bağlamı ve sayı havuzu (fazla sayı = rastlantısal eşleşme olasılığı). Kolon meta'sı ve geçmiş satırlar istenince açılır.
- **Fiyat modu:** `adjusted` (varsayılan) açık/yüksek/düşük/kapanışı `adj_close/close` ile ölçekler, `close = adj_close` (§11.3).
  `unadjusted` Yahoo `open/high/low/close` değerlerini kullanır; Yahoo `close`'u bölünmeye göre zaten düzeltilmiştir, temettüye göre değildir.
  Hacim düzeltilmez. CCOLA için v2'de iki mod da 2024-07-31 öncesi bölünme-düzeltilmiş fiyatı verir (§12.3).
- **Isınma = `None`:** ısınma günlerinde değer `None` (NaN zarfa girmez), `valid_at_as_of=False`, `INSUFFICIENT_HISTORY` uyarısı verilir.
  `columns[].warmup_bars` analitiktir; testler ampirik ilk geçerli bar ile eşitliği doğrular.
- **Tohum etkisi:** özyinelemeli göstergeler (EMA, RSI, ATR, KAMA, MACD sinyali, Supertrend bantları) başlangıç tohumundan etkilenir.
  Tohum snapshot'ın başındadır (2023-01-02), bu yüzden 2024'ten sonraki değerler 2023 tohumuna bağlıdır; EMA/RSI/ATR için etki üstel
  sönümlenir (`ta` ile karşılaştırmada 400 barda göreli fark < 1e-8). Aynı snapshot → aynı değer (determinizm).
- **Birimler:** sayılar 4 ondalığa yuvarlanır. `BB_BANDWIDTH_PCT_*` yüzde (0-100 ölçeği); `BB_B_*` birimsiz oran (alt bant 0, üst bant 1).
  `ICHIMOKU_CHIKOU_VS_CLOSE_*` fiyat birimi (TL).
- **2023-02-15 uyarısı:** tüm hisselerde SOFT sıçrama (§11.5) ısınma döneminde yer alır; etkisi 2024 başında üstel olarak sönmüştür.
  Analiz penceresinde (2024-01-01 →) v2'de sıçrama yoktur.

### 13.2 Formüller, tohum, ısınma (n = istenen bar sayısı; "ısınma" = ilk geçerli değer için gereken bar)
| Gösterge | Formül | Tohum | Isınma (bar) | Kolon adı (varsayılan) |
|---|---|---|---|---|
| SMA(w) | son w kapanışın ortalaması | – | w | `SMA_20`, `SMA_50`, `SMA_200` |
| EMA(w) | `α·x_t + (1−α)·EMA_{t−1}`, α = 2/(w+1) | ilk w değerin SMA'sı | w | `EMA_12`, `EMA_26` |
| RSI(p) Wilder | `100 − 100/(1+RS)`, RS = ort. kazanç/ort. kayıp; `avg_t = (avg_{t−1}·(p−1)+x_t)/p` | ilk p değişimin basit ortalaması; kayıp=0 → 100, düz seri → 50 | p+1 | `RSI_14` |
| MACD(f,s,g) | `EMA(f) − EMA(s)`; sinyal = MACD'nin EMA(g)'si; hist = MACD − sinyal | EMA tohumları | MACD: s; sinyal/hist: s+g−1 | `MACD_12_26_9`, `MACD_SIGNAL_12_26_9`, `MACD_HIST_12_26_9` |
| Bollinger(w,k) | orta = SMA(w); üst/alt = orta ± k·std; `%B` = (c−alt)/(üst−alt); bant genişliği % = (üst−alt)/orta·100 | – | w | `BB_UPPER_20_2.0`, `BB_MID_20_2.0`, `BB_LOWER_20_2.0`, `BB_B_20_2.0`, `BB_BANDWIDTH_PCT_20_2.0` |
| ATR(p) Wilder | `TR = max(h−l, \|h−c₋₁\|, \|l−c₋₁\|)`; `ATR_t = (ATR_{t−1}·(p−1)+TR_t)/p` | ilk p TR'nin (idx 1..p) basit ortalaması (TR₀ yok) | p+1 | `ATR_14` |
| KAMA(n,f,s) | `ER = \|c_t−c_{t−n}\|/Σ\|Δc\|`; `sc = (ER·(2/(f+1)−2/(s+1))+2/(s+1))²`; `KAMA_t = KAMA_{t−1}+sc·(c_t−KAMA_{t−1})` | önceki KAMA = c_{n−1} (ilk çıktı idx n); hareket yoksa ER=0 | n+1 | `KAMA_10_2_30` |
| Supertrend(p,m) | hl2 = (h+l)/2; bantlar hl2 ± m·ATR(p); üst bant yalnız düşer, alt bant yalnız yükselir (önceki kapanış bandı geçince sıfırlanır); çizgi = yükselişte alt, düşüşte üst bant | ilk gün yön: c ≥ hl2 → yükseliş | p+1 | `SUPERTREND_10_3.0` (çizgi; yön `states.supertrend`) |
| Ichimoku(t,k,b) | Tenkan = (max H + min L)/2 (t gün); Kijun (k gün); Senkou A = (Tenkan+Kijun)/2, Senkou B = (max H + min L)/2 (b gün), ikisi k bar İLERİ kaydırılır (kaydırma = kijun = 26); Chikou karşılığı = c_t − c_{t−26} | – | Tenkan t; Kijun k; Senkou A max(t,k)+k; Senkou B b+k; Chikou karşılığı k+1 | `ICHIMOKU_TENKAN_9`, `ICHIMOKU_KIJUN_26`, `ICHIMOKU_SENKOU_A_9_26`, `ICHIMOKU_SENKOU_B_52`, `ICHIMOKU_CHIKOU_VS_CLOSE_26` |
| Hacim z-skoru(w) | `(v_t − ort)/std`, son w gün, BUGÜN DAHİL; std = 0 → `None` | – | w | `VOLUME_ZSCORE_20` |
| Getiri / volatilite (yalnız kütüphane) | `c_t/c_{t−h} − 1` (kesir); yıllıklandırılmış std(1g log getiri, ddof=1)·√252 | – | h+1 / w+1 | araca girmez |

Ichimoku bulutu: gün `t`'deki Senkou A/B, `t−26` gününün verisinden hesaplanıp ileri kaydırılmıştır (gelecek bilgisi yok).
Klasik "Chikou Span" (kapanışın 26 gün GERİYE çizilmesi) geleceğe bakacağı için sinyalde kullanılmaz; yerine nedensel karşılığı
`ICHIMOKU_CHIKOU_VS_CLOSE_26` (c_t − c_{t−26}) verilir.

### 13.3 Standart sapma tanımı (Bollinger = hacim z-skoru)
**Her ikisinde de popülasyon std'si (`ddof = 0`)** kullanılır: `std = sqrt( Σ(x_i − ort)² / w )`, `w` = pencere uzunluğu, pencere bugün dahil.
Doğrulama: `tests/tools/test_indicators_config.py::test_bollinger_and_volume_zscore_use_same_population_std_ddof0` aynı seride
Bollinger'ın std'sinin `(üst−orta)/k`, hacim z-skorunun paydasının ve `numpy ddof=0` değerinin birebir aynı olduğunu, `ddof=1`'den farklı
olduğunu doğrular; ayrıca `ta` kütüphanesinin (ddof=0) bant değerleriyle birebir eşleşir. Getiri volatilitesi ise örneklem std'sidir (`ddof=1`);
bu gösterge ayrıdır ve araca girmez.

### 13.4 Kategorik durumlar (`states`; `None` = gösterge istenmedi veya ısınmada)
| Durum | Sınıflar | Tanım |
|---|---|---|
| `supertrend` | `BULLISH` / `BEARISH` | yön +1 → BULLISH (çizgi fiyatın altında, alt bant); yön −1 → BEARISH (çizgi fiyatın üstünde, üst bant). Yönün dönmesi: yükselişteyken kapanış nihai alt bandın altına inerse, düşüşteyken nihai üst bandın üstüne çıkarsa |
| `ichimoku_position` | `ABOVE_CLOUD` / `IN_CLOUD` / `BELOW_CLOUD` | bulut = [min(Senkou A, B), max(Senkou A, B)] (günün kendi değerleri). Kapanış > üst → ABOVE; < alt → BELOW; sınırlar dahil arası → IN |
| `kama_slope` | `RISING` / `FLATTENING` / `FALLING` | `eğim_pct = (KAMA_t/KAMA_{t−1} − 1)·100` (KAMA'nın 1 günlük % değişimi). `> +0,10` RISING; `< −0,10` FALLING; sınır dahil arası FLATTENING (`KAMA_FLAT_SLOPE_PCT`). İlk geçerli KAMA gününde önceki yok → `None` |
| `volume_regime` | `HIGH` / `NORMAL` / `LOW` | hacim z-skoru `> +1,0` HIGH; `< −1,0` LOW; sınır dahil arası NORMAL (`VOLUME_HIGH_Z`, `VOLUME_LOW_Z`). z tanımsızsa (std = 0) `None` |

Eşikler ileri getiriye bakılmadan seçilmiştir ve olay sonuçlarına bakılarak değiştirilmez (`docs/calibration_thresholds.md`).
Bu durumlar nedensellik iddiası değildir; yalnızca o günkü gösterge konumunu betimler (`HISTORICAL_ONLY`).

### 13.5 Isınma ve analiz başlangıcı
Veri 2023-01-02'den başlar (§11.1). En uzun ısınma `SMA_200` (200 bar); THYAO'da ilk geçerli gün 2023-10-23. Test: 30 hissenin hepsinde
`as_of = 2024-01-01` (tatil → `state_date` 2023-12-29) için TÜM kolonlar ve durumlar geçerlidir ve `INSUFFICIENT_HISTORY` uyarısı yoktur
(`tests/tools/test_calculate_indicators.py::test_real_all_columns_valid_on_2024_01_01_for_all_30_tickers`).
`CCOLA` 2024-08-01 çevresinde SMA/EMA/KAMA/Bollinger/Ichimoku'da sıçrama yoktur (v2); aynı test v1'de (düzeltilmemiş) kırılır.

## 14. Sektör göreli güç ve tarihsel catch-up (`rank_sector_relative_strength`, `tools/rank_sector_relative_strength.py`)
Parametre `sector` = `peer_group` kimliği (§6). Fiyat `adj_close`, getiri basit getiri. Bu bölüm §6'yı tamamlar; çelişirse §6'nın
şema tanımları (kendisi dahil medyan, eşikler) geçerlidir.

### 14.1 Ortak gün paneli ve lag penceresi
- Panel = grubun TÜM üyeleri + XU100 `adj_close`, `as_of`'a kesilmiş (`enforce_as_of`), **ortak günler** (inner join; doldurma yok, §11.4).
  Bir üyede veya XU100'de eksik gün panelden düşer ve `MISSING_TRADING_DAYS` uyarısıyla (panel düzeyinde, tarihler listelenerek) bildirilir.
  Retail, `as_of = 2026-09-10`: 2024-04-09, 2024-12-25, 2025-12-25 düşer. "h işlem günü" = panelde h satır.
- Lag penceresi `horizon` gün: `getiri_t = (p_t / p_{t−h} − 1)·100`. `window_end` = `as_of`'ta veya öncesindeki son panel günü;
  `window_start` = `window_end`'den h−1 satır önceki gün (getiri bir önceki kapanıştan ölçülür).
- **Yuvarlama:** getiriler 4 ondalığa yuvarlanır; medyan, `lag_score_pp`, XU100 farkı yuvarlanmış getirilerden türetilir. Böylece zarftaki
  sayılar birbiriyle birebir tutarlıdır (`lag = return − medyan`). Sınıflandırma (`is_laggard`, `sector_strength`) da yuvarlanmış değerlerle yapılır;
  sınırlar dahildir (`lag ≤ −eşik`, `lag ≥ +eşik`, `fark ≥ +2,0` STRONG, `≤ −2,0` WEAK). Negatif sıfır (`-0.0`) `0.0`'a çevrilir.
- Sıralama: getiri azalan; eşitlikte ticker alfabetik (determinizm). Rank 1 = en güçlü.
- **Tek hisseli grup:** `ERROR` değil. `SOLO_PEER_GROUP` uyarısı, `insufficient_peers = true`; sıralamada tek satır (rank 1, `lag_score_pp = 0.0`,
  `is_laggard = is_leader = false`); sektör medyanı, XU100 farkı ve `sector_strength` `null`; `historical_catch_up = []`, `n_events = null`.
  **İki hisseli grup:** `SMALL_PEER_GROUP`; medyan iki hissenin ortalaması olduğundan lag skorları birbirinin aynasıdır (A = −B) ve olaylar birbirine bağımlıdır.

### 14.2 İKİ AYRI medyan tanımı (tespit ≠ sonuç)
| | Tespit (laggard / leader, `lag_score_pp`, `sector_median`) | Sonuç (tarihsel ileri getiri farkı, `excess`) |
|---|---|---|
| Ölçüt | grubun TÜM üyeleri DAHİL medyanı (şema: `includes_subject_stock = true`) | **KENDİSİ HARİÇ** diğer üyelerin medyanı (leave-one-out) |
| Formül | `lag = getiri_i − medyan(getiri_1..n)` | `excess_i = ileri_getiri_i − medyan(ileri_getiri_j, j ≠ i)` |

Şema 1.2.0: sonuç ölçütü `outcome_benchmark_definition` alanındadır (`peer_median`, `includes_subject_stock = false`, `members` = grup üyeleri; her hisse için
kendisi çıkarılır). `benchmark_definition` yalnızca TESPİT medyanını anlatır (`includes_subject_stock = true`).

**Neden iki tanım:** sonuçta kendisi dahil medyan kullanmak, 3 hisseli grupta başarıyı "grubun en iyisi olmak"a indirir: medyan her zaman üyelerden
biridir; geride kalmaya devam etmeyip medyan hisseye yetişen hisse `excess = 0` alır ve "yanlış pozitif" sayılır; baz isabet oranı da `%33`e düşer.
Kendisi hariç medyan bu yapay sınırı kaldırır.

**Sayısal örnek:** ileri +5 günde B +%6, A (laggard) +%4, C +%1. Kendisi dahil medyan %4 → `excess = 0` (yanlış pozitif). A için kendisi hariç
medyan = medyan(6, 1) = %3,5 → `excess = +0,5` (başarı). (Test: `test_leave_one_out_outcome_user_example_is_a_success_not_a_false_positive`.)

Başarı: `excess > 0`. Yanlış pozitif: `excess ≤ 0` (geride kalmaya devam etti); eşitlik başarı değildir (`HorizonStats` sözleşmesi).
3 üyede kendisi hariç medyan = diğer ikisinin ortalaması olduğundan, `excess` toplamı her gün tam sıfırdır (baz ortalama = 0, yuvarlama hariç).
Kendisi hariç tanımla **baz isabet oranı ≈ %50** çıkar (iid hisse yürüyüşlerinde test edilir; gerçek retail: %49,7 / %50,6 / %48,7).
`HISTORICAL_ONLY` uyarı metni her çağrıda şunu yazar: *"tespit: grup medyanı (kendisi dahil); sonuç: kendisi hariç peer medyanı"*.

### 14.3 Tarihsel olay kuralı
Her `t ∈ [analysis_start, as_of]` günü ve her üye için **aynı** kural uygulanır (yalnızca `≤ t` verisi): `lag_t ≤ −lag_threshold_pp`
(kendisi dahil medyanla). Lag penceresi `analysis_start`'tan önceki geçmişe uzanabilir (nedensel; veri 2023-01-02'den başlar).
- **Sınırlama:** kural, o gün **sektörün güçlü olup olmadığını aramaz** (`sector_strength` koşulu yoktur). Sektör genel olarak düşerken
  medyanın gerisinde kalmak ile sektör yükselirken gerisinde kalmak aynı olay sayılır. Bu bir tasarım sınırlamasıdır; sonuçlar bu karışımı yansıtır.
- **Havuzlama ve hisse bazlı kırılım (1.2.0):** `historical_catch_up` grubun tüm üyelerinin olaylarını birleştirir (havuzlu). `per_ticker` aynı olayların hisse bazlı
  PARÇASIDIR: ham sayılar, bağımsız olaylar ve her ufuk için `CatchUpHorizon`; şema doğrulayıcısı hisse bazlı toplamların havuza eşitliğini zorlar
  (ham sayı, tamamlanmış, dışlanan, başarı, yanlış pozitif). Retail'de MAVI ham gözlemlerin çoğunu verir (227 / 398). `HISTORICAL_ONLY` uyarı metni geçiş dönemi için
  sayıları yazmaya devam eder, fakat sayı doğrulayıcı yalnızca `results` ağacını havuza alır; `warnings` içindeki sayılar alıntılanamaz. Makine okunur kaynak `per_ticker` ve üst alanlardır.

### 14.4 Bağımsızlaştırma (cooldown)
**Sorun:** bir hisse ardışık günlerde geride kalırsa ileri pencereler örtüşür; aynı fiyat hareketi onlarca "olay" olarak sayılır, `n_events` şişer
ve güven aralığı yanlış daralır. **Kural:** her hissede, kronolojik tarama; `laggard[t, i]` doğruysa ve `t ≥ (son kabul edilen olay + cooldown)`
ise olay kabul edilir. `cooldown = max(forward_horizons)` işlem günü (varsayılan 20). Kabul edilen bir hissenin olaylarının en uzun ileri
pencereleri örtüşmez. Cooldown KABUL EDİLEN olaydan sayılır (arada laggard olmayan gün olması süreyi sıfırlamaz). Kural yalnızca geçmiş
olaylara bağlıdır; `as_of` sonrası veri kabul kararını etkileyemez. Sonuçta `cooldown_days` alanı yazılıdır (= `max(forward_horizons)`; PARAMETRE değildir, duyarlılık analizi gerekirse sonraki sürümde param olarak eklenir ve `input_hash`'i değiştirir).
- **Retail, `as_of = 2026-09-10`, eşik 3 pp:** ham laggard hisse-günü BIMAS 43, MAVI 227, MGROS 128 (toplam 398) → cooldown=20 sonrası
  bağımsız olay BIMAS 9, MAVI 21, MGROS 14 (toplam 44). Bu sayılar `n_raw_laggard_observations` (398), `per_ticker[].n_raw_laggard_observations` ve `per_ticker[].n_independent_events` alanlarındadır (geçiş dönemi: `HISTORICAL_ONLY` metninde de).
- **Hisseler arası bağımlılık KALIR:** cooldown hisse bazındadır. Aynı gün/komşu günlerde farklı hisselerin olayları ortak sektör şoklarını paylaşır
  (ve 2 hisseli grupta birbirinin aynasıdır); olaylar tam bağımsız değildir. Bu yüzden isabet oranları güven aralığı olmadan, yaklaşık göstergedir.

### 14.5 İstatistikler (`historical_catch_up[]`)
- `forward_horizons` (varsayılan 5/10/20) başına bir `HorizonBlock`. Olay (i, t) için ufuk f: `ileri_getiri = (p_{t+f}/p_t − 1)·100`; `excess` §14.2.
  `HorizonStats.mean_return_pct` / `median_return_pct` **hissenin ham getirisi değil, `excess`'in (pp) ortalaması/medyanıdır.**
- **Ufku dolmamış olaylar (kural 2):** `t + f` panelin son gününü (`≤ as_of`) aşıyorsa olay o ufkun istatistiğine girmez;
  `n_excluded_incomplete_horizon` olarak sayılır (`INCOMPLETE_HORIZON_EXCLUDED`). Kabul edilen her olay her ufukta ya tamamlanmıştır ya dışlanmıştır
  (`n_events_complete + n_excluded_incomplete_horizon` ufuktan bağımsız sabit: retail'de 44).
- `median_catch_up_size_pp` = başarılı olaylarda (`excess > 0`) `excess` medyanı; başarılı olay yoksa `null`.
- **Baz (`baseline`):** aynı dönem (`t ≥ analysis_start`), aynı ufuk, tüm (hisse, gün) gözlemleri (olay şartı yok; örtüşen pencereler dahil, bu yüzden
  yalnızca referans düzeyidir); aynı `excess` tanımı. `mean_diff_vs_baseline_pct` = olay ortalaması − baz ortalaması.
- **`cost_adjusted_mean_return_pct` = `mean_return_pct − round_trip_cost_pct` (varsayılan 0,50 pp). VARSAYIM:** bu, yalnızca laggard hissede **uzun
  pozisyonun tur maliyetidir**; kendisi hariç medyan "bacağı" için maliyet düşülmez ve böyle bir bacak işlem olarak varsayılmaz. Yani `excess`
  uygulanabilir bir strateji getirisi değil, göreli performans ölçüsüdür; gerçek işlem testi `run_backtest`'tedir (§5).
- **Örneklem içi/dışı:** `split_date` verilirse olay tarihi `< split_date` ise IS, `≥ split_date` ise OOS. Olay, **tarihine** göre atanır; bir IS olayının ileri
  penceresi `split_date`'in ötesine uzanabilir. `oos_degradation_flag` §9'a göre (`tools/stability.py::oos_degradation`); OOS tamamlanmış olay `< MIN_OOS_EVENTS`
  ise `false` + `OOS_TOO_SMALL`; `true` ise `OOS_DEGRADATION`. `split_date` yoksa IS/OOS blokları ve bayrak `null`.
- **Zarf:** `n_events` = en uzun ufukta **tamamlanmış** bağımsız olay sayısı; `n_excluded_incomplete_horizon` = aynı ufukta dışlananlar.
  `n_events < MIN_EVENTS` ise `FEW_EVENTS`. Her çağrıda `HISTORICAL_ONLY` ve `MULTIPLE_TESTING_RISK` (3 ufuk + pencere/eşik seçimi, düzeltme uygulanmaz) bulunur.
- **`per_ticker[].per_horizon[]` (1.2.0):** aynı `CatchUpHorizon` tipi, aynı olaylar ve aynı `excess`; yalnız o hissenin olayları. IS/OOS bölümü YOKTUR (hisse başına 9–21 olay
  bölünemez; `in_sample` / `out_of_sample` `null`). Baz (`baseline`) o hissenin kendi koşulsuz `excess` gözlemleridir (Σ `n_obs` = havuzlu baz). `n_independent_events` = tamamlanmış +
  dışlanan (her ufukta sabit); `n_excluded_incomplete_horizon` en uzun ufuk içindir. Olayı olmayan hissede istatistikler `n_events_complete = 0`, oranlar `null`.
  **`FEW_EVENTS` yalnızca havuzlu `n_events` için üretilir**; hisse bazlı olay sayısı (ör. BIMAS 9) `per_ticker`'dan okunur ve hisse bazlı eşik değerlendirmesi harness etiket politikasındadır.
- `structural_vs_temporary` şimdilik `null` (temel/makro araçları gelince doldurulacak).

### 14.6 Gerçek örnek (v2, retail = BIMAS, MGROS, MAVI, `as_of = 2026-09-10`, horizon 20, eşik 3 pp, `split_date = 2026-01-01`)
- Pencere 2026-08-14 → 2026-09-10: BIMAS +14,2098 %, MGROS −1,8116 % (medyan), MAVI −5,0568 %; XU100 +1,8518 %; sektör − XU100 = −3,6634 pp → `WEAK`.
  Lag: BIMAS +16,0214 (leader), MGROS 0,0, MAVI −3,2452 pp (laggard; eşikten yalnızca 0,2452 pp uzakta, eşik hassas).
- Tarihsel (kendisi hariç excess, bağımsız olay 44, ufku dolmamış 1): isabet oranı 5g %46,5, 10g %48,8, 20g %48,8; baz %49,7 / %50,6 / %48,7.
  20g'de ortalama +1,16 pp ama medyan −0,80 pp (büyük yakalamalar ortalamayı çekiyor); OOS (2026) isabet %40, `OOS_DEGRADATION` (20g).
- Hisse bazlı kırılım (1.2.0): `n_raw_laggard_observations` 398 (BIMAS 43, MAVI 227, MGROS 128); `cooldown_days` 20; bağımsız olay BIMAS 9, MAVI 21, MGROS 14; ufku dolmamış toplam 1.
  Test: `tests/tools/test_rank_sector_relative_strength.py::test_real_retail_per_ticker_matches_documented_counts`.

## 15. Veri kalitesi ve risk kapısı (`check_data_quality`, `tools/check_data_quality.py`)

### 15.1 İlke
Kapı, **hangi kontrol çalıştı** ve **ne buldu** bilgisini birlikte verir. Çalışmayan kontrol "geçti" sayılmaz: `checks_run` yalnızca gerçekten
çalışanları listeler, `gate_reason` çalışmayanları (veri veya şema yoksa) adıyla yazar. `hard_blocks[]` ve `soft_warnings[]` kodlu (`DQCode`) ve
sayılıdır: makine okunur sayaç `issue_counts` (1.2.0; kod → adet, hard ve soft birlikte, sıfır girdi yok, anahtarlar kod adına göre sıralı; sorun yoksa `{}`, `null` değil).
Geçiş dönemi için `gate_reason` metni aynı sayıları yazar ("hard 1 (WRONG_TICKER_OR_BROKEN_HISTORY×1), soft 2 (MISSING_TRADING_DAYS×2)"); sayı doğrulayıcı metin yerine alanı kullanabilir.
`DQIssue.date` hiçbir zaman `as_of` sonrası olamaz (`date` geçmiş-only anahtardır; aksi halde şema look-ahead taraması kapının kendi zarfını reddederdi): `as_of` sonrası tarihli ihlalin tarihi `message` içinde yazılır, `date` `null` kalır.
Araç `status = OK` döner; `HARD_BLOCK` bir araç hatası değil bir **bulgudur**. Sıra: veri **önce** `as_of` ile kesilir (`enforce_as_of`), sonra kontroller.

### 15.2 Koşul → kapı tablosu
En yüksek kademe kazanır: `HARD_BLOCK` > `ANALYSIS_UNSAFE` > `INVESTIGATE` > `PASS_WITH_WARNINGS` > `PASS`. Uyarı **sayısı** kapıyı yükseltmez.

| Koşul | Kod | Sınıf | Kapı | Durum |
|---|---|---|---|---|
| Bundle öğesinin `as_of`'u oturum `as_of`'unu aşıyor | `AS_OF_VIOLATION` | HARD | HARD_BLOCK | `params` üzerinden çalışır |
| Hisseye özgü fiyat sıçraması (aynı gün hisselerin < %50'si sıçradı); ticker snapshot'ta yok / pencerede satır yok | `WRONG_TICKER_OR_BROKEN_HISTORY` | HARD | HARD_BLOCK | `params` üzerinden çalışır |
| `signal_lag_days_applied < 1`; `run_backtest` dışı araçta `max_result_date > as_of` | `LOOKAHEAD_SIGNAL` | HARD | HARD_BLOCK | `params` (bundle; `BundleItem.signal_lag_days_applied` / `max_result_date`, şema 1.2.0; `check_lookahead`) |
| `run_backtest` çıkışı `as_of` sonrası (`max_result_date > as_of`) | `BACKTEST_FUTURE_INFO` | HARD | HARD_BLOCK | `params` (bundle; aynı olgu iki kodla yazılmaz) |
| Backtest girişi sinyal gününden sonra değil (işlem bazlı) | `BACKTEST_FUTURE_INFO` | HARD | HARD_BLOCK | **saf fonksiyon** (`check_backtest_information`); bundle'da işlem listesi yok, bağlanmaz |
| Bilanço açıklama tarihi kullanım tarihinden veya `as_of`'tan sonra | `FUTURE_FUNDAMENTAL_LEAK` | HARD | HARD_BLOCK | **saf fonksiyon** (`check_fundamental_alignment`); bilanço verisi henüz yok |
| Bilanço açıklama tarihi dönem sonundan önce (dönem sonuna göre hizalama izi) | `PERIOD_MISMATCH` | HARD | HARD_BLOCK | **saf fonksiyon**; tanım **GEÇİCİ** (bizim operasyonelleştirmemiz; bilanço verisi gelince yeniden değerlendirilecek) |
| Piyasa geneli sıçrama (hisselerin ≥ %50'si, ör. 2023-02-15) | `PRICE_JUMP_OVER_LIMIT` | SOFT | PASS_WITH_WARNINGS | `params` |
| Hissede eksik işlem günü | `MISSING_TRADING_DAYS` | SOFT | PASS_WITH_WARNINGS | `params` |
| Bayatlık 5–10 gün | `STALE_DATA` | SOFT | PASS_WITH_WARNINGS | `params` |
| Makro seride boşluk; seyrek haber; düşük transkript kalitesi | `MACRO_GAP`, `NEWS_SPARSE`, `TRANSCRIPT_LOW_QUALITY` | SOFT | PASS_WITH_WARNINGS | **saf fonksiyon**; veri/araç yok |
| `n_events` < araç minimumu (0 dahil) | `FEW_EVENTS` | SOFT | **INVESTIGATE** | `params` (bundle) |
| Peer grubu < 3 (yalnızca bundle'da rank aracı varsa) | `SMALL_PEER_GROUP` | SOFT | **INVESTIGATE** | `params` (bundle) |
| Bundle öğesi başka `data_version`'dan | `DATA_VERSION_MISMATCH` | SOFT | **INVESTIGATE** | `params` (bundle) |
| Bayatlık 11–30 gün | `STALE_DATA` | SOFT | **INVESTIGATE** | `params` |
| Bayatlık > 30 gün (veri `as_of`'u kapsamıyor) | `STALE_DATA` | SOFT | **ANALYSIS_UNSAFE** | `params` |

- **INVESTIGATE:** sonuç üretilebilir ama kanıt zayıf; harness eylemi `INVESTIGATE`'e bağlar (`harness/evidence.py::_action_for_gate`).
- **ANALYSIS_UNSAFE:** yalnızca veri `as_of`'u kapsamıyorsa. "Olay yok" (`n_events = 0`) **bir bulgudur, veri hatası değil** → INVESTIGATE.
- Bayatlık = `as_of − (as_of'a kadarki son satır tarihi)`, takvim günü, her hisse ve XU100 için. Eşikler (`tools/check_data_quality.py`, `config/`'e konmadı):
  `STALE_GRACE_DAYS = 4` (**varsayım**: Cuma–Pazartesi tatili dahil normal; ≤ 4 gün uyarı yok), `STALE_WARN_MAX_DAYS = 10`, `STALE_UNSAFE_DAYS = 30` (ikisi onaylı).
- **MACRO_GAP eşiği seri sıklığına bağlıdır (onaylı):** `MACRO_MAX_GAP_DAYS_BY_FREQUENCY = {"daily": 7, "monthly": 45}` gün; `check_macro_coverage(..., frequency="daily"|"monthly", max_gap_days=None)`.
  Açık `max_gap_days` sıklığı ezer; bilinmeyen sıklık hata verir. Boşluk, ardışık gözlemler ve `[start, end]` uçları arasında ölçülür.
- **GEÇİCİ** eşikler (ekip onayı bekliyor; ilgili veri/araç gelince gerçek dağılıma göre yeniden belirlenecek): `NEWS_MIN_ITEMS = 3`, `TRANSCRIPT_MIN_QUALITY = 0.6`,
  `PEER_GROUP_MIN_SIZE = 3` ve `PERIOD_MISMATCH` tanımı (tablo).

### 15.3 Hangi kontrol ne zaman `checks_run`'a girer
Her zaman: `PRICE_JUMPS`, `MISSING_DAYS`, `STALENESS`, `AS_OF_CONSISTENCY`, `TICKER_IDENTITY` (boş bundle'da bile; harness'ın ilk kapısı budur).
Bundle doluysa: `DATA_VERSION_CONSISTENCY`. Bundle'da tabloda olan bir araç ve `n_events` varsa: `EVENT_COUNT`. Bundle'da `rank_sector_relative_strength` varsa:
`PEER_GROUP_SIZE`. `SIGNAL_SHIFT` (1.2.0): bundle'da en az bir `run_backtest` öğesi varsa VE her `run_backtest` öğesi `signal_lag_days_applied` taşıyorsa; aksi halde çalışmadı sayılır ve `gate_reason`'da adıyla yazılır
(lag taşıyan öğeler yine de değerlendirilir). `max_result_date` kontrolü `AS_OF_CONSISTENCY` altındadır (alanı olmayan öğe sorun üretmez).
**Hiçbir zaman (şimdilik):** `FUNDAMENTAL_DISCLOSURE_ALIGNMENT`, `MACRO_COVERAGE`, `NEWS_COVERAGE`, `TRANSCRIPT_QUALITY`
(veri/araç yok; saf fonksiyonları sentetik girdiyle testli). `checks` verilirse yalnızca istenenler değerlendirilir; istenip çalışamayanlar `gate_reason`'da yazılır.

### 15.4 `FEW_EVENTS` araç bazlıdır (`EVENT_COUNT_RULES`)
Birim, `schemas/envelope.py` içindeki `n_events` tanımından; minimum config sabitlerinden. **Tabloda olmayan araçta kontrol çalışmaz** ve `EVENT_COUNT` `checks_run`'a girmez.

| Araç | `n_events` birimi | Minimum | Kaynak |
|---|---|---|---|
| `detect_reversal_events` | olay | 20 | `MIN_EVENTS` |
| `rank_sector_relative_strength` | olay (en uzun ufuk, tamamlanmış, bağımsız) | 20 | `MIN_EVENTS` |
| `run_backtest` | sinyal | 20 | `MIN_EVENTS` |
| `test_weekday_pattern` | hafta (IS+OOS `n_occurrences`) | 15 | `MIN_WEEKDAY_IS_TRIGGER_WEEKS + MIN_WEEKDAY_OOS_TRIGGER_WEEKS` (10 + 5) |
| `calculate_fundamental_change` | çeyrek | 4 | `MIN_FUNDAMENTAL_QUARTERS` |

`test_weekday_pattern` için asgari **yaklaşıktır**: kapı yalnızca zarfı görür (`n_occurrences` toplamı); aracın kendi kararlılık eşikleri **tetik haftası** (`n_trigger_weeks`,
`results` içinde) üzerindendir ve `n_occurrences ≤ n_trigger_weeks`. `get_news_events` (haber sayısı) FEW_EVENTS değil `NEWS_SPARSE` konusudur, tabloda yoktur.

### 15.5 Kapı bundle seviyesinde sayar; Bilgisayar 2'nin etiket politikası özne bazlı sayacak
- **Kapı:** `BundleItem.n_events`, yani aracın **zarf düzeyindeki toplam sayısı** (havuzlu): retail rank çağrısında `n_events = 43`; hangi hissenin kaç olay verdiği görünmez.
- **Harness etiket politikası (planlanan, repoda henüz yok):** özne (hisse) bazında saymayı hedefliyor. Fark: havuzlu 43 ≥ 20 geçer, ama hisse bazında olay sayısı
  çok daha küçük olabilir (`schema_wishlist.md` §1.1: retail'de ham gözlemler BIMAS 43, MAVI 227, MGROS 128; bağımsız olaylar hisse başına 9–21). Yani **kapı FEW_EVENTS vermezken özne bazlı sayaç
  vermiş olabilir.** Çelişki değil, farklı birim: kapı = araç çıktısının yeterliliği, etiket politikası = hisse başına kanıt. Özne bazlı sayı artık `rank_sector_relative_strength` zarfındaki `per_ticker` alanında (şema 1.2.0); etiket politikası onu zarftan okuyabilir. Kapı hâlâ yalnızca bundle künyesini (havuzlu `n_events`) görür.
- **Eşik tekrarı:** `harness/gate_params.py` ve `harness/` içinde `MIN_EVENTS`, bayatlık veya olay minimumu **tekrarı yok**; `gate_params` yalnızca `n_events`'i künyeye kopyalar. Eşikler tek yerde (bu araç + `config/settings.py`).
- Dikkat: `bundle_items` künyeye ticker koymaz; kapı, bundle'daki öğeyle hangi hissenin eşleştiğini bilmez (peer kontrolü `tickers` param'ının tamamını kullanır).

### 15.6 Fiyat kontrolü ayrıntıları
- **Sıçrama sınıflandırması:** `tools/price_quality.py::classify_price_jumps` (§11.5). XU100 için ayrı sıçrama uyarısı üretilmez; rapordaki `n_price_jumps_over_limit` sayar.
- **`TickerQuality.n_price_jumps_over_limit`** sınıflandırmayla **aynı** kuralı kullanır (şema açıklaması 1.2.0'da bu kurala göre düzeltildi): mutlak `adj_close` getirisi `> limit + PRICE_JUMP_TOLERANCE_PP`, pencere `[start, min(end, as_of)]`.
- **`last_date`** pencerenin son satırıdır; **`last_data_age_days`** ise `as_of − (as_of'a kadarki son satır)` (pencere `end < as_of` ise erken bitebilir, bayatlık yine `as_of`'a göre ölçülür).
- **Eksik gün:** birleşik takvim (§11.4), `as_of`'a kesilmiş, hissenin **kendi ilk satırından** sonraki günler. **XU100'ün eksik günü raporlanır (`n_missing_trading_days`) ama uyarı üretmez**: v2'de 2 gün (2024-12-25, 2025-12-25)
  Yahoo'da bilinen bir **veri sınırlamasıdır** (§11.4) ve göreli getiriler ortak günlerle hesaplanır. Hissedeki aynı boşluk uyarıdır: 2024-04-09'da 30 hissenin yalnızca 9'unda veri var (THYAO ve MGROS dahil).
- **Kimlik:** ticker snapshot'ta yoksa, `as_of`'a kadar satırı yoksa ya da istenen pencerede satırı yoksa `WRONG_TICKER_OR_BROKEN_HISTORY` (HARD). XU100 `include_index` iken aynı kuralla.

### 15.7 Gerçek değerler (v1 / v2, `as_of = 2026-09-10`, `start = 2024-01-01`; testler: `tests/tools/test_check_data_quality_real.py`)
| Çağrı | Kapı | Bulgu |
|---|---|---|
| CCOLA, **v1** | HARD_BLOCK | `WRONG_TICKER_OR_BROKEN_HISTORY` 2024-08-01, getiri −%90,7479 (düzeltilmemiş %1000 bedelsiz) |
| CCOLA, **v2** | PASS | 673 satır, 0 eksik gün, 0 sıçrama; en büyük mutlak getiri %10,0 (2025-03-21) |
| CCOLA, v1, `as_of = 2024-07-31` | PASS | sıçrama `as_of` sonrası: görünmez (sızıntı testi); `as_of = 2024-08-01` ise HARD_BLOCK |
| THYAO, v2 | PASS_WITH_WARNINGS | `MISSING_TRADING_DAYS`×1 (2024-04-09); 672 satır; en büyük mutlak getiri %8,5616 (2026-04-08) |
| BIMAS+MAVI+MGROS + gerçek `rank` zarfı (`n_events = 43`), v2 | PASS_WITH_WARNINGS | yalnızca MGROS `MISSING_TRADING_DAYS`×1; EVENT_COUNT ve PEER_GROUP_SIZE çalıştı, sorun yok |
| 30 hisse, `2023-01-02 … 2023-03-01`, v1 ve v2 | PASS_WITH_WARNINGS | `PRICE_JUMP_OVER_LIMIT`×30, hepsi 2023-02-15 (THYAO +%21,6522); hard 0 |
| THYAO, v2, `as_of = 2026-12-31` | ANALYSIS_UNSAFE | `STALE_DATA`: son satır 2026-11-20, 41 gün (THYAO ve XU100) |

`issue_counts` çapaları (aynı çağrılar): CCOLA v1 `{WRONG_TICKER_OR_BROKEN_HISTORY: 1}`; CCOLA v2 `{}`; THYAO v2 `{MISSING_TRADING_DAYS: 1}`; 30 hisse 2023-01-02…2023-03-01 `{PRICE_JUMP_OVER_LIMIT: 30}`.

## 17. Haftanın günü örüntüsü (`test_weekday_pattern`, `tools/test_weekday_pattern.py`)

### 17.1 Hafta ve getiri tanımı
- **Gün getirisi** = `adj_close[d] / adj_close[önceki hafta içi günü] − 1` (Pzt için önceki Cuma). İki gün de snapshot'ta olmalı; yoksa (tatil veya veri boşluğu) getiri tanımsızdır ve
  o gün örüntüde ise **hafta dışlanır** (`n_excluded_holiday_weeks`, `HOLIDAY_WEEKS_EXCLUDED`). Tatilden sonraki günün getirisi iki günü kapsayacağı için kullanılmaz (bilinçli katılık).
- **Pencere ataması:** hafta, İLK örüntü gününün tarihi `[start, min(end, as_of)]` içindeyse o pencereye atanır. Son örüntü günü pencere sonunu aşarsa: `as_of`'u da aşıyorsa
  **ufku dolmamış** (`n_excluded_incomplete_horizon`, kural 2); aşmıyorsa (ör. IS bitişi Çarşamba) hafta **hiçbir pencereye girmez** (IS/OOS verisi karışmasın) ve `n_excluded_holiday_weeks`
  içinde sayılır. **Varsayım:** şemada üçüncü bir dışlama alanı olmadığı için bu hafta türü tatil sayacına eklenir (alan açıklamasının hafif genişlemesi; `HOLIDAY_WEEKS_EXCLUDED` metni dökümü verir).
  Örnek (Soru 2): `as_of = 2026-09-10` Perşembe; 7–11 Eylül haftasının Cuması 11.09 `as_of` sonrası → OOS'ta `n_excluded_incomplete_horizon = 1`.
- **TRIGGER haftası:** tüm TRIGGER günleri beklenen yönde (`> 0` UP, `< 0` DOWN; sıfır eşleşmez) ve varsa conditioning koşulu. **OUTCOME getirisi** = OUTCOME günlerinin bileşik getirisi.
  `n_occurrences` = tetik haftası **ve** her OUTCOME günü beklenen yönde. `hit_rate_pct = n_occurrences / n_trigger_weeks`.
- **Koşulsuz taban** (`unconditional_*`): aynı OUTCOME günleri, pencerenin TÜM tam haftaları (tetik haftaları dahil). `per_day.unconditional_*` penceredeki TÜM işlem günlerinin ortalama/medyanıdır.
- **`expected_occurrences_if_independent`** = `n_weeks_complete × Π (günün beklenen yönde olma oranı)` (tüm örüntü günleri, conditioning yok sayılır).
- **Maliyet:** `cost_adjusted_outcome_mean_return_pct = yön × ort − tur maliyeti` (§5; UP: `ort − 0,5`, DOWN: `−ort − 0,5`). TRIGGER haftası başına tek tur.

### 17.2 Anlamlılık testi: permütasyon (rastgeleleştirme)
Tüm tam haftalardan rastgele `k` hafta (k = tetik haftası sayısı) iadesiz çekilir; istatistik `ort(k hafta) − ort(tüm haftalar)` (şemadaki `outcome_mean_diff_vs_unconditional_pct` ile **aynı fark, aynı baz**).
Getiriler yönlüdür (DOWN çıktıda işaret çevrilir) ve test **tek yönlüdür** (beklenen yön). `p_value_raw = (sayım + 1) / (B + 1)`, `B = 10 000`, sabit seed (`PERMUTATION_SEED = 481`; modül sabitleri), böylece
aynı girdi aynı p'yi verir. Gerekçe: k ≈ 10–20 ve getiriler kalın kuyruklu iken normallik varsayımı gerekmez; scipy bağımlılığı yoktur; "rastgele k hafta çeksek bu kadar iyi çıkar mıydı?" diye açıklanır.
- **`t_stat`** = `fark / (s_tüm × √(1/k − 1/N))` (iadesiz örnekleme). **Yönlüdür: pozitif = beklenen yönde.** Bilgi amaçlıdır; karar `p_value_adjusted`'a dayanır.
- **OOS:** `t_stat`/p yine hesaplanır (sayısal alanlar hep dolu) ama karar OOS p-değerini KULLANMAZ (§8).
- **Çoklu test (kural 11):** örüntü (beş gün birlikte) **tek birleşik hipotezdir**: tek p. `per_day` satırları betimleyicidir, teste girmez. `p_value_adjusted = min(1, p_raw × n_tests_declared)` (Bonferroni; yuvarlanmış `p_raw`'dan türer).
  `n_tests_declared` **çağıranın beyanıdır**; araç denenmiş diğer örüntüleri bilemez, bu yüzden her zarfta `MULTIPLE_TESTING_RISK` uyarısı vardır.
- **Örtüşme:** her hafta tek gözlemdir; getiri aralıkları (Pzt–Cum) hiçbir haftada başka haftayla kesişmez. Kalan risk: haftalar arası otokorelasyon ve oynaklık kümelenmesi; permütasyon testi haftaların
  değiştirilebilir olduğunu varsayar (bir sınırlamadır).

### 17.3 Conditioning (`XU100_UP` / `XU100_DOWN`): look-ahead'siz tanım
Şema yorumu "haftalık XU100 getirisi" der; haftanın tamamı Perş/Cum OUTCOME günlerini de kapsar ve koşula sızardı. Bu yüzden XU100 getirisi **önceki Cuma kapanışından (yoksa o güne kadarki son satır) son TRIGGER gününün
kapanışına** ölçülür: tetik kararının verildiği ana kadar bilinen bilgi. Koşul yalnızca tetik tanımına eklenir; koşulsuz taban (tüm tam haftalar) ve hafta sayıları değişmez. Sapma `docs/schema_wishlist.md` §8'de.

### 17.4 Desteklenmeyen örüntüler (`status = ERROR`, `error.code = UNSUPPORTED_PATTERN`)
TRIGGER günü olmayan örüntü (tek gün etkisi: sıfıra karşı test henüz yok) ve karışık yönlü OUTCOME (yönlü maliyet tanımsız). Pencere `as_of` sonrasında başlıyorsa `INVALID_WINDOW`; hisse snapshot'ta yoksa `NO_DATA`.

### 17.5 `oos_degradation_flag` karşılığı
`TestWeekdayPatternResult`'ta `oos_degradation_flag` alanı yoktur; karşılığı §8'in kararıdır: (c) OOS maliyet sonrası ≤ 0 → `OOS_COST_ADJ_NOT_POSITIVE`, (d) OOS isabet < %50 → `OOS_HIT_RATE_TOO_LOW`
(+ işaret/etki kodları). §9'daki "IS'ten 15 pp düşüş" kuralı bu araçta uygulanmaz.

### 17.6 Gerçek değerler (v2, `as_of = 2026-09-10`; kalıp: MON-DOWN, TUE-DOWN, WED-DOWN | THU-UP, FRI-UP; IS 2024-01-01…2025-12-31, OOS 2026-01-01…2026-09-10; test: `tests/tools/test_weekday_pattern.py`)
| Hisse | IS toplam / dışlanan(tatil) / tam | IS tetik / olay (hit) | IS ort. vs koşulsuz (%) | IS `p_raw` | OOS tetik / olay | Karar |
|---|---|---|---|---|---|---|
| THYAO | 105 / 20 / 85 | 18 / 5 (%27,8) | 1,3017 vs 0,7196 | 0,1205 | 3 / 0 | `UNSTABLE` (`IS_NOT_SIGNIFICANT`) |
| EREGL | 105 / 20 / 85 | 11 / 3 (%27,3) | 0,8320 vs 0,4532 | 0,3152 | 3 / 0 | `UNSTABLE` (`IS_NOT_SIGNIFICANT`) |
| ASELS | 105 / 20 / 85 | 4 / 3 | 2,0502 vs 1,1003 | 0,2602 | 4 / 1 | `INSUFFICIENT_DATA` (`IS_TOO_FEW`) |
| BIMAS | 105 / 20 / 85 | 4 / 3 | 0,8966 vs −0,0321 | 0,2890 | 2 / 1 | `INSUFFICIENT_DATA` (`IS_TOO_FEW`) |

OOS: 36 hafta, 9 dışlanan, 1 ufku dolmamış, 26 tam (dört hissede de aynı). Yapısal not: üç gün üst üste düşüş koşulu haftaların yaklaşık 1/8'idir; 26 tam OOS haftasından beklenen tetik ≈ 3, eşik 5'in altında.
Bu örüntü için OOS'ta `STABLE` pratikte ulaşılamazdır (IS anlamlı çıksa bile `OOS_TOO_FEW`). Bu bir hata değil, kısa örneklemin dürüst sonucudur. Dışlanan hafta oranı yüksektir (IS'te 105'in 20'si, ~%19: BIST tatilleri,
THYAO'da 2024-04-09 veri boşluğu, sınır haftası); `HOLIDAY_WEEKS_EXCLUDED` uyarısı verilir.

## 18. Destek / direnç (`find_support_resistance`, `tools/find_support_resistance.py`)
- **Fiyat:** adjusted ölçekli OHLC (§11.3); `last_close` ve tüm seviyeler aynı ölçektedir, ham işlem fiyatı olmayabilir (uyarı metni).
- **Nedensel pivot:** `i` barı pivot tepe: `high[i] >` önceki `w` barın en yükseği **ve** `>=` sonraki `w` barın en yükseği (`w = pivot_window`, varsayılan 5); pivot dip simetrik (`low`). Onay için `i + w` bar gerekir:
  aralığın (`[start, min(end, as_of)]`) son `w` barındaki pivot ONAYLANMAMIŞTIR ve kullanılmaz (`as_of` anında henüz bilinemez; test: aynı veride bu pivot ancak `w` bar sonra görünür). Düz bölge pivot üretmez.
- **Kümeleme:** tepe ve dip pivotları tek havuzda, fiyata göre; küme en düşük fiyatına çıpalıdır (`p <= çıpa × (1 + tolerance_pct/100)`). Tepe/dip ayrımı yapılmaz çünkü kırılan direnç destek olabilir (rol değişimi).
  Seviye = küme ortalaması; `zone_low/high` = küme min/max; `touch_count` = kümedeki pivot sayısı (`min_touches` altı elenir). **Dokunuş = onaylı pivot** (fiyatın seviyeye gelip döndüğü bar); yalnızca bölgeye yaklaşan barlar sayılmaz.
- **Tip son kapanışa göredir:** seviye ≤ `last_close` → `SUPPORT`, aksi `RESISTANCE`. `nearest_support` = en yüksek destek seviyesi, `nearest_resistance` = en düşük direnç seviyesi (tüm kümelerden; listelenenlerle aynı).
- **`strength`** = `Σ 0,5^(yaş/126) × min(2, pivot barı hacmi / aralık medyan hacmi)`; yaş = o bardan son bara bar sayısı (yarı ömür 126 bar ≈ 6 ay; hacim ağırlığı üst sınırı 2). Sabitler modülde (`RECENCY_HALF_LIFE_BARS`, `VOLUME_WEIGHT_CAP`),
  ileri getiriye bakılmadan seçilmiştir. Birimsiz bir skordur; seviyeler arası göreli karşılaştırma içindir.
- **Mesafeler (şema 1.3.0):** `nearest_support_distance_pct = (last_close − nearest_support) / last_close × 100`, `nearest_resistance_distance_pct = (nearest_resistance − last_close) / last_close × 100` (pozitif; yuvarlanmış değerlerden türer). THYAO: 0,6929 ve 0,923.
- **Hafif zarf:** her yönde en yakın 5 seviye listelenir (`MAX_LEVELS_PER_SIDE`); sıra: önce dirençler (yakından uzağa), sonra destekler (yakından uzağa). Fazlası varsa uyarıda toplam sayı yazılır.
- **Gerçek örnek (v2, `as_of = 2026-09-10`, varsayılan parametreler):** THYAO `last_close = 299,25`, `nearest_support = 297,1765` (9 dokunuş, son 2026-05-05), `nearest_resistance = 302,012` (5 dokunuş, son 2026-06-03).
  Seviye fiyatları adjusted ölçeklidir. Bu seviyeler geçmiş pivotlardır; gelecekte tutacağı garanti değildir (`HISTORICAL_ONLY`).

## 19. Teknik dönüş olayları (`detect_reversal_events`, `tools/detect_reversal_events.py`)
### 19.1 Kapsam
Tek yönlü dört aile: `BB_LOWER_TOUCH` (UP), `BB_UPPER_TOUCH` (DOWN), `RSI_LOCAL_TROUGH` (UP), `RSI_LOCAL_PEAK` (DOWN). Olayları hem yukarı hem aşağı yönlü olabilen aileler
(`BB_MID_TEST`, `SUPERTREND_FLIP`, `KAMA_*`, `ICHIMOKU_*`, `SR_TOUCH`) `status = ERROR`, `error.code = UNSUPPORTED_EVENT_FAMILY` döner (neden: sonuçta tek bir `expected_direction` var; çözüm önerisi `schema_wishlist.md` §11, `event_direction`).

### 19.2 Olay tanımı
- **Ham olay günü:** Bollinger'da §4'teki temas günü (`touch_mode`); RSI'da yerel dip/zirve **teyit günü** (`RSI[t−1]` son 5 değerin en küçüğü/büyüğü ve `RSI[t]` yön değiştirdi; bkz. `calibration_thresholds.md`).
- **Olay = ardışık ham gün serisinin İLK günü** (önceki işlem günü ham gün değilse). Gerekçe: ardışık temas günlerini ayrı olay saymak `n_events`'i şişirir ve ileri pencereleri örtüştürür (rank'taki cooldown sorunuyla aynı).
  `n_raw_event_days` (şema 1.3.0): grubun olaylarına ait serilerin toplam ham gün sayısı (koşulsuz grupta: analiz penceresinde başlayan tüm serilerin toplamı). `n_overlapping_forward_windows`: bir sonraki olay en fazla `max(forward_horizons)` işlem günü sonraysa sayılır.
- **İleri getiri:** olay günü kapanışından `t+h` kapanışına, adjusted. Başarı: beklenen yönde `> 0` (eşitlik başarı değil). `reversal_strength_pct` (MFE) = `t+1..t+h` kapanışları boyunca beklenen yönde en büyük hareket, **en az 0**
  (hiç lehte kapanış yoksa 0). `ForwardReturn.return_pct` HAM getiridir; `HorizonStats` (ortalama, medyan, maliyet sonrası) YÖNLÜdür (DOWN'da işaret çevrilir: pozitif = beklenen yönde). Maliyet sonrası = yönlü ortalama − tur maliyeti (§5).
- **Ufku dolmamış olay (kural 2):** `t+h` veri sonunu (`as_of`) aşarsa o ufkun istatistiğine girmez, `n_excluded_incomplete_horizon`; olay kaydında `complete = false`, getiri alanları `null`. Zarfta `n_events` = koşulsuz grup `n_events_detected`; `n_excluded_incomplete_horizon` = koşulsuz grubun EN UZUN ufuktaki dışlananı.
- **Baz:** aynı dönem (`t ≥ analysis_start`), aynı ufuk, tüm günler (yönlü getiri; olay şartı yok, örtüşen pencereler dahil). `mean_diff_vs_baseline_pct` = olay ortalaması − baz ortalaması.
- **IS/OOS:** `split_date` verilirse olay günü `< split_date` IS, `≥ split_date` OOS. `oos_degradation_flag` §9 kuralı (`tools/stability.py`); OOS tamamlanmış olay `< MIN_OOS_EVENTS` ise `false` + `OOS_TOO_SMALL`. Uyarılar grup başına tek satırdır.
- **Birleşik koşullar:** olay koşuldan bağımsız belirlenir, koşul olayı OLAY GÜNÜNÜN gösterge durumlarına göre süzer (durum `None` ise eşleşmez). Koşullu grup koşulsuz grubun alt kümesidir. Her koşul ek bir karşılaştırmadır (`MULTIPLE_TESTING_RISK`; araç p-değeri üretmez).
- **Rejim kırılımı** (en uzun ufuk, tamamlanmış olaylar): `XU100_UP/DOWN` = olay gününe kadar son 20 işlem günü XU100 getirisi `> 0` / `≤ 0`; `HIGH/LOW_VOLATILITY` = hissenin 20 günlük volatilitesi, o güne kadarki tüm 20 günlük volatiliteler medyanının üstünde/altında (genişleyen, nedensel medyan). **Varsayım:** şema rejim tanımını vermiyor; bu tanımlar ekibe aittir.
- `events` listesi en son 100 olayı taşır (`events_truncated`).

### 19.3 Gerçek örnek (v2, ASELS, `BB_LOWER_TOUCH`, `touch_mode = close`, `as_of = 2026-09-10`, analiz 2024-01-01 → 2026-09-10, `split_date = 2026-01-01`, ufuklar 1/3/5/10; test: `tests/tools/test_detect_reversal_events.py`)
- **Koşulsuz:** 17 ham temas günü → **12 olay** (IS 9, OOS 3), 5 olayın ileri penceresi bir sonrakiyle çakışıyor, ufku dolmamış 0.
  Olaylar: 2024-03-26, 04-02, 05-29, 06-11, 07-01, 08-02, 2025-10-16, 11-06, 11-11, 2026-05-21, 05-26, 06-04.

| Ufuk | n | İsabet % | Ort. getiri % | Medyan % | Maliyet sonrası ort. % | Baz isabet % | Baz ort. % | Fark (ort.) pp | IS / OOS isabet % |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 12 | 66,67 | 0,8680 | 1,0194 | 0,3680 | 52,61 | 0,3558 | +0,5122 | 55,56 / 100,0 |
| 3 | 12 | 66,67 | 1,9797 | 0,8195 | 1,4797 | 58,30 | 1,0653 | +0,9144 | 66,67 / 66,67 |
| 5 | 12 | 66,67 | 2,9608 | 3,1341 | 2,4608 | 59,22 | 1,7803 | +1,1805 | 66,67 / 66,67 |
| 10 | 12 | 50,00 | 2,7972 | −0,0546 | 2,2972 | 61,78 | 3,6015 | −0,8043 | 55,56 / 33,33 |

- **Birleşik (Soru 3):** `rsi_trough_high_volume` (RSI `LOCAL_LOW` + hacim `HIGH` aynı gün): **0 olay**; `supertrend_bearish_below_cloud` (Supertrend `BEARISH` + Ichimoku `BELOW_CLOUD`): **5 olay**.
- **Yorum sınırları:** ASELS'in analiz dönemi yukarı eğilimlidir (baz isabet %52–62), 10 günde olay isabeti bazın altındadır; olay sayısı `MIN_EVENTS`'in (20) altındadır (`FEW_EVENTS`), OOS 3 olaydır (`OOS_TOO_SMALL`). Hiçbiri kesin sonuç değildir (`HISTORICAL_ONLY`).
- **Not (RSI koşulu):** RSI durumu olay GÜNÜNDE değerlendirilir. Bollinger teması fiyat düşerken oluştuğundan, aynı gün RSI'ın yukarı dönmesi (teyit) nadirdir; bu yüzden "RSI dibi + yüksek hacim" birleşik koşulu çoğu hissede 0–birkaç olay verir. "Son k günde RSI dibi" gibi geriye bakan bir koşul ayrı bir tasarım kararıdır (şimdilik yok).

## 20. Backtest (`run_backtest`, `tools/run_backtest.py`)
### 20.1 Kapsam (onaylı plan) ve sınırlar
- **Varyant:** `A` (yalnızca teknik/sinyal), `B` (+ sektör filtresi: sektör gücü `WEAK` olan sinyaller elenir). `C/D/E` → `UNSUPPORTED_VARIANT` (bilanço, makro, haber verisi gerekir).
- **Sinyal:** `CATCH_UP`, `WEEKDAY`, `REVERSAL` (yalnız UZUN yön: `BB_LOWER_TOUCH`, `RSI_LOCAL_TROUGH`; `BB_UPPER_TOUCH`/`RSI_LOCAL_PEAK` → `UNSUPPORTED_DIRECTION`, karışık aileler → `UNSUPPORTED_EVENT_FAMILY`). `FUNDAMENTAL` → `UNSUPPORTED_SIGNAL_TYPE`.
  WEEKDAY'de OUTCOME günleri UP olmalıdır; OUTCOME günleri sinyal ÜRETMEZ (yalnızca yön), sinyali TRIGGER günleri verir. **Yalnızca uzun yön** (borç/kısa satış maliyeti modellenmez). Hepsi `signal_params` ile: bilinmeyen anahtar `INVALID_PARAMS`.
- **Optimizasyon yok:** araç parametre taraması yapmaz; parametreler çağırandan gelir. Aynı veride çok strateji denemek seçim yanlılığı üretir (`MULTIPLE_TESTING_RISK` uyarısı; bu araçta `n_tests_declared` yoktur).

### 20.2 Zamanlama (signal shifting) ve işlem tanımı
- Sinyal `t` kapanışında yalnızca `≤ t` verisiyle üretilir. **Giriş = `t + signal_lag_days` kapanışı, çıkış = giriş + `holding_days` kapanışı** (adjusted, hissenin kendi barları). `signal_lag_days ≥ 1` (şema); `signal_date < entry_date ≤ exit_date`.
  WEEKDAY'de bunun anlamı: tetik, haftanın son TRIGGER gününde tamamlanır (örn. Çarşamba), giriş en erken ertesi gün kapanışıdır; o günün getirisi (örn. Perşembe) yakalanamaz.
- **Çakışmasız işlem:** aynı hissede önceki işlemin çıkış gününden ÖNCE gelen sinyal alınmaz (`n_signals` kabul edilen sinyaldir; alınmayanlar `HISTORICAL_ONLY` uyarısında sayılır). Hisseler arası ilişki yoktur.
- **Ufku dolmamış (kural 2):** çıkışı dönem sonunu (`min(end, as_of)`) aşan sinyal SAYILIR (`n_signals`) ama işlem yoktur; `n_excluded_incomplete_horizon`; metrik, `trade_log`, `n_winning/losing_trades` ve `last_exit_date`'e girmez. Açık pozisyon `as_of`'ta mark-to-market EDİLMEZ.
  Veri dönem sonunda kesilir: dönem sonrası bar hiçbir hesaba girmez.
- **Maliyet:** işlem `net = brüt − tur maliyeti` (§5, varsayılan 0,5 pp). Portföy eğrisinde maliyet işlemin İLK ve SON tutma gününe yarı yarıya düşülür (tek günlükte tamamı); bu yüzden eğri kümülatifi `brüt − 0,5`'ten az sapar.
- **`n_losing_trades`** = net getirisi `≤ 0` işlem (yanlış pozitif). `low_signal_flag = n_signals < MIN_EVENTS` (+ `LOW_SIGNAL_COUNT`).

### 20.3 Portföy ve metrikler
- **Günlük strateji getirisi** = o gün açık pozisyonların (giriş gününden SONRAKİ barlar, çıkış günü dahil) eşit ağırlıklı ortalaması; pozisyon yoksa 0 (nakit, `rf = 0`). Takvim: evrendeki hisselerin işlem günlerinin birleşimi, `start`'tan itibaren.
- `cumulative_return_pct` = `Π(1+r) − 1`; `annualized_return_pct` = `(1+kümülatif)^(252/gün) − 1`; `sharpe_ratio` = `ort/std(ddof=1)·√252` (`std = 0` → `null`); `max_drawdown_pct` = özsermaye eğrisinin tepeden en büyük düşüşü (≤ 0);
  `win_rate_pct`, `avg/median_trade_return_pct` = işlem net getirileri (brüt metrikte brüt); `exposure_pct` = en az bir pozisyonun açık olduğu gün oranı.
- **Benchmark'lar** (günlük, aynı takvim): `BUY_AND_HOLD` = evrenin eşit ağırlıklı günlük ortalaması; `XU100`; `SECTOR` = evrenin peer grubunun TÜM üyelerinin günlük medyanı (evren tek peer grubunda olmalı, aksi `INVALID_PARAMS`; ≤ 2 üyeli grupta `SMALL_PEER_GROUP`/`SOLO_PEER_GROUP`).
  `cumulative_return_diff_pct = strateji net − benchmark`, `sharpe_diff` aynı şekilde. İşlem istatistiği benchmark'ta yoktur (`n_trades = 0`).
- **Varyant B sektör gücü:** üyelerin `sector_window` (varsayılan 20 bar) getirisi medyanı − XU100 aynı pencere getirisi; `≥ +2 pp` STRONG, `≤ −2 pp` WEAK, arası NEUTRAL (`config` eşikleri §6). STRONG/NEUTRAL korunur; WEAK veya hesaplanamayan elenir; tek hisseli grupta filtre uygulanmaz (`SOLO_PEER_GROUP`).
- **CATCH_UP:** `lag_window` (varsayılan 20) getirisi − (kendisi DAHİL) evren medyanı `≤ −lag_threshold_pp` (varsayılan 3,0) → sinyal. Evren ≥ 2 hisse; ortak günler (rank ile aynı kural).

### 20.4 Bölünmeler ve `oos_degradation_flag`
- `strategy.train_end` verilirse `TRAIN = [start, train_end]`, `validation_end` ile `VALIDATION`, sonrası `TEST` (OOS). `walk_forward = true` (train_end şart): TEST yerine `wf_test_days` (varsayılan 126) işlem günlük ardışık `WALK_FORWARD` blokları (son blok kısmi).
  **Hiçbir parametre eğitim diliminde ayarlanmaz**; bölünme yalnızca dönemler arası kararlılığı gösterir.
- Dilim `n_signals` = sinyal tarihi dilimde olan kabul edilmiş sinyaller (dolmamışlar dahil; toplamları `n_signals`). Dilim getiri/Sharpe/drawdown/maruziyet = o tarihlerdeki küresel günlük strateji getirisi dilimi; işlem istatistikleri (`n_trades`, kazanma oranı) = sinyal tarihi dilimde olan işlemler.
  `benchmark_diff_pct` = dilim net kümülatifi − ilk benchmark'ın (sıralı ad) aynı dilim kümülatifi.
- **`oos_degradation_flag`** §9 kuralı (`tools/stability.py`): IS = sinyal tarihi `≤ validation_end ya da train_end` olan işlemler, OOS = sonrası; OOS işlem `< MIN_OOS_EVENTS` → `false` + `OOS_TOO_SMALL`. `train_end` yoksa `null`.
- **`last_exit_date`** (şema 1.3.0): TÜM işlemlerin en geç `exit_date`'i; `trade_log` en çok `BACKTEST_TRADE_LOG_MAX` (200) son işlemdir (`trade_log_truncated`), `last_exit_date` kısaltmadan etkilenmez.

### 20.5 Gerçek örnekler (v2, `as_of = 2026-09-10`, `start = 2024-01-01`, `train_end = 2025-12-31`, tur maliyeti 0,5 pp; test: `tests/tools/test_run_backtest.py`)
| | Retail (BIMAS, MAVI, MGROS) `CATCH_UP`, lag 20, eşik 3 pp, tut 10, gecikme 1 | THYAO `WEEKDAY` (Pzt-Sal-Çar düşüş → Per-Cum yükseliş), tut 2, gecikme 1 |
|---|---|---|
| Sinyal / dolmamış / işlem | 65 / 2 / 63 (39 kazanan, 24 kaybeden) | 24 / 0 / 24 (10 / 14) |
| Brüt kümülatif | %112,29 | %−12,36 |
| Net kümülatif (Sharpe, maks. düşüş) | %62,08 (0,7253; −%36,20) | %−22,31 (−0,7922; −%27,94) |
| Benchmark kümülatif | AL-TUT %104,24; SECTOR %63,03; XU100 %92,69 | AL-TUT %34,00; XU100 %91,56 |
| TRAIN / TEST sinyal | 48 / 17 | 19 / 5 |
| `oos_degradation_flag` | `true` | `true` |
- **Yorum sınırları:** retail net getirisi AL-TUT'un 42,2 pp, XU100'ün 30,6 pp altındadır; yalnızca peer medyanına yakındır (−0,9 pp). Maruziyet %84 olduğundan strateji büyük ölçüde sürekli açık pozisyondur. THYAO örüntü stratejisi negatiftir
  ve OOS 5 işlemdir (eşik sınırında). Hiçbiri kanıt değil, geçmiş gözlemdir (`HISTORICAL_ONLY`).
