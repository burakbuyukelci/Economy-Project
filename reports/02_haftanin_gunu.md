# Rapor 02 — Haftanın günü ve çok günlü örüntüler

> **Otomatik üretildi** (`python -m experiments.make_reports`, model yok): her sayı bir araç çıktısındandır; analiz tarihi **2026-09-10**, veri dönemi 2024-01-01 – 2026-09-10. Veri sürümleri: fiyat `snap_2026-11-20_v2`, bilanço `fundamentals_2026-11-23_v2`, makro `macro_2026-11-09_v2`.
> Eğitim/araştırma amaçlıdır; **yatırım tavsiyesi ve gelecek getiri garantisi değildir**. Senaryo: Senaryo 2 (§12).

## Yöntem
Permütasyon testi (B=10 000, sabit tohum 481), tek yönlü; örneklem içi (IS) 2024-01-01 – 2025-12-31, örneklem dışı (OOS) 2026-01-01 – 2026-09-10. Tatil haftaları dışlanır; son tamamlanmamış hafta `as_of` sonrasına taşarsa dışlanır. İşlem maliyeti tetik haftası başına bir kez düşülür. Örüntüler **keşif amaçlı seçilmedi**, dokümandaki örneklerdir.

## P1 Pzt–Sal–Çar düşüş → Per–Cum yükseliş
| Hisse | IS tetik hafta | IS gerçekleşme | IS ort. sonuç getirisi % | IS ham p | IS düzeltilmiş p (×60) | OOS tetik hafta | OOS gerçekleşme | OOS ort. sonuç getirisi % | Karar |
|---|---|---|---|---|---|---|---|---|---|
| AKBNK | 5 | 0 | 0.4496 | 0.4686 | 1 | 3 | 0 | -2.5174 | INSUFFICIENT_DATA |
| AKSEN | 11 | 4 | 1.2909 | 0.422 | 1 | 3 | 0 | 0.2903 | UNSTABLE |
| ARCLK | 12 | 2 | -0.9708 | 0.9586 | 1 | 5 | 2 | 2.0868 | UNSTABLE |
| ASELS | 4 | 3 | 2.0502 | 0.2602 | 1 | 4 | 1 | 0.5061 | INSUFFICIENT_DATA |
| BIMAS | 4 | 3 | 0.8966 | 0.289 | 1 | 2 | 1 | 0.4033 | INSUFFICIENT_DATA |
| CCOLA | 16 | 3 | -0.4146 | 0.9805 | 1 | 0 | 0 | – | UNSTABLE |
| ECILC | 15 | 9 | 3.1902 | 0.0586 | 1 | 4 | 0 | 0.4966 | UNSTABLE |
| EKGYO | 9 | 2 | -0.393 | 0.8196 | 1 | 2 | 0 | -4.0541 | INSUFFICIENT_DATA |
| ENJSA | 10 | 3 | 1.6161 | 0.2617 | 1 | 3 | 1 | 0.6245 | UNSTABLE |
| ENKAI | 11 | 7 | 2.783 | 0.0179 | 1 | 3 | 2 | 0.855 | UNSTABLE |
| EREGL | 11 | 3 | 0.832 | 0.3152 | 1 | 3 | 0 | -1.3972 | UNSTABLE |
| FROTO | 14 | 2 | 0.9977 | 0.2736 | 1 | 5 | 1 | 0.5019 | UNSTABLE |
| GUBRF | 12 | 3 | -1.4675 | 0.9892 | 1 | 0 | 0 | – | UNSTABLE |
| ISMEN | 6 | 1 | 1.035 | 0.3263 | 1 | 4 | 2 | 0.3722 | INSUFFICIENT_DATA |
| KCHOL | 8 | 1 | 0.0928 | 0.6605 | 1 | 2 | 0 | 0.8056 | INSUFFICIENT_DATA |
| KRDMD | 17 | 6 | 1.9598 | 0.1668 | 1 | 1 | 0 | -2.1223 | UNSTABLE |
| MAVI | 13 | 3 | 1.3858 | 0.2497 | 1 | 3 | 0 | -1.3931 | UNSTABLE |
| MGROS | 9 | 2 | 0.4633 | 0.4889 | 1 | 3 | 1 | -0.7837 | INSUFFICIENT_DATA |
| MPARK | 8 | 2 | 0.3263 | 0.7476 | 1 | 4 | 1 | 0.1945 | INSUFFICIENT_DATA |
| OYAKC | 12 | 3 | 1.37 | 0.4177 | 1 | 0 | 0 | – | UNSTABLE |
| PETKM | 12 | 5 | 1.3177 | 0.2703 | 1 | 1 | 0 | -0.3684 | UNSTABLE |
| PGSUS | 13 | 3 | 0.4359 | 0.6892 | 1 | 5 | 1 | 0.3982 | UNSTABLE |
| SASA | 15 | 2 | -0.5349 | 0.9363 | 1 | 2 | 1 | 4.6683 | UNSTABLE |
| TCELL | 8 | 2 | 0.3358 | 0.4846 | 1 | 3 | 1 | -1.3767 | INSUFFICIENT_DATA |
| THYAO | 18 | 5 | 1.3017 | 0.1205 | 1 | 3 | 0 | 0.1303 | UNSTABLE |
| TOASO | 12 | 4 | 0.772 | 0.5037 | 1 | 6 | 0 | 0.1267 | UNSTABLE |
| TRALT | 8 | 4 | 3.4702 | 0.1585 | 1 | 3 | 0 | -1.517 | INSUFFICIENT_DATA |
| TTKOM | 9 | 4 | 1.1125 | 0.3157 | 1 | 3 | 0 | -1.5435 | INSUFFICIENT_DATA |
| TUPRS | 18 | 4 | 0.7758 | 0.5082 | 1 | 1 | 0 | 1.107 | UNSTABLE |
| TURSG | 10 | 7 | 4.1719 | 0.0082 | 0.4919 | 1 | 1 | 0.64 | UNSTABLE |

## P2 Pzt düşüş → Cum yükseliş
| Hisse | IS tetik hafta | IS gerçekleşme | IS ort. sonuç getirisi % | IS ham p | IS düzeltilmiş p (×60) | OOS tetik hafta | OOS gerçekleşme | OOS ort. sonuç getirisi % | Karar |
|---|---|---|---|---|---|---|---|---|---|
| AKBNK | 39 | 15 | -0.0958 | 0.4846 | 1 | 15 | 7 | -0.4813 | UNSTABLE |
| AKSEN | 46 | 29 | 0.3567 | 0.3674 | 1 | 16 | 8 | 0.0187 | UNSTABLE |
| ARCLK | 54 | 20 | -0.7074 | 0.9936 | 1 | 14 | 9 | 0.7488 | UNSTABLE |
| ASELS | 38 | 19 | 0.3235 | 0.3635 | 1 | 13 | 8 | 0.9533 | UNSTABLE |
| BIMAS | 37 | 17 | -0.3279 | 0.4885 | 1 | 10 | 6 | 0.6343 | UNSTABLE |
| CCOLA | 48 | 27 | 0.3331 | 0.4295 | 1 | 14 | 10 | 0.8669 | UNSTABLE |
| ECILC | 53 | 38 | 1.0259 | 0.158 | 1 | 14 | 6 | 0.5585 | UNSTABLE |
| EKGYO | 49 | 30 | 0.7903 | 0.0894 | 1 | 10 | 3 | -0.1949 | UNSTABLE |
| ENJSA | 47 | 25 | 0.4833 | 0.5596 | 1 | 10 | 6 | 0.7841 | UNSTABLE |
| ENKAI | 51 | 27 | 0.3044 | 0.596 | 1 | 18 | 13 | 1.0674 | UNSTABLE |
| EREGL | 49 | 26 | 0.182 | 0.4284 | 1 | 11 | 6 | 0.5076 | UNSTABLE |
| FROTO | 49 | 20 | -0.0641 | 0.5938 | 1 | 18 | 8 | 0.3982 | UNSTABLE |
| GUBRF | 47 | 18 | -0.1993 | 0.9056 | 1 | 10 | 4 | -0.1583 | UNSTABLE |
| ISMEN | 43 | 20 | 0.5816 | 0.0308 | 1 | 17 | 10 | 0.3757 | UNSTABLE |
| KCHOL | 48 | 16 | -0.5431 | 0.9471 | 1 | 12 | 7 | 0.6844 | UNSTABLE |
| KRDMD | 51 | 25 | 0.2109 | 0.6626 | 1 | 5 | 2 | 0.2052 | UNSTABLE |
| MAVI | 49 | 27 | 0.1505 | 0.4781 | 1 | 16 | 9 | 0.1441 | UNSTABLE |
| MGROS | 45 | 21 | 0.0091 | 0.6676 | 1 | 11 | 7 | 0.7944 | UNSTABLE |
| MPARK | 45 | 25 | 0.4125 | 0.5728 | 1 | 14 | 9 | 1.082 | UNSTABLE |
| OYAKC | 40 | 20 | 0.2684 | 0.3494 | 1 | 11 | 5 | -0.1261 | UNSTABLE |
| PETKM | 44 | 29 | 0.4422 | 0.2665 | 1 | 9 | 5 | 0.6593 | UNSTABLE |
| PGSUS | 45 | 22 | 0.1572 | 0.7416 | 1 | 17 | 7 | 0.1195 | UNSTABLE |
| SASA | 45 | 15 | -0.092 | 0.8174 | 1 | 12 | 7 | 1.1571 | UNSTABLE |
| TCELL | 48 | 21 | -0.238 | 0.5871 | 1 | 13 | 8 | 0.0043 | UNSTABLE |
| THYAO | 49 | 25 | 0.1765 | 0.7578 | 1 | 15 | 7 | 0.2337 | UNSTABLE |
| TOASO | 46 | 22 | -0.289 | 0.7787 | 1 | 18 | 11 | 1.389 | UNSTABLE |
| TRALT | 43 | 28 | 0.726 | 0.1483 | 1 | 10 | 4 | 0.7928 | UNSTABLE |
| TTKOM | 52 | 30 | 0.3484 | 0.0589 | 1 | 11 | 7 | 0.7187 | UNSTABLE |
| TUPRS | 52 | 28 | 0.1511 | 0.294 | 1 | 11 | 6 | 0.573 | UNSTABLE |
| TURSG | 53 | 33 | 0.3804 | 0.6971 | 1 | 16 | 9 | 0.7765 | UNSTABLE |

## Sayımlar (tesadüf beklentisiyle birlikte)
| Örüntü | Test edilen hisse | IS ham p < 0,05 | Bonferroni sonrası p < 0,05 | STABLE (IS+OOS) |
|---|---|---|---|---|
| P1 Pzt–Sal–Çar düşüş → Per–Cum yükseliş | 30 | 2 | 0 | 0 |
| P2 Pzt düşüş → Cum yükseliş | 30 | 1 | 0 | 0 |

Sadece tesadüfle, 30 bağımsız testte ham p < 0,05 için beklenen sayı ≈ 1.5 hisse/örüntüdür. Bu raporda araca beyan edilen toplam test sayısı **60** (30 hisse × 2 örüntü); düzeltilmiş p bununla hesaplanır. Aranan örüntü sayısı arttıkça tesadüfi 'keşif' riski artar (§12).

## Yorum sınırı
Kararlılık = IS'te anlamlı ve OOS'ta aynı yönde. IS'te anlamlı çıkan bir örüntü OOS'ta yoksa tesadüf adayıdır. Hiçbir örüntü tek başına işlem kuralı değildir (L24–L25, L30).
