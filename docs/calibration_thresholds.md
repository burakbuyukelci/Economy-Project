# Gösterge durum eşikleri: kalibrasyon

`calculate_indicators` aracındaki kategorik durumların (`kama_slope`, `volume_regime`) eşikleri burada gerekçelendirilir.
Eşikler `config/settings.py` içindedir; tabloları üreten betik: `scripts/calibrate_indicator_thresholds.py`
(`python -m scripts.calibrate_indicator_thresholds`; ağ yok, `snap_2026-11-20_v2` okur).

## İlke (bağlayıcı)
- Eşikler **ileri getiriye / olay sonuçlarına hiç bakılmadan**, yalnızca **gösterge dağılımına** (KAMA eğimi ve hacim
  z-skoru) göre seçildi. Betik getiri hesaplamaz.
- Eşikler, sonradan olay sonuçlarına (isabet oranı, ortalama getiri, backtest) bakılarak **DEĞİŞTİRİLMEZ**.
  Değişiklik gerekirse yalnızca gösterge dağılımı gerekçesiyle yapılır ve bu dosyadaki tablolar yeniden üretilip tarihiyle
  eklenir. Aksi halde eşik seçimi, olay istatistiklerinde gizli bir çoklu-test / veri kazıma kaynağı olur.
- Örnek: 30 hisse (`config/universe.csv`), 20.159 hisse-gün, adjusted fiyat, 2024-01-01 → 2026-09-10, KAMA(10, 2, 30),
  hacim z penceresi 20. Isınma tüm geçmişten (2023-01-02) hesaplandı; yalnızca pencere içindeki günler sayıldı.

## Seçilen değerler
| Sabit | Değer | Anlam |
|---|---|---|
| `KAMA_FLAT_SLOPE_PCT` | 0.10 | KAMA'nın 1 günlük % değişimi. `> +0.10` RISING, `< −0.10` FALLING, arası FLATTENING |
| `VOLUME_HIGH_Z` | 1.0 | z > 1.0 → HIGH |
| `VOLUME_LOW_Z` | −1.0 | z < −1.0 → LOW; arası NORMAL |
| `VOLATILITY_WINDOW` | 20 | gün; yalnızca kütüphane (`rolling_volatility`) |
| `RETURN_HORIZONS` | [1, 5, 20] | gün; yalnızca kütüphane (`simple_returns`) |

## KAMA eğimi
`kama_slope_pct_t = (KAMA_t / KAMA_{t-1} − 1) × 100`.

|eğim| dağılımı (yüzde): p25 = 0,04 · medyan = 0,16 · p75 = 0,60 · p90 = 1,31 · p95 = 1,89 · p99 = 3,31.
İşaretli dağılım: p1 = −2,42 · p5 = −1,09 · p10 = −0,57 · p25 = −0,10 · medyan = 0,01 · p75 = 0,26 · p90 = 0,94 · p95 = 1,51 · p99 = 2,99.

Aday eşikler (sınıf payları %; son iki sütun hisse bazında FLATTENING payının en küçük/en büyük değeri):

| Eşik (%) | RISING | FLATTENING | FALLING | FLAT min (hisse) | FLAT max (hisse) |
|---|---|---|---|---|---|
| 0,02 | 45,45 | 16,52 | 38,03 | 11,61 | 23,36 |
| 0,05 | 39,20 | 29,88 | 30,91 | 23,66 | 38,69 |
| **0,10 (seçildi)** | 33,91 | 41,02 | 25,07 | 34,67 | 49,85 |
| 0,15 | 30,29 | 48,33 | 21,38 | 41,96 | 58,04 |
| 0,20 | 27,62 | 53,46 | 18,92 | 46,43 | 62,50 |
| 0,30 | 23,44 | 61,14 | 15,42 | 53,12 | 71,58 |

Gerekçe: 0,10'da FLATTENING payı (~%41) anlamlı ama baskın değil ve hisseler arası yayılım dar (%35–50). 0,05 de savunulabilirdi
(üç sınıf ≈ üçte bir). RISING > FALLING asimetrisi (%34 / %25), dönemin nominal yükselişinden gelir; eşik bunu simetriye zorlamaz.
Sınırlama: eşik mutlak yüzdedir; oynaklığı yüksek hisselerde FLATTENING payı daha düşüktür (hisse bazında aralık yukarıda).

## Hacim z-skoru
`z_t = (v_t − ort) / std`; ort ve std son 20 günden, bugün dahil, popülasyon std (ddof=0). Pencere 20 olduğundan z üst sınırı √19 ≈ 4,36.

Dağılım: p1 = −1,78 · p5 = −1,34 · p10 = −1,12 · p25 = −0,74 · medyan = −0,21 · p75 = 0,58 · p90 = 1,51 · p95 = 2,15 · p99 = 3,27
(sağa çarpık: hacim log-normal benzeri).

| HIGH z > | LOW z < | HIGH | NORMAL | LOW | HIGH hisse min–max | LOW hisse min–max |
|---|---|---|---|---|---|---|
| **1,0 (seçildi)** | **−1,0 (seçildi)** | 16,55 | 69,60 | 13,84 | 14,56 – 19,32 | 10,71 – 16,67 |
| 1,5 | −1,0 | 10,12 | 76,03 | 13,84 | 8,77 – 11,31 | 10,71 – 16,67 |
| 1,0 | −0,5 | 16,55 | 46,99 | 36,46 | 14,56 – 19,32 | 32,84 – 40,27 |
| 2,0 | −1,0 | 6,02 | 80,13 | 13,84 | 4,61 – 7,89 | 10,71 – 16,67 |
| 1,5 | −0,5 | 10,12 | 53,42 | 36,46 | 8,77 – 11,31 | 32,84 – 40,27 |

Gerekçe: ±1σ simetrik ve yorumlaması kolay; hisseler arası dağılım homojen (HIGH %14,6–19,3). Not: HIGH ve LOW payları
birbirine eşit değildir (sağa çarpıklık). Birleşik koşullarla (ör. dip + yüksek hacim) olay sayısı hızla düşer; `FEW_EVENTS` uyarısı bunu yakalar.

## RSI yerel dip/zirve durumu (`detect_reversal_events`, 2026-11-21)
| Sabit | Değer | Yer | Anlam |
|---|---|---|---|
| `RSI_LOCAL_WINDOW` | 5 | `tools/detect_reversal_events.py` | `t` günü: `RSI[t−1]`, `RSI[t−5..t−1]` penceresinin en küçüğü ve `RSI[t] > RSI[t−1]` ise `LOCAL_LOW`; en büyüğü ve `RSI[t] < RSI[t−1]` ise `LOCAL_HIGH`; aksi `NEUTRAL` |
| `REGIME_WINDOW` | 20 | `tools/detect_reversal_events.py` (= `VOLATILITY_WINDOW`) | rejim kırılımı: XU100 son 20 gün getirisi ve hissenin 20 günlük volatilitesi |

**Getirilere bakılmadan seçildi.** `w = 5` bir işlem haftasıdır; seçim ileri getiriye, isabet oranına ya da olay sonuçlarına bakılmadan, tanımın okunabilirliği (kısa vadeli yerel dönüş) gerekçesiyle yapıldı.
Bu sabit sonradan olay sonuçlarına bakılarak DEĞİŞTİRİLMEZ (üstteki ilkeyle aynı): aksi halde eşik seçimi olay istatistiklerinde gizli bir çoklu-test kaynağı olur.
Sabitler araç modülündedir (`config/` ortak bölgedir; taşınması istenirse onay gerekir). **Teyit günü olay günüdür:** yerel dip ancak ertesi gün (RSI dönünce) bilinebilir; olay günü bilginin ilk mümkün olduğu gündür, bu yüzden look-ahead yoktur.
