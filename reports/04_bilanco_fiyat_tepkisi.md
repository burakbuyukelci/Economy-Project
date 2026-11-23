# Rapor 04 — Çeyreklik bilanço değişimi ve açıklama sonrası fiyat tepkisi

> **Otomatik üretildi** (`python -m experiments.make_reports`, model yok): her sayı bir araç çıktısındandır; analiz tarihi **2026-09-10**, veri dönemi 2024-01-01 – 2026-09-10. Veri sürümleri: fiyat `snap_2026-11-20_v2`, bilanço `fundamentals_2026-11-23_v2`, makro `macro_2026-11-09_v2`.
> Eğitim/araştırma amaçlıdır; **yatırım tavsiyesi ve gelecek getiri garantisi değildir**. Senaryo: Senaryo 4 (§14).

## Yöntem
Bilanço satırları **KAP açıklama tarihine** (bilinmiyorsa dönem sonu + yasal süre) göre hizalanır, dönem sonuna göre değil; yalnızca TMS 29 sonrası dönemler (2025+). Tepki: açıklamadan önceki son kapanıştan 1/5/20 işlem günü sonrası getiri, XU100'e göre anormal getiri; pencere `as_of`'u aşarsa dışlanır. Banka için sanayi oranları kullanılmaz (net kâr). Karşılaştırma bir önceki çeyreğe göre (QoQ), mevsim arındırılmamıştır.

## 1. Son açıklanmış çeyrek
| Hisse | Açıklanmış çeyrek | Son çeyrek | Açıklama tarihi | İyileşme metriği değeri | QoQ değişim | Yön |
|---|---|---|---|---|---|---|
| AKBNK | 5 | 2026Q2 | 2026-07-28 | 15198 | -20.6442 | DETERIORATED |
| AKSEN | 4 | 2026Q2 | 2026-09-03 | 34.9997 | 6.2146 | IMPROVED |
| ARCLK | 5 | 2026Q2 | 2026-09-03 | 8.3492 | -2.5769 | DETERIORATED |
| ASELS | 5 | 2026Q2 | 2026-09-03 | 1.7872 | -14.9574 | DETERIORATED |
| BIMAS | 4 | 2026Q2 | 2026-08-17 | 10.1878 | -0.0349 | FLAT |
| CCOLA | 4 | 2026Q2 | 2026-09-03 | 25.0925 | 0.5086 | IMPROVED |
| ECILC | 4 | 2026Q2 | 2026-09-03 | -9.0897 | 5.9224 | IMPROVED |
| EKGYO | 5 | 2026Q2 | 2026-08-19 | 31.1376 | -22.1727 | DETERIORATED |
| ENJSA | 6 | 2026Q2 | 2026-09-03 | 26.4254 | 3.9502 | IMPROVED |
| ENKAI | 4 | 2026Q2 | 2026-08-17 | 36.1702 | 20.4033 | IMPROVED |
| EREGL | 5 | 2026Q2 | 2026-08-03 | 15.9896 | 7.666 | IMPROVED |
| FROTO | 5 | 2026Q2 | 2026-09-03 | 4.3827 | -3.7713 | DETERIORATED |
| GUBRF | 4 | 2026Q2 | 2026-09-03 | 33.6729 | 12.643 | IMPROVED |
| ISMEN | 4 | 2026Q2 | 2026-09-03 | 0.769 | 0.0679 | FLAT |
| KCHOL | 4 | 2026Q2 | 2026-09-03 | 11.1324 | 3.1961 | IMPROVED |
| KRDMD | 4 | 2026Q2 | 2026-09-03 | 13.2935 | -3.7152 | DETERIORATED |
| MAVI | 4 | 2026Q2 | 2026-07-04 | 21.5126 | 5.0472 | IMPROVED |
| MGROS | 4 | 2026Q2 | 2026-09-03 | 11.0816 | -2.5217 | DETERIORATED |
| MPARK | 5 | 2026Q2 | 2026-09-03 | 35.1399 | 0.2676 | FLAT |
| OYAKC | 4 | 2026Q2 | 2026-09-03 | 28.3087 | 5.1277 | IMPROVED |
| PETKM | 4 | 2026Q2 | 2026-09-03 | 18.2231 | 2.1974 | IMPROVED |
| PGSUS | 4 | 2026Q2 | 2026-09-03 | 8.3702 | 8.4296 | IMPROVED |
| SASA | 5 | 2026Q2 | 2026-09-03 | -9.0108 | -52.248 | DETERIORATED |
| TCELL | 4 | 2026Q2 | 2026-08-13 | 45.2102 | -2.7195 | DETERIORATED |
| THYAO | 4 | 2026Q2 | 2026-09-03 | 14.6426 | -0.9903 | DETERIORATED |
| TOASO | 4 | 2026Q2 | 2026-09-03 | 4.8819 | 0.1157 | FLAT |
| TRALT | 5 | 2026Q2 | 2026-09-03 | 28.418 | -9.4049 | DETERIORATED |
| TTKOM | 5 | 2026Q2 | 2026-09-03 | 65.8084 | -4.3096 | DETERIORATED |
| TUPRS | 4 | 2026Q2 | 2026-08-04 | 14.8685 | 7.6149 | IMPROVED |
| TURSG | 5 | 2026Q2 | 2026-09-03 | – | – | – |

## 2. Açıklama sonrası ortalama anormal getiri (tüm çeyrekler, XU100'e göre)
| Hisse | Ufuk (gün) | Gözlem (çeyrek) | Ort. anormal getiri % | İsabet % | Ufku dolmamış dışlanan |
|---|---|---|---|---|---|
| AKBNK | 1 | 5 | -0.3932 | 20 | 0 |
| AKBNK | 5 | 5 | -3.5749 | 40 | 0 |
| AKBNK | 20 | 5 | -2.5877 | 40 | 0 |
| BIMAS | 1 | 3 | 2.6364 | 66.6667 | 0 |
| BIMAS | 5 | 3 | 5.0209 | 100 | 0 |
| BIMAS | 20 | 2 | 0.1888 | 50 | 1 |
| CCOLA | 1 | 1 | 0.373 | 100 | 0 |
| CCOLA | 5 | 1 | 6.6323 | 100 | 0 |
| CCOLA | 20 | 1 | 0.0626 | 100 | 0 |
| EKGYO | 1 | 1 | 1.4539 | 100 | 0 |
| EKGYO | 5 | 1 | 4.721 | 100 | 0 |
| ENKAI | 1 | 1 | -8.2731 | 0 | 0 |
| ENKAI | 5 | 1 | -7.4367 | 0 | 0 |
| EREGL | 1 | 5 | 0.1719 | 80 | 0 |
| EREGL | 5 | 5 | 1.7191 | 60 | 0 |
| EREGL | 20 | 5 | 0.6391 | 60 | 0 |
| TCELL | 1 | 1 | -1.1172 | 0 | 0 |
| TCELL | 5 | 1 | -2.5688 | 0 | 0 |
| TCELL | 20 | 1 | -5.0117 | 0 | 0 |
| TUPRS | 1 | 4 | -1.6111 | 0 | 0 |
| TUPRS | 5 | 4 | -0.1371 | 25 | 0 |
| TUPRS | 20 | 4 | 8.5686 | 50 | 0 |

## Yorum sınırı
Gözlem sayısı çeyrek sayısıdır (en çok 4–6): istatistik zayıftır ve IS/OOS ayrımı yapılamaz. "İyi bilanço = fiyat artar" nedensellik iddiası YAPILMAZ. Yahoo kaynaklı değerler KAP'a karşı doğrulanmamıştır; yalnızca TUPRS açıklama tarihleri haber/KAP'tan doğrulandı (L10–L17).
