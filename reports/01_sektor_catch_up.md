# Rapor 01 — Sektör geride kalanı / catch-up

> **Otomatik üretildi** (`python -m experiments.make_reports`, model yok): her sayı bir araç çıktısındandır; analiz tarihi **2026-09-10**, veri dönemi 2024-01-01 – 2026-09-10. Veri sürümleri: fiyat `snap_2026-11-20_v2`, bilanço `fundamentals_2026-11-23_v2`, makro `macro_2026-11-09_v2`.
> Eğitim/araştırma amaçlıdır; **yatırım tavsiyesi ve gelecek getiri garantisi değildir**. Senaryo: Senaryo 1 (§11).

## Yöntem
Peer grupları `config/universe.csv`'den (en az 2 üyeli 9 grup). Geride kalma: hisse getirisi − grup medyanı (20 işlem günü). Tarihsel catch-up: geride kalma olayları cooldown ile bağımsızlaştırılır, ufku `as_of`'u aşan olaylar dışlanır; OOS = 2026-01-01 ve sonrası. Backtest: sinyal kaydırmalı, tur maliyeti 0,5 pp, 5 gün tutma; varyant A (yalnızca sinyal), B (+ sektör gücü filtresi).

## 1. Güncel durum (20 işlem günü)
| Grup | Üyeler | Sektör gücü | Sektör medyanı − XU100 (pp) | En çok geride | Gecikme skoru (pp) | Eşikte mi |
|---|---|---|---|---|---|---|
| airlines | PGSUS, THYAO | WEAK | -2.9109 | THYAO | -1.7818 | False |
| automotive | FROTO, TOASO | STRONG | 3.4209 | FROTO | -2.5123 | False |
| chemicals | GUBRF, SASA | STRONG | 14.9536 | SASA | -3.7442 | True |
| electric_utilities | AKSEN, ENJSA | NEUTRAL | 0.3203 | AKSEN | -6.7664 | True |
| energy_petrochem | PETKM, TUPRS | STRONG | 24.773 | TUPRS | -6.1768 | True |
| healthcare | ECILC, MPARK | WEAK | -3.7862 | ECILC | -4.9577 | True |
| retail | BIMAS, MAVI, MGROS | WEAK | -3.6634 | MAVI | -3.2452 | True |
| steel | EREGL, KRDMD | STRONG | 4.791 | EREGL | -4.7077 | True |
| telecom | TCELL, TTKOM | WEAK | -2.2153 | TCELL | -1.0914 | False |

## 2. Tarihsel catch-up (havuzlu, tüm üyeler)
| Grup | Ufuk (gün) | Tamamlanmış olay | Yanlış pozitif | İsabet % | Taban isabet % | Ort. getiri % | Maliyet sonrası % | OOS olay | OOS isabet % | OOS bozulma | Ufku dolmamış dışlanan |
|---|---|---|---|---|---|---|---|---|---|---|---|
| airlines | 5 | 25 | 16 | 36 | 50 | -0.5372 | -1.0372 | 5 | 40 | False | 0 |
| airlines | 10 | 25 | 14 | 44 | 50 | -0.9901 | -1.4901 | 5 | 20 | True | 0 |
| airlines | 20 | 25 | 16 | 36 | 50 | -1.7528 | -2.2528 | 5 | 20 | True | 0 |
| automotive | 5 | 34 | 18 | 47.0588 | 50 | 0.001 | -0.499 | 9 | 55.5556 | False | 1 |
| automotive | 10 | 34 | 16 | 52.9412 | 50 | -0.4808 | -0.9808 | 9 | 66.6667 | False | 1 |
| automotive | 20 | 33 | 19 | 42.4242 | 49.9231 | -2.156 | -2.656 | 8 | 37.5 | False | 2 |
| chemicals | 5 | 37 | 22 | 40.5405 | 50 | -0.6766 | -1.1766 | 10 | 30 | False | 1 |
| chemicals | 10 | 37 | 24 | 35.1351 | 50 | -1.2233 | -1.7233 | 10 | 40 | False | 1 |
| chemicals | 20 | 37 | 22 | 40.5405 | 50 | -3.5565 | -4.0565 | 10 | 50 | False | 1 |
| electric_utilities | 5 | 34 | 17 | 50 | 50 | 0.4308 | -0.0692 | 8 | 75 | False | 1 |
| electric_utilities | 10 | 34 | 15 | 55.8824 | 50 | 0.9563 | 0.4563 | 8 | 50 | False | 1 |
| electric_utilities | 20 | 34 | 16 | 52.9412 | 50 | 0.6772 | 0.1772 | 8 | 62.5 | True | 1 |
| energy_petrochem | 5 | 35 | 17 | 51.4286 | 50 | 0.3452 | -0.1548 | 9 | 44.4444 | True | 1 |
| energy_petrochem | 10 | 34 | 18 | 47.0588 | 50 | 0.2943 | -0.2057 | 8 | 37.5 | True | 2 |
| energy_petrochem | 20 | 34 | 14 | 58.8235 | 50 | 1.2103 | 0.7103 | 8 | 50 | True | 2 |
| healthcare | 5 | 38 | 15 | 60.5263 | 50 | 0.6939 | 0.1939 | 10 | 50 | True | 1 |
| healthcare | 10 | 38 | 15 | 60.5263 | 50 | 0.5913 | 0.0913 | 10 | 70 | True | 1 |
| healthcare | 20 | 37 | 18 | 51.3514 | 50 | -0.5566 | -1.0566 | 9 | 44.4444 | False | 2 |
| retail | 5 | 43 | 23 | 46.5116 | 49.6742 | -0.1828 | -0.6828 | 10 | 40 | False | 1 |
| retail | 10 | 43 | 22 | 48.8372 | 50.5556 | -0.3852 | -0.8852 | 10 | 40 | False | 1 |
| retail | 20 | 43 | 22 | 48.8372 | 48.7179 | 1.1596 | 0.6596 | 10 | 40 | True | 1 |
| steel | 5 | 32 | 16 | 50 | 49.9248 | 0.1097 | -0.3903 | 9 | 55.5556 | False | 0 |
| steel | 10 | 31 | 16 | 48.3871 | 49.9242 | -0.4538 | -0.9538 | 8 | 62.5 | False | 1 |
| steel | 20 | 31 | 18 | 41.9355 | 50 | -0.3257 | -0.8257 | 8 | 37.5 | False | 1 |
| telecom | 5 | 25 | 13 | 48 | 50 | -0.0482 | -0.5482 | 5 | 60 | False | 0 |
| telecom | 10 | 25 | 8 | 68 | 50 | 1.1351 | 0.6351 | 5 | 60 | False | 0 |
| telecom | 20 | 25 | 12 | 52 | 50 | 0.412 | -0.088 | 5 | 80 | False | 0 |

## 3. Backtest (A/B) ve benchmark farkları
| Grup | Varyant | Sinyal | Net kümülatif % | Sharpe | Maks. düşüş % | Kazanma % | Fark: Al-Tut (pp) | Fark: XU100 (pp) | OOS bozulma | Az sinyal |
|---|---|---|---|---|---|---|---|---|---|---|
| airlines | A | 63 | -50.4669 | -1.0328 | -62.0097 | 39.6825 | -76.9604 | -143.1522 | False | False |
| airlines | B | 44 | -42.7961 | -0.9317 | -53.1564 | 43.1818 | -69.2896 | -135.4814 | False | False |
| automotive | A | 85 | -62.1986 | -1.0888 | -66.2901 | 39.2857 | -118.1434 | -154.8839 | False | False |
| automotive | B | 61 | -38.6739 | -0.601 | -46.2704 | 45 | -94.6187 | -131.3592 | False | False |
| chemicals | A | 106 | -62.4973 | -0.7677 | -74.2158 | 39.0476 | -117.4956 | -155.1826 | False | False |
| chemicals | B | 70 | -41.2534 | -0.4585 | -56.3505 | 42.029 | -96.2517 | -133.9387 | False | False |
| electric_utilities | A | 91 | 9.4433 | 0.2614 | -34.2632 | 54.4444 | -192.2024 | -82.1131 | True | False |
| electric_utilities | B | 73 | 63.6777 | 0.8432 | -26.5229 | 59.7222 | -137.968 | -27.8787 | False | False |
| energy_petrochem | A | 89 | 7.631 | 0.2402 | -51.8539 | 52.8736 | -132.8678 | -83.9254 | False | False |
| energy_petrochem | B | 66 | -13.0178 | -0.0821 | -40.4052 | 53.125 | -153.5166 | -104.5742 | False | False |
| healthcare | A | 91 | 12.8501 | 0.3041 | -32.047 | 55.5556 | -140.6273 | -78.7063 | False | False |
| healthcare | B | 67 | 136.0456 | 1.2894 | -20.8226 | 61.194 | -17.4318 | 44.4892 | False | False |
| retail | A | 100 | 46.1477 | 0.6385 | -25.1391 | 51.0204 | -58.0919 | -46.5376 | True | False |
| retail | B | 75 | 9.3125 | 0.2574 | -33.9517 | 49.3333 | -94.9271 | -83.3728 | True | False |
| steel | A | 77 | -35.4037 | -0.4426 | -58.6113 | 51.3158 | -137.89 | -128.089 | False | False |
| steel | B | 56 | -26.9016 | -0.3238 | -49.5727 | 52.7273 | -129.3879 | -119.5869 | False | False |
| telecom | A | 57 | 15.63 | 0.3528 | -29.4547 | 50.8772 | -100.6652 | -75.9264 | True | False |
| telecom | B | 45 | -14.279 | -0.153 | -44.4162 | 51.1111 | -130.5742 | -105.8354 | False | False |

## Sayımlar
* 9 grup, 27 grup×ufuk bloğu; toplam yanlış pozitif olay: **462** (geride kalıp toparlanmayan olaylar raporlanır).
* Taban isabeti aşan blok sayısı: **12/27**; OOS bozulma bayrağı olan blok sayısı: **9/27**.
* `MIN_EVENTS` = 20: bunun altındaki bloklar zayıf kanıttır. Çoklu test: grup × ufuk × varyant denemesi tek düzeltmeyle kapsanmaz (limitations L24–L25).

## Yorum sınırı
Sonuçlar ilişki gözlemidir; "geride kalan toparlanır" nedensellik iddiası değildir. Sektör gücü ve gecikme eşikleri varsayımdır. 11 hisse tek başına olduğundan sektör karşılaştırması yoktur (L19).
