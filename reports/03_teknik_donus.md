# Rapor 03 — Teknik dönüş olayları

> **Otomatik üretildi** (`python -m experiments.make_reports`, model yok): her sayı bir araç çıktısındandır; analiz tarihi **2026-09-10**, veri dönemi 2024-01-01 – 2026-09-10. Veri sürümleri: fiyat `snap_2026-11-20_v2`, bilanço `fundamentals_2026-11-23_v2`, makro `macro_2026-11-09_v2`.
> Eğitim/araştırma amaçlıdır; **yatırım tavsiyesi ve gelecek getiri garantisi değildir**. Senaryo: Senaryo 3 (§8, §13).

## Yöntem
Bollinger (20, 2) alt/üst bant teması ve RSI yerel dip/zirve olayları; ardışık gün serileri tek olaydır (ilk gün); olay `t`'de tespit edilir, ileri getiri `t` kapanışından sonra ölçülür; ufku `as_of`'u aşan olaylar dışlanır. OOS = 2026-01-01 ve sonrası. Beyan edilen toplam test sayısı **120** (30 hisse × 4 aile).

## Özet sayımlar
| Aile | Hisse | Toplam tamamlanmış olay | ≥ 20 olaylı hisse | …bunların taban isabetini aşanı | OOS bozulma bayraklı hisse |
|---|---|---|---|---|---|
| BB_LOWER_TOUCH | 30 | 452 | 3 | 3 | 5 |
| BB_UPPER_TOUCH | 30 | 776 | 27 | 11 | 3 |
| RSI_LOCAL_TROUGH | 30 | 2714 | 30 | 24 | 10 |
| RSI_LOCAL_PEAK | 30 | 2751 | 30 | 17 | 2 |

## ASELS: tekli ve birleşik koşullar (5 gün, alt Bollinger teması)
| Grup | Tespit edilen olay | Ham olay günü | Tamamlanmış olay | İsabet % | Ort. getiri % | Ufku dolmamış dışlanan |
|---|---|---|---|---|---|---|
| single_indicator | 12 | 17 | 12 | 66.6667 | 2.9608 | 0 |
| RSI dip + yüksek hacim | 0 | 0 | 0 | – | – | 0 |
| Supertrend düşüş + bulut altı | 5 | 7 | 5 | 80 | 5.9652 | 0 |

## BB_LOWER_TOUCH: 5 günlük ileri getiri
| Hisse | Tespit edilen olay | Tamamlanmış olay | İsabet % | Taban isabet % | Ort. getiri % | Maliyet sonrası % | Ufku dolmamış dışlanan | OOS bozulma |
|---|---|---|---|---|---|---|---|---|
| AKBNK | 14 | 14 | 50 | 55.0225 | 0.4754 | -0.0246 | 0 | False |
| AKSEN | 16 | 16 | 56.25 | 53.5232 | 0.8665 | 0.3665 | 0 | False |
| ARCLK | 18 | 18 | 38.8889 | 47.6762 | -0.7518 | -1.2518 | 0 | True |
| ASELS | 12 | 12 | 66.6667 | 59.2204 | 2.9608 | 2.4608 | 0 | False |
| BIMAS | 15 | 15 | 80 | 55.8383 | 3.5014 | 3.0014 | 0 | False |
| CCOLA | 17 | 17 | 58.8235 | 51.3473 | 1.6976 | 1.1976 | 0 | False |
| ECILC | 14 | 14 | 35.7143 | 50.2249 | 0.3498 | -0.1502 | 0 | True |
| EKGYO | 14 | 14 | 57.1429 | 56.8216 | 1.4637 | 0.9637 | 0 | True |
| ENJSA | 14 | 14 | 71.4286 | 58.9205 | 2.5889 | 2.0889 | 0 | False |
| ENKAI | 15 | 15 | 93.3333 | 55.3223 | 2.914 | 2.414 | 0 | False |
| EREGL | 10 | 10 | 50 | 55.6886 | 0.8914 | 0.3914 | 0 | False |
| FROTO | 16 | 16 | 62.5 | 48.6527 | 2.3495 | 1.8495 | 0 | False |
| GUBRF | 12 | 12 | 66.6667 | 55.4723 | 2.8715 | 2.3715 | 0 | False |
| ISMEN | 12 | 12 | 58.3333 | 48.7256 | 0.819 | 0.319 | 0 | False |
| KCHOL | 19 | 19 | 36.8421 | 52.6237 | 0.2551 | -0.2449 | 0 | False |
| KRDMD | 9 | 9 | 44.4444 | 53.2234 | 0.1163 | -0.3837 | 0 | False |
| MAVI | 20 | 20 | 50 | 48.9521 | 0.0161 | -0.4839 | 0 | False |
| MGROS | 14 | 14 | 64.2857 | 56.2219 | 1.1167 | 0.6167 | 0 | False |
| MPARK | 19 | 19 | 73.6842 | 57.5712 | 1.9407 | 1.4407 | 0 | False |
| OYAKC | 10 | 10 | 20 | 53.1437 | -2.8937 | -3.3937 | 0 | False |
| PETKM | 12 | 12 | 58.3333 | 52.6237 | -0.1072 | -0.6072 | 0 | False |
| PGSUS | 15 | 15 | 80 | 47.9042 | 2.7852 | 2.2852 | 0 | False |
| SASA | 21 | 21 | 61.9048 | 46.4072 | 0.7703 | 0.2703 | 0 | True |
| TCELL | 19 | 19 | 52.6316 | 52.024 | 0.9958 | 0.4958 | 0 | True |
| THYAO | 22 | 22 | 59.0909 | 51.8741 | 1.9359 | 1.4359 | 0 | False |
| TOASO | 14 | 14 | 50 | 56.8216 | 0.5562 | 0.0562 | 0 | False |
| TRALT | 13 | 13 | 69.2308 | 53.6732 | 4.5879 | 4.0879 | 0 | False |
| TTKOM | 16 | 16 | 62.5 | 53.3733 | 1.4271 | 0.9271 | 0 | False |
| TUPRS | 13 | 13 | 53.8462 | 52.9235 | 1.2587 | 0.7587 | 0 | False |
| TURSG | 17 | 17 | 58.8235 | 51.7964 | 1.3356 | 0.8356 | 0 | False |

## BB_UPPER_TOUCH: 5 günlük ileri getiri
| Hisse | Tespit edilen olay | Tamamlanmış olay | İsabet % | Taban isabet % | Ort. getiri % | Maliyet sonrası % | Ufku dolmamış dışlanan | OOS bozulma |
|---|---|---|---|---|---|---|---|---|
| AKBNK | 26 | 26 | 30.7692 | 44.8276 | -2.0386 | -2.5386 | 0 | True |
| AKSEN | 26 | 26 | 42.3077 | 45.8771 | -1.8926 | -2.3926 | 0 | False |
| ARCLK | 15 | 15 | 33.3333 | 51.4243 | -0.812 | -1.312 | 0 | False |
| ASELS | 31 | 31 | 25.8065 | 40.4798 | -3.2879 | -3.7879 | 0 | False |
| BIMAS | 28 | 28 | 57.1429 | 43.5629 | 0.1898 | -0.3102 | 0 | True |
| CCOLA | 17 | 17 | 35.2941 | 48.2036 | -0.5978 | -1.0978 | 0 | False |
| ECILC | 20 | 20 | 35 | 49.0255 | -2.5806 | -3.0806 | 0 | False |
| EKGYO | 33 | 32 | 56.25 | 42.7286 | -0.0318 | -0.5318 | 1 | False |
| ENJSA | 32 | 31 | 38.7097 | 40.3298 | -0.5959 | -1.0959 | 1 | False |
| ENKAI | 28 | 28 | 39.2857 | 44.2279 | -0.786 | -1.286 | 0 | False |
| EREGL | 41 | 40 | 42.5 | 43.2635 | 0.6544 | 0.1544 | 1 | True |
| FROTO | 23 | 22 | 50 | 51.1976 | -0.4943 | -0.9943 | 1 | False |
| GUBRF | 27 | 27 | 40.7407 | 44.078 | -2.2841 | -2.7841 | 0 | False |
| ISMEN | 26 | 25 | 44 | 50.6747 | -0.5043 | -1.0043 | 1 | False |
| KCHOL | 26 | 26 | 38.4615 | 46.7766 | -0.5947 | -1.0947 | 0 | False |
| KRDMD | 24 | 24 | 45.8333 | 45.8771 | -0.6012 | -1.1012 | 0 | False |
| MAVI | 21 | 21 | 52.381 | 50.2994 | 0.3626 | -0.1374 | 0 | False |
| MGROS | 34 | 34 | 38.2353 | 43.4783 | 0.0201 | -0.4799 | 0 | False |
| MPARK | 29 | 29 | 48.2759 | 41.8291 | 0.2431 | -0.2569 | 0 | False |
| OYAKC | 27 | 27 | 44.4444 | 46.5569 | -0.8415 | -1.3415 | 0 | False |
| PETKM | 28 | 27 | 40.7407 | 46.9265 | -0.4056 | -0.9056 | 1 | False |
| PGSUS | 22 | 21 | 52.381 | 51.497 | 0.2341 | -0.2659 | 1 | False |
| SASA | 14 | 13 | 38.4615 | 51.9461 | -2.9823 | -3.4823 | 1 | False |
| TCELL | 25 | 25 | 48 | 47.2264 | -0.2611 | -0.7611 | 0 | False |
| THYAO | 21 | 21 | 28.5714 | 46.9265 | -1.1381 | -1.6381 | 0 | False |
| TOASO | 26 | 25 | 56 | 43.0285 | 0.5467 | 0.0467 | 1 | False |
| TRALT | 28 | 28 | 71.4286 | 46.027 | 2.2449 | 1.7449 | 0 | False |
| TTKOM | 29 | 29 | 51.7241 | 46.027 | 0.0115 | -0.4885 | 0 | False |
| TUPRS | 32 | 32 | 53.125 | 46.6267 | -1.3163 | -1.8163 | 0 | False |
| TURSG | 26 | 26 | 50 | 47.1557 | -0.7318 | -1.2318 | 0 | False |

## RSI_LOCAL_TROUGH: 5 günlük ileri getiri
| Hisse | Tespit edilen olay | Tamamlanmış olay | İsabet % | Taban isabet % | Ort. getiri % | Maliyet sonrası % | Ufku dolmamış dışlanan | OOS bozulma |
|---|---|---|---|---|---|---|---|---|
| AKBNK | 83 | 83 | 57.8313 | 55.0225 | 0.8842 | 0.3842 | 0 | True |
| AKSEN | 92 | 92 | 51.087 | 53.5232 | 0.7855 | 0.2855 | 0 | True |
| ARCLK | 89 | 88 | 51.1364 | 47.6762 | 0.0589 | -0.4411 | 1 | False |
| ASELS | 95 | 94 | 59.5745 | 59.2204 | 1.9943 | 1.4943 | 1 | False |
| BIMAS | 99 | 99 | 60.6061 | 55.8383 | 1.13 | 0.63 | 0 | False |
| CCOLA | 93 | 93 | 60.2151 | 51.3473 | 1.4235 | 0.9235 | 0 | False |
| ECILC | 95 | 94 | 52.1277 | 50.2249 | 0.5635 | 0.0635 | 1 | True |
| EKGYO | 90 | 89 | 58.427 | 56.8216 | 1.596 | 1.096 | 1 | False |
| ENJSA | 79 | 79 | 56.962 | 58.9205 | 0.823 | 0.323 | 0 | False |
| ENKAI | 93 | 93 | 51.6129 | 55.3223 | 1.2015 | 0.7015 | 0 | False |
| EREGL | 93 | 92 | 48.913 | 55.6886 | 0.2023 | -0.2977 | 1 | False |
| FROTO | 91 | 90 | 54.4444 | 48.6527 | 0.4974 | -0.0026 | 1 | True |
| GUBRF | 93 | 93 | 62.3656 | 55.4723 | 1.7953 | 1.2953 | 0 | False |
| ISMEN | 91 | 90 | 42.2222 | 48.7256 | 0.07 | -0.43 | 1 | False |
| KCHOL | 96 | 96 | 61.4583 | 52.6237 | 0.9614 | 0.4614 | 0 | False |
| KRDMD | 93 | 92 | 55.4348 | 53.2234 | 1.1506 | 0.6506 | 1 | False |
| MAVI | 94 | 93 | 49.4624 | 48.9521 | 1.0955 | 0.5955 | 1 | False |
| MGROS | 83 | 82 | 67.0732 | 56.2219 | 1.2027 | 0.7027 | 1 | True |
| MPARK | 91 | 91 | 59.3407 | 57.5712 | 1.262 | 0.762 | 0 | False |
| OYAKC | 86 | 85 | 54.1176 | 53.1437 | 0.5658 | 0.0658 | 1 | True |
| PETKM | 77 | 77 | 57.1429 | 52.6237 | 1.1873 | 0.6873 | 0 | False |
| PGSUS | 93 | 93 | 50.5376 | 47.9042 | 0.4267 | -0.0733 | 0 | True |
| SASA | 91 | 90 | 50 | 46.4072 | 0.0641 | -0.4359 | 1 | False |
| TCELL | 93 | 93 | 53.7634 | 52.024 | 0.9107 | 0.4107 | 0 | True |
| THYAO | 96 | 95 | 53.6842 | 51.8741 | 0.3345 | -0.1655 | 1 | True |
| TOASO | 91 | 90 | 63.3333 | 56.8216 | 1.0833 | 0.5833 | 1 | False |
| TRALT | 89 | 89 | 58.427 | 53.6732 | 2.6306 | 2.1306 | 0 | False |
| TTKOM | 94 | 94 | 59.5745 | 53.3733 | 1.5592 | 1.0592 | 0 | True |
| TUPRS | 94 | 93 | 60.2151 | 52.9235 | 1.54 | 1.04 | 1 | False |
| TURSG | 92 | 92 | 51.087 | 51.7964 | 0.9515 | 0.4515 | 0 | False |

## RSI_LOCAL_PEAK: 5 günlük ileri getiri
| Hisse | Tespit edilen olay | Tamamlanmış olay | İsabet % | Taban isabet % | Ort. getiri % | Maliyet sonrası % | Ufku dolmamış dışlanan | OOS bozulma |
|---|---|---|---|---|---|---|---|---|
| AKBNK | 96 | 95 | 52.6316 | 44.8276 | -0.7417 | -1.2417 | 1 | False |
| AKSEN | 99 | 98 | 47.9592 | 45.8771 | -0.9674 | -1.4674 | 1 | False |
| ARCLK | 94 | 93 | 56.9892 | 51.4243 | 0.3278 | -0.1722 | 1 | False |
| ASELS | 91 | 89 | 33.7079 | 40.4798 | -2.2393 | -2.7393 | 2 | False |
| BIMAS | 92 | 92 | 45.6522 | 43.5629 | -0.5914 | -1.0914 | 0 | False |
| CCOLA | 79 | 78 | 55.1282 | 48.2036 | 0.2783 | -0.2217 | 1 | False |
| ECILC | 91 | 90 | 53.3333 | 49.0255 | -0.3658 | -0.8658 | 1 | False |
| EKGYO | 90 | 89 | 42.6966 | 42.7286 | -1.2146 | -1.7146 | 1 | False |
| ENJSA | 103 | 102 | 35.2941 | 40.3298 | -1.2837 | -1.7837 | 1 | False |
| ENKAI | 104 | 103 | 42.7184 | 44.2279 | -1.1535 | -1.6535 | 1 | False |
| EREGL | 92 | 91 | 38.4615 | 43.2635 | -1.1486 | -1.6486 | 1 | False |
| FROTO | 85 | 84 | 54.7619 | 51.1976 | 0.0205 | -0.4795 | 1 | False |
| GUBRF | 92 | 91 | 43.956 | 44.078 | -0.7219 | -1.2219 | 1 | False |
| ISMEN | 91 | 89 | 43.8202 | 50.6747 | -0.3711 | -0.8711 | 2 | False |
| KCHOL | 88 | 86 | 44.186 | 46.7766 | -0.6439 | -1.1439 | 2 | False |
| KRDMD | 87 | 86 | 45.3488 | 45.8771 | -0.7145 | -1.2145 | 1 | True |
| MAVI | 85 | 85 | 47.0588 | 50.2994 | 0.2349 | -0.2651 | 0 | False |
| MGROS | 100 | 99 | 46.4646 | 43.4783 | -0.6109 | -1.1109 | 1 | False |
| MPARK | 94 | 93 | 47.3118 | 41.8291 | -0.2055 | -0.7055 | 1 | False |
| OYAKC | 98 | 97 | 46.3918 | 46.5569 | -0.9276 | -1.4276 | 1 | False |
| PETKM | 100 | 99 | 51.5152 | 46.9265 | -0.0255 | -0.5255 | 1 | False |
| PGSUS | 85 | 84 | 55.9524 | 51.497 | 0.2393 | -0.2607 | 1 | False |
| SASA | 95 | 94 | 51.0638 | 51.9461 | -0.0023 | -0.5023 | 1 | False |
| TCELL | 98 | 97 | 54.6392 | 47.2264 | -0.0334 | -0.5334 | 1 | False |
| THYAO | 93 | 92 | 53.2609 | 46.9265 | 0.25 | -0.25 | 1 | False |
| TOASO | 94 | 93 | 47.3118 | 43.0285 | 0.2814 | -0.2186 | 1 | False |
| TRALT | 93 | 92 | 53.2609 | 46.027 | 0.1916 | -0.3084 | 1 | False |
| TTKOM | 99 | 98 | 52.0408 | 46.027 | -0.0915 | -0.5915 | 1 | False |
| TUPRS | 85 | 85 | 47.0588 | 46.6267 | -1.0989 | -1.5989 | 0 | True |
| TURSG | 88 | 87 | 47.1264 | 47.1557 | -0.7694 | -1.2694 | 1 | False |

## Yorum sınırı
Olay sayısı `MIN_EVENTS` altında ise (az olay) sonuç zayıf kanıttır; birleşik koşullar olay sayısını daha da küçültür. Bir bandın 'işe yaradığı' iddiası, taban oranla ve OOS ile karşılaştırılmadan yapılamaz (L24, L27).
