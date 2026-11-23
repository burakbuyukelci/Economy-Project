# Rapor 06 — Backtest ve benchmark karşılaştırması (30 hisse, eşit ağırlıklı)

> **Otomatik üretildi** (`python -m experiments.make_reports`, model yok): her sayı bir araç çıktısındandır; analiz tarihi **2026-09-10**, veri dönemi 2024-01-01 – 2026-09-10. Veri sürümleri: fiyat `snap_2026-11-20_v2`, bilanço `fundamentals_2026-11-23_v2`, makro `macro_2026-11-09_v2`.
> Eğitim/araştırma amaçlıdır; **yatırım tavsiyesi ve gelecek getiri garantisi değildir**. Senaryo: Doğrulama katmanı (§18).

## Yöntem
Sinyal `t` kapanışında oluşur, giriş `t+1` (sinyal kaydırma); 5 gün tutma; tur maliyeti 0,5 pp (20 + 5 bps × 2); çakışmasız işlem; eşit ağırlıklı portföy. Benchmark: Al-Tut (aynı evren) ve XU100. Eğitim ≤ 2025-12-31, test sonrası.

## Sonuçlar
| Sinyal | Varyant | Sinyal sayısı | Net kümülatif % | Sharpe | Maks. düşüş % | Kazanma % | Fark: Al-Tut (pp) | Fark: XU100 (pp) | Test dilimi sinyal | OOS bozulma | Az sinyal |
|---|---|---|---|---|---|---|---|---|---|---|---|
| REVERSAL BB_LOWER_TOUCH | A | 361 | 9.412 | 0.26 | -38.4582 | 53.4626 | -119.5265 | -83.2733 | 91 | False | False |
| REVERSAL BB_LOWER_TOUCH | B | 234 | -15.2827 | -0.1181 | -40.3624 | 52.5641 | -144.2212 | -107.968 | 56 | False | False |
| REVERSAL RSI_LOCAL_TROUGH | A | 1851 | 21.9195 | 0.4221 | -37.3693 | 50.7885 | -107.019 | -70.7658 | 479 | False | False |
| REVERSAL RSI_LOCAL_TROUGH | B | 1411 | 29.8526 | 0.5083 | -35.8742 | 51.4632 | -99.0859 | -62.8327 | 341 | False | False |

## Yorum sınırı
Backtest geleceği garanti etmez; getiri/Sharpe ile tahmin doğruluğu farklı kavramlardır. Yalnızca uzun yön; kayma maliyeti varsayımdır (L28). Birden çok sinyal/varyant denendiği için seçim yanlılığı riski vardır (`MULTIPLE_TESTING_RISK`).
