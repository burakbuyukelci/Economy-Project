# Rapor 05 — Makro bağlam ve kur/faiz–hisse ilişkisi

> **Otomatik üretildi** (`python -m experiments.make_reports`, model yok): her sayı bir araç çıktısındandır; analiz tarihi **2026-09-10**, veri dönemi 2024-01-01 – 2026-09-10. Veri sürümleri: fiyat `snap_2026-11-20_v2`, bilanço `fundamentals_2026-11-23_v2`, makro `macro_2026-11-09_v2`.
> Eğitim/araştırma amaçlıdır; **yatırım tavsiyesi ve gelecek getiri garantisi değildir**. Senaryo: Makro katman (§15) ve Soru 5.

## Yöntem
Makro seriler TCMB/EVDS'den, **yayın tarihine** göre hizalanır; resmî tatil günleri son gözlemle ileri doldurulur (geriye doldurma yok). İlişki: 5 işlem günlük örtüşmeyen bloklarda kur değişimi (%) ile hisse getirisi; eş zamanlı (gecikme 0) ve öncü (gecikme 5) korelasyon; faiz için seviye farkı. **TCMB serisi politika faizi değil, fiili ağırlıklı ortalama fonlama maliyetidir.** Permütasyon p-değeri (B=10 000), Bonferroni için beyan edilen toplam test sayısı **90** (30 hisse × 3 ilişki).

## 1. Son gözlemler (analiz tarihi itibarıyla yayımlanmış)
| Seri | Gözlem tarihi | Yayın tarihi | Değer |
|---|---|---|---|
| CPI_ANNUAL | 2026-08-31 | 2026-09-03 | 31.5073 |
| CPI_MONTHLY | 2026-08-31 | 2026-09-03 | 1.8442 |
| EURTRY | 2026-09-10 | 2026-09-10 | 56.306 |
| TCMB_FUNDING_COST | 2026-09-10 | 2026-09-10 | 37.09 |
| USDTRY | 2026-09-10 | 2026-09-10 | 48.3905 |

## 2. Hisse bazında ilişki (düzeltilmiş p = ham p × test sayısı)
| Hisse | USDTRY eş zamanlı korelasyon | düzeltilmiş p | USDTRY öncü korelasyon | düzeltilmiş p | Fonlama maliyeti (fark) korelasyon | düzeltilmiş p | OOS bozulma (eş zamanlı) | Gözlem (blok) |
|---|---|---|---|---|---|---|---|---|
| AKBNK | -0.261 | 0.387 | 0.0159 | 1 | -0.0636 | 1 | True | 134 |
| AKSEN | -0.2392 | 0.7559 | 0.0743 | 1 | 0.0055 | 1 | True | 134 |
| ARCLK | -0.1999 | 1 | 0.0548 | 1 | -0.176 | 1 | False | 134 |
| ASELS | -0.1575 | 1 | 0.0329 | 1 | -0.0358 | 1 | False | 134 |
| BIMAS | -0.2314 | 0.8099 | 0.0922 | 1 | -0.1847 | 1 | True | 134 |
| CCOLA | -0.1011 | 1 | 0.0036 | 1 | 0.1308 | 1 | True | 134 |
| ECILC | -0.1339 | 1 | 0.0852 | 1 | -0.0691 | 1 | True | 134 |
| EKGYO | -0.3012 | 0.081 | 0.2204 | 1 | -0.0813 | 1 | True | 134 |
| ENJSA | -0.3526 | 0.009 | 0.0695 | 1 | -0.0749 | 1 | True | 134 |
| ENKAI | -0.0763 | 1 | 0.0009 | 1 | -0.1023 | 1 | False | 134 |
| EREGL | -0.163 | 1 | 0.0227 | 1 | -0.1569 | 1 | True | 134 |
| FROTO | -0.0196 | 1 | 0.0842 | 1 | -0.0146 | 1 | False | 134 |
| GUBRF | -0.2949 | 0.333 | -0.0764 | 1 | -0.0572 | 1 | True | 134 |
| ISMEN | -0.2005 | 1 | 0.0429 | 1 | -0.1185 | 1 | False | 134 |
| KCHOL | -0.2413 | 0.6029 | 0.1497 | 1 | -0.0134 | 1 | True | 134 |
| KRDMD | -0.2689 | 0.207 | -0.0159 | 1 | -0.1477 | 1 | True | 134 |
| MAVI | -0.0628 | 1 | 0.1041 | 1 | -0.0756 | 1 | True | 134 |
| MGROS | -0.1666 | 1 | 0.117 | 1 | -0.0135 | 1 | True | 134 |
| MPARK | -0.2124 | 1 | -0.0725 | 1 | -0.0153 | 1 | True | 134 |
| OYAKC | -0.0442 | 1 | 0.0162 | 1 | -0.1633 | 1 | True | 134 |
| PETKM | -0.1432 | 1 | 0.1045 | 1 | -0.0128 | 1 | True | 134 |
| PGSUS | -0.1208 | 1 | 0.0227 | 1 | 0.0036 | 1 | True | 134 |
| SASA | -0.1451 | 1 | 0.0135 | 1 | -0.0164 | 1 | False | 134 |
| TCELL | -0.3558 | 0.036 | 0.1076 | 1 | -0.0034 | 1 | True | 134 |
| THYAO | -0.235 | 0.7289 | 0.1775 | 1 | 0.0108 | 1 | True | 134 |
| TOASO | -0.1688 | 1 | 0.1121 | 1 | -0.1059 | 1 | True | 134 |
| TRALT | -0.2028 | 1 | 0.1354 | 1 | -0.0331 | 1 | True | 134 |
| TTKOM | -0.3268 | 0.072 | 0.0799 | 1 | 0.0445 | 1 | True | 134 |
| TUPRS | -0.1152 | 1 | 0.1407 | 1 | 0.0946 | 1 | True | 134 |
| TURSG | -0.055 | 1 | 0.0557 | 1 | -0.0433 | 1 | True | 134 |

## Sayımlar
* Düzeltme sonrası p < 0,05: USDTRY eş zamanlı **2/30**, USDTRY öncü **0/30**, fonlama maliyeti **0/30**.
* USDTRY eş zamanlı korelasyon işareti: pozitif **0**, negatif **30** hisse (aynı yönde bir 'ihracatçı hisseler kurla yükselir' kuralı yoktur).
* **EREGL (Soru 5)**: USDTRY eş zamanlı korelasyon -0.163 (düzeltilmiş p 1), öncü 0.0227 (düzeltilmiş p 1). 'Dolar yükselince EREGL kesin yükselir' iddiası doğrulanmaz.

## Yorum sınırı
Korelasyon nedensellik değildir. Kısa örneklem (≈134 blok; OOS ≈33), hisse getirisi enflasyon ve kur rejimine duyarlıdır. Politika faizi serisi veri setinde yoktur (L22, L43).
