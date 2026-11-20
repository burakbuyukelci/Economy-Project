# Veri sözlüğü ve tanımlar

> Durum: **Bölüm 1-6 sözleşmeyle birlikte yazıldı (schemas v1.0.0).**
> Bölüm 7 (fiyat verisinin kaynağı, aralığı, adjusted/unadjusted, eksik gün yönetimi, gerçek sayılar)
> veri indirme adımında (`scripts/download_prices.py`) doldurulacak.

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
  (varsayılan 5 bps, **öneri; ekip onayına tabi**).
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

## 7. Fiyat verisi (Adım 4'te doldurulacak)
Kaynak, tarih aralığı (2023-01-01'den; analiz penceresi varsayılan 2024-01-01), `adj_close` varsayılan /
ham `close` da saklanır, eksik gün yönetimi, günlük fiyat limitini (`PRICE_JUMP_LIMIT_PCT = %10`) aşan
sıçramaların `check_data_quality` ile işaretlenmesi: bkz. veri katmanı commit'i.
