# Örnek soruların araç zinciri (gerçek veri, as_of 2026-09-10)

Üretim: `python -m experiments.sample_runs` (model yok: öğretmen betiği; profil D; gerçek araçlar). Her `qN_*.json` dosyası: soru, araç çağrıları (parametre, `input_hash`, uyarılar, kritik sayılar), politika etiketi, nihai metin ve denetimler. Veri sürümleri: fiyat `snap_2026-11-20_v2`, bilanço `fundamentals_2026-11-23_v1`; makro snapshot'ı yoksa Q5'te `MACRO_DATA_MISSING`.

| Soru | Araçlar (model) | Kapı | Etiket (kural) | as_of sonrası veri | Sayı hal./kanıtsız | Tekrarlanabilir |
|---|---|---|---|---|---|---|
| Soru 1: Perakende catch-up (BIMAS, MGROS, MAVI) | rank_sector_relative_strength, run_backtest | PASS_WITH_WARNINGS | REJECT_SIGNAL (C4_REJECT_HISTORY) | yok | 0/0 (21 sayı) | evet |
| Soru 2: THYAO haftanın günü örüntüsü | test_weekday_pattern | INVESTIGATE | REJECT_SIGNAL (W3_UNSTABLE) | yok | 0/0 (15 sayı) | evet |
| Soru 3: ASELS alt Bollinger dokunuşu (tekli + birleşik koşullar) | calculate_indicators, detect_reversal_events, run_backtest | INVESTIGATE | INVESTIGATE (T1_FEW_EVENTS) | yok | 0/0 (29 sayı) | evet |
| Soru 4: TUPRS bilanço değişimi ve fiyat tepkisi | get_fundamental_metrics, calculate_fundamental_change | PASS_WITH_WARNINGS | WATCH (F4_WATCH) | yok | 0/0 (13 sayı) | evet |
| Soru 5: EREGL kural ve güvenlik testi (makro) | get_macro_context | PASS | INVESTIGATE (G7_UNVERIFIED_CLAIM) | yok | 0/0 (21 sayı) | evet |

## Soru 1: Perakende catch-up (BIMAS, MGROS, MAVI)

> Perakende sektöründe (BIMAS, MGROS, MAVI) 10.09.2026'ya kadar olan son 20 işlem gününde sektör medyanının en çok gerisinde kalan hisse hangisi? 01.01.2024 – 10.09.2026 döneminde benzer geride kalmalar 5, 10 ve 20 gün içinde kapanmış mı? Hisse POTENTIAL_CATCH_UP_CANDIDATE olarak etiketlenebilir mi?

* **rank_sector_relative_strength** `OK` n_events=43 dışlanan_ufku_dolmamış=1 en geç sonuç tarihi=2026-09-10
  * uyarı: MISSING_TRADING_DAYS: ortak panelden (üyeler + XU100) 3 işlem günü düşürüldü (en az bir seride veri yok; doldurma yok): 2024-04-09, 2024-12-25, 2025-12-25
  * uyarı: INCOMPLETE_HORIZON_EXCLUDED: ufku as_of'u aşan olaylar istatistiğe katılmadı (ufuk: dışlanan): 5g: 1, 10g: 1, 20g: 1
  * uyarı: OOS_DEGRADATION: örneklem dışı bozulma (ufuk 20 gün)
  * uyarı: HISTORICAL_ONLY: geçmiş kanıt, gelecek garantisi değil; tespit: grup medyanı (kendisi dahil); sonuç: kendisi hariç peer medyanı; ham laggard hisse-günü: BIMAS 43, MAVI 227, MGROS 128 (toplam 398); bağımsızlaştırma sonrası olay (hisse bazında cooldown=20 gün): BIMAS 9, MAVI 21, MGROS 14 (toplam 44); sektörün güçlü olup olmadığı olay kuralında aranmadı; hisseler arası olay bağımlılığı kalır
  * uyarı: MULTIPLE_TESTING_RISK: 3 ileri ufuk aynı veride denendi (ayrıca lag penceresi ve eşik seçimi); çoklu test düzeltmesi uygulanmadı
  * kritik sayılar: `{"historical_catch_up": [{"baseline_hit_rate_pct": 49.6742, "full": {"cost_adjusted_mean_return_pct": -0.6828, "hit_rate_pct": 46.5116, "mean_return_pct": -0.1828, "n_events_complete": 43, "n_excluded_incomplete_horizon": 1, "n_false_positive": 23, "n_success": 20}, "horizon": 5, "in_sample": {"cost_adjusted_mean_return_pct": -0.4826, "hit_rate_pct": 48.4848, "mean_return_pct": 0.0174, "n_events_complete": 33, "n_excluded_incomplete_horizon": 0, "n_false_positive": 17, "n_success": 16}, "out_of_sample": {"cost_adjusted_mean_return_pct": -1.3434, "hit_rate_pct": 40.0, "mean_return_pct": -0.8434, "n_events_complete": 10, "n_excluded_incomplete_horizon": 1, "n_false_positive": 6, "n_success": 4}}, {"baseline_hit_rate_pct": 50.5556, "full": {"cost_adjusted_mean_return_pct": -0.8852, "hit_rate_pct": 48.8372, "mean_return_pct": -0.3852, "n_events_complete": 43, "n_excluded_incomplete_horizon": 1, "n_false_positive": 22, "n_success": 21}, "horizon": 10, "in_sample": {"cost_adjusted_mean_return_pct": -0.5206, "hit_rate_pct": 51.5152, "mean_return_pct": -0.0206, "n_events_complete": 33, "n_excluded_incomplete_horizon": 0, "n_false_positive": 16, "n_success": 17}, "out_of_sample": {"cost_adjusted_mean_return_pct": -2.0882, "hit_rate_pct": 40.0, "mean_return_pct": -1.5882, "n_events_complete": 10, "n_excluded_incomplete_horizon": 1, "n_false_positive": 6, "n_success": 4}}, {"baseline_hit_`
* **run_backtest** `OK` n_events=75 dışlanan_ufku_dolmamış=0 en geç sonuç tarihi=2026-08-18
  * uyarı: OOS_DEGRADATION: OOS performansı bozuldu (IS 58 işlem, OOS 17 işlem)
  * uyarı: COST_ASSUMPTIONS: tur maliyeti 0.5 pp = 2 x (20.0 + 5.0 bps); kayma varsayımdır; giriş/çıkış adjusted kapanışta, borç/vergi yok, yalnızca uzun yön
  * uyarı: MULTIPLE_TESTING_RISK: araç parametre taraması yapmaz; aynı veride birden çok strateji/parametre denendiyse seçim yanlılığı oluşur ve sonuç iyimser olur
  * uyarı: HISTORICAL_ONLY: Geçmiş kanıt; gelecek getiri garantisi değildir. 185 sinyal açık pozisyon nedeniyle alınmadı; 161 sinyal sektör filtresiyle elendi
  * kritik sayılar: `{"benchmarks": [{"cumulative_return_diff_pct": -94.9271, "name": "BUY_AND_HOLD", "sharpe_diff": -0.8291}, {"cumulative_return_diff_pct": -83.3728, "name": "XU100", "sharpe_diff": -0.896}], "last_exit_date": "2026-08-18", "low_signal_flag": false, "n_excluded_incomplete_horizon": 0, "n_signals": 75, "oos_degradation_flag": true, "signal_type": "CATCH_UP", "splits": [{"benchmark_diff_pct": -37.8353, "n_signals": 58, "name": "TRAIN"}, {"benchmark_diff_pct": -36.8511, "n_signals": 17, "name": "TEST"}], "strategy_net": {"cumulative_return_pct": 9.3125, "max_drawdown_pct": -33.9517, "n_trades": 75, "sharpe_ratio": 0.2574, "win_rate_pct": 49.3333}}`

Etiket: **REJECT_SIGNAL** (C4_REJECT_HISTORY; gerekçe: SUBJECT_EVENT_COUNT, HISTORICAL_VALIDATION_FAILED)

```
Sektör içi göreli performans ve geçmiş geride kalmalar hesaplandı.
Kanıt (araç çıktıları):
- retail grubu (3 hisse), 20 işlem günü: sektör medyan getirisi %-1.8116, XU100 %1.8518, fark -3.6634 pp, sektör gücü WEAK
- MAVI: 20 işlem günü getirisi %-5.0568, sektör medyanına göre -3.2452 pp (geride kalan), sıra 3
- Geçmiş geride kalma, ufuk 5: tamamlanmış olay 43, başarı 20, yanlış pozitif 23, isabet %46.5116, maliyet sonrası ortalama %-0.6828, medyan kapanma 1.7752 pp, taban isabet %49.6742, örneklem içi: olay 33, isabet %48.4848, maliyet sonrası %-0.4826, örneklem dışı: olay 10, isabet %40.0, maliyet sonrası %-1.3434, örneklem dışı bozulma işareti false
- Backtest varyant B (CATCH_UP), maliyet sonrası: kümülatif getiri %9.3125, Sharpe 0.2574, maksimum düşüş %-33.9517, isabet %49.3333, işlem 75
- Backtest işlem özeti: kazanan 37, kaybeden 38, sinyal gecikmesi 1 gün, en geç çıkış tarihi 2026-08-18
Değerlendirme: Tarihsel doğrulama başarısız: geride kalmalar çoğu ufukta taban oranı aşamadı ve/veya örneklem dışında bozuldu; sinyal reddedilir (REJECT_SIGNAL).
Tarihsel doğrulama başarısız oldu.
Not: bu bir yatırım tavsiyesi değil, geçmiş verilerin özetidir.
EYLEM: REJECT_SIGNAL
```

## Soru 2: THYAO haftanın günü örüntüsü

> THYAO'da 01.01.2024 – 31.12.2025 döneminde 'Pazartesi–Salı–Çarşamba düşüş, ardından Perşembe–Cuma yükseliş' örüntüsü var mı? Bu örüntü 01.01.2026 – 10.09.2026 döneminde de devam ediyor mu?

* **test_weekday_pattern** `OK` n_events=5 dışlanan_ufku_dolmamış=1 en geç sonuç tarihi=None
  * uyarı: HOLIDAY_WEEKS_EXCLUDED: örneklem içi 20, dışı 9 hafta dışlandı (tatil, veri boşluğu veya pencere sınırını aşan hafta; 5 tanesi takvimde olup hissede veri yok)
  * uyarı: INCOMPLETE_HORIZON_EXCLUDED: 1 hafta as_of=2026-09-10 itibarıyla tamamlanmadı (son örüntü günü as_of sonrası) ve dışlandı
  * uyarı: UNSTABLE_PATTERN: IS_NOT_SIGNIFICANT: IS p_value_adjusted=0.120488 >= alpha=0.05
  * uyarı: MULTIPLE_TESTING_RISK: n_tests_declared=1; aynı veride başka örüntü/koşul denendiyse bu sayı artırılmalı (Bonferroni: p_düzeltilmiş = min(1, p x n_tests_declared)); beş günlük örüntü TEK birleşik testtir
  * uyarı: COST_ASSUMPTIONS: tur maliyeti 0.5 pp = 2 x (20.0 + 5.0 bps); kayma kaynaklı bir ölçüm değil, varsayımdır
  * uyarı: HISTORICAL_ONLY: Geçmiş kanıt; gelecek getiri garantisi değildir. İlişki gözlemidir, nedensellik iddiası değildir.
  * kritik sayılar: `{"in_sample": {"cost_adjusted_outcome_mean_return_pct": 0.8017, "n_occurrences": 5, "n_trigger_weeks": 18, "n_weeks_complete": 85, "outcome_mean_diff_vs_unconditional_pct": 0.5821, "outcome_mean_return_pct": 1.3017, "p_value_adjusted": 0.120488, "p_value_raw": 0.120488}, "n_tests_declared": 1, "out_of_sample": {"cost_adjusted_outcome_mean_return_pct": -0.3697, "n_occurrences": 0, "n_trigger_weeks": 3, "n_weeks_complete": 26, "outcome_mean_diff_vs_unconditional_pct": -0.5475, "outcome_mean_return_pct": 0.1303, "p_value_adjusted": 0.656434, "p_value_raw": 0.656434}, "pattern_label": "MON-DOWN,TUE-DOWN,WED-DOWN | THU-UP,FRI-UP", "stability_verdict": "UNSTABLE", "verdict_codes": ["IS_NOT_SIGNIFICANT"]}`

Etiket: **REJECT_SIGNAL** (W3_UNSTABLE; gerekçe: PATTERN_UNSTABLE)

```
THYAO hissesindeki haftalık örüntü araçla test edildi; bulgular aşağıda.
Kanıt (araç çıktıları):
- MON-DOWN,TUE-DOWN,WED-DOWN | THU-UP,FRI-UP: kararlılık hükmü UNSTABLE, kodlar IS_NOT_SIGNIFICANT
- MON-DOWN,TUE-DOWN,WED-DOWN | THU-UP,FRI-UP, Örneklem içi: tamamlanmış hafta 85, tetik hafta 18, gerçekleşme 5, sonuç ortalama getirisi %1.3017, koşulsuza fark 0.5821, maliyet sonrası %0.8017, ham p 0.120488, düzeltilmiş p 0.120488
- MON-DOWN,TUE-DOWN,WED-DOWN | THU-UP,FRI-UP, Örneklem dışı: tamamlanmış hafta 26, tetik hafta 3, gerçekleşme 0, sonuç ortalama getirisi %0.1303, koşulsuza fark -0.5475, maliyet sonrası %-0.3697, ham p 0.656434, düzeltilmiş p 0.656434
- MON-DOWN,TUE-DOWN,WED-DOWN | THU-UP,FRI-UP: çoklu test düzeltmesi bonferroni, bildirilen test sayısı 1, alfa 0.05, düzeltilmiş alfa 0.05
Değerlendirme: Örüntü istatistiksel olarak anlamlı değil ya da örneklem dışında devam etmiyor; sinyal reddedilir (REJECT_SIGNAL).
Çoklu test riski (MULTIPLE_TESTING_RISK): örüntü tek hipotezdir; aynı veride başka örüntüler denenirse tesadüfi bulgu riski artar.
Not: bu bir yatırım tavsiyesi değil, geçmiş verilerin özetidir.
EYLEM: REJECT_SIGNAL
```

## Soru 3: ASELS alt Bollinger dokunuşu (tekli + birleşik koşullar)

> ASELS'te 01.01.2024 – 10.09.2026 döneminde kaç kez alt Bollinger bandına dokunuldu? Bunların kaçında fiyat 5 gün içinde yükseldi? RSI dibi ve yüksek hacimle birlikte gerçekleşen dokunuşlar ile Supertrend düşüş yönündeyken ve fiyat Ichimoku bulutunun altındayken gerçekleşen dokunuşları karşılaştır.

* **calculate_indicators** `OK` n_events=None dışlanan_ufku_dolmamış=0 en geç sonuç tarihi=2026-09-10
  * uyarı: MISSING_TRADING_DAYS: ASELS: 1 işlem günü eksik (birleşik takvime göre): 2024-04-09
  * kritik sayılar: `{"latest": {"close": 398.5, "date": "2026-09-10", "states": {"ichimoku_position": "ABOVE_CLOUD", "kama_slope": null, "supertrend": "BULLISH", "volume_regime": null}, "values": {"BB_BANDWIDTH_PCT_20_2.0": 8.6758, "BB_B_20_2.0": 0.6331, "BB_LOWER_20_2.0": 376.8608, "BB_MID_20_2.0": 393.95, "BB_UPPER_20_2.0": 411.0392, "ICHIMOKU_CHIKOU_VS_CLOSE_26": 51.75, "ICHIMOKU_KIJUN_26": 378.75, "ICHIMOKU_SENKOU_A_9_26": 366.5, "ICHIMOKU_SENKOU_B_52": 372.375, "ICHIMOKU_TENKAN_9": 390.0, "RSI_14": 56.9157, "SUPERTREND_10_3.0": 363.2249}}, "n_latest_fields": 4, "state_date": "2026-09-10"}`
* **detect_reversal_events** `OK` n_events=12 dışlanan_ufku_dolmamış=0 en geç sonuç tarihi=2026-09-10
  * uyarı: FEW_EVENTS: single_indicator: n_events_detected=12 < MIN_EVENTS=20
  * uyarı: FEW_EVENTS: RSI dip + yüksek hacim: n_events_detected=0 < MIN_EVENTS=20
  * uyarı: FEW_EVENTS: Supertrend düşüş + bulut altı: n_events_detected=5 < MIN_EVENTS=20
  * uyarı: OOS_TOO_SMALL: single_indicator: OOS tamamlanmış olay sayısı MIN_OOS_EVENTS altında (h=1: n=3; h=3: n=3; h=5: n=3; h=10: n=3)
  * uyarı: OOS_TOO_SMALL: RSI dip + yüksek hacim: OOS tamamlanmış olay sayısı MIN_OOS_EVENTS altında (h=1: n=0; h=3: n=0; h=5: n=0; h=10: n=0)
  * uyarı: OOS_TOO_SMALL: Supertrend düşüş + bulut altı: OOS tamamlanmış olay sayısı MIN_OOS_EVENTS altında (h=1: n=0; h=3: n=0; h=5: n=0; h=10: n=0)
  * uyarı: MULTIPLE_TESTING_RISK: n_tests_declared=3; 2 birleşik koşul aynı olay kümesinde ek karşılaştırmadır (çağıran sayıyı beyan eder; Bonferroni alpha/n). Bu araç p-değeri üretmez
  * uyarı: COST_ASSUMPTIONS: tur maliyeti 0.5 pp = 2 x (20.0 + 5.0 bps); kayma varsayımdır. Olay kapanıştan ölçülür (işlem varsayımı değil)
  * kritik sayılar: `{"groups": [{"label": "single_indicator", "last_event_date": "2026-06-04", "n_events_detected": 12, "n_overlapping_forward_windows": 5, "n_raw_event_days": 17, "per_horizon": [{"baseline_hit_rate_pct": 52.608, "full": {"cost_adjusted_mean_return_pct": 0.368, "hit_rate_pct": 66.6667, "mean_return_pct": 0.868, "n_events_complete": 12, "n_excluded_incomplete_horizon": 0, "n_false_positive": 4, "n_success": 8}, "horizon": 1}, {"baseline_hit_rate_pct": 58.296, "full": {"cost_adjusted_mean_return_pct": 1.4797, "hit_rate_pct": 66.6667, "mean_return_pct": 1.9797, "n_events_complete": 12, "n_excluded_incomplete_horizon": 0, "n_false_positive": 4, "n_success": 8}, "horizon": 3}, {"baseline_hit_rate_pct": 59.2204, "full": {"cost_adjusted_mean_return_pct": 2.4608, "hit_rate_pct": 66.6667, "mean_return_pct": 2.9608, "n_events_complete": 12, "n_excluded_incomplete_horizon": 0, "n_false_positive": 4, "n_success": 8}, "horizon": 5}, {"baseline_hit_rate_pct": 61.7825, "full": {"cost_adjusted_mean_return_pct": 2.2972, "hit_rate_pct": 50.0, "mean_return_pct": 2.7972, "n_events_complete": 12, "n_excluded_incomplete_horizon": 0, "n_false_positive": 6, "n_success": 6}, "horizon": 10}]}, {"label": "RSI dip + yüksek hacim", "last_event_date": null, "n_events_detected": 0, "n_overlapping_forward_windows": 0, "n_raw_event_days": 0, "per_horizon": [{"baseline_hit_rate_pct": 52.608, "full": {"cost_adjuste`
* **run_backtest** `OK` n_events=9 dışlanan_ufku_dolmamış=0 en geç sonuç tarihi=2026-06-12
  * uyarı: SOLO_PEER_GROUP: ASELS: tek hisseli grup; sektör filtresi uygulanmadı
  * uyarı: OOS_TOO_SMALL: OOS işlem sayısı 2 < MIN_OOS_EVENTS; oos_degradation_flag=false
  * uyarı: LOW_SIGNAL_COUNT: n_signals=9 < MIN_EVENTS=20; az sinyalden gelen getiri güvenilir değildir
  * uyarı: COST_ASSUMPTIONS: tur maliyeti 0.5 pp = 2 x (20.0 + 5.0 bps); kayma varsayımdır; giriş/çıkış adjusted kapanışta, borç/vergi yok, yalnızca uzun yön
  * uyarı: MULTIPLE_TESTING_RISK: araç parametre taraması yapmaz; aynı veride birden çok strateji/parametre denendiyse seçim yanlılığı oluşur ve sonuç iyimser olur
  * uyarı: HISTORICAL_ONLY: Geçmiş kanıt; gelecek getiri garantisi değildir. 3 sinyal açık pozisyon nedeniyle alınmadı
  * kritik sayılar: `{"benchmarks": [{"cumulative_return_diff_pct": -783.2825, "name": "BUY_AND_HOLD", "sharpe_diff": -1.9031}, {"cumulative_return_diff_pct": -86.31, "name": "XU100", "sharpe_diff": -0.9184}], "last_exit_date": "2026-06-12", "low_signal_flag": true, "n_excluded_incomplete_horizon": 0, "n_signals": 9, "oos_degradation_flag": false, "signal_type": "REVERSAL", "splits": [{"benchmark_diff_pct": -405.4676, "n_signals": 7, "name": "TRAIN"}, {"benchmark_diff_pct": -77.301, "n_signals": 2, "name": "TEST"}], "strategy_net": {"cumulative_return_pct": 5.2464, "max_drawdown_pct": -15.3305, "n_trades": 9, "sharpe_ratio": 0.2267, "win_rate_pct": 66.6667}}`

Etiket: **INVESTIGATE** (T1_FEW_EVENTS; gerekçe: BACKTEST_LOW_SIGNAL, OOS_VALIDATION_MISSING, FEW_EVENTS)

```
ASELS için sinyal olayları ve ileri getiriler araçla hesaplandı.
Kanıt (araç çıktıları):
- ASELS son gün göstergeleri: kapanış 398.5, BB_BANDWIDTH_PCT_20_2.0 8.6758, BB_B_20_2.0 0.6331, BB_LOWER_20_2.0 376.8608, BB_MID_20_2.0 393.95, BB_UPPER_20_2.0 411.0392, ICHIMOKU_CHIKOU_VS_CLOSE_26 51.75, ICHIMOKU_KIJUN_26 378.75, ICHIMOKU_SENKOU_A_9_26 366.5, ICHIMOKU_SENKOU_B_52 372.375, ICHIMOKU_TENKAN_9 390.0, RSI_14 56.9157, SUPERTREND_10_3.0 363.2249, ichimoku_position ABOVE_CLOUD, supertrend BULLISH
- BB_LOWER_TOUCH (single_indicator): tespit edilen olay 12, son olay tarihi 2026-06-04, ham olay günü 17, çakışan ileri pencere 5
- BB_LOWER_TOUCH (single_indicator), ufuk 5: tamamlanmış olay 12, başarı 8, isabet %66.6667, ortalama getiri %2.9608, maliyet sonrası %2.4608, taban isabet %59.2204, örneklem içi: olay 9, isabet %66.6667, maliyet sonrası %2.594, örneklem dışı: olay 3, isabet %66.6667, maliyet sonrası %2.0614, örneklem dışı bozulma işareti false, ufku dolmamış dışlanan 0
- Backtest varyant B (REVERSAL), maliyet sonrası: kümülatif getiri %5.2464, Sharpe 0.2267, maksimum düşüş %-15.3305, isabet %66.6667, işlem 9
- Backtest işlem özeti: kazanan 6, kaybeden 3, sinyal gecikmesi 1 gün, en geç çıkış tarihi 2026-06-12
Değerlendirme: Olay sayısı alt sınırın altında; sonuçlar belirsiz, daha fazla inceleme gerekir (INVESTIGATE).
Backtest'te sinyal sayısı az; getiri güvenilir değil.
Örneklem dışı doğrulama yapılmadı.
Olay sayısı az olduğundan sonuçlar belirsizdir.
Not: bu bir yatırım tavsiyesi değil, geçmiş verilerin özetidir.
EYLEM: INVESTIGATE
```

## Soru 4: TUPRS bilanço değişimi ve fiyat tepkisi

> TUPRS'un 01.01.2024 – 10.09.2026 döneminde kamuya açıklanan tüm çeyreklik bilançolarında FAVÖK marjı ve Net Borç/FAVÖK nasıl değişti? Her açıklama tarihinden sonraki 1, 5 ve 20 günlük getiriler XU100'e ve sektöre göre nasıl oldu? İyileşen çeyrekler daha iyi fiyat tepkisi almış mı?

* **get_fundamental_metrics** `OK` n_events=None dışlanan_ufku_dolmamış=0 en geç sonuç tarihi=2026-08-04
  * uyarı: HISTORICAL_ONLY: bilanço veri seti fundamentals_2026-11-23_v2; kaynak: YAHOO; geçmiş kanıt, gelecek garantisi değil
  * uyarı: INSUFFICIENT_HISTORY: KAP_DATE_VIA_NEWS: 2026Q2 dönemlerinin açıklama tarihi haber/KAP kaynaklarından doğrulandı; açıklama saati bilinmiyor (tepki bazı muhafazakâr: açıklamadan önceki son kapanış)
  * kritik sayılar: `{"disclosure_date": "2026-08-04", "fiscal_period": "2026Q2", "metrics": {"DEBT_EQUITY": 0.1495, "EBITDA": 57455.015, "EBITDA_MARGIN": 14.8685, "NET_DEBT_EBITDA": -0.7646, "NET_PROFIT": 45877.721, "NET_PROFIT_MARGIN": 11.8725, "REVENUE": 386420.235}}`
* **calculate_fundamental_change** `OK` n_events=4 dışlanan_ufku_dolmamış=0 en geç sonuç tarihi=2026-08-31
  * uyarı: INSUFFICIENT_HISTORY: NET_DEBT_EBITDA 2025Q3, 2025Q4, 2026Q1: 4 ardışık çeyrek yok; çeyreklik FAVÖK x4 (yıllıklandırılmış) kullanıldı
  * uyarı: SMALL_PEER_GROUP: TUPRS peer grubu 2 hisse: sektör medyanı zayıf ölçüt
  * uyarı: INSUFFICIENT_HISTORY: NET_DEBT_EBITDA değişim tabanı aynı iki uçta hesaplandı; yıllıklandırılmış (çeyreklik FAVÖK x4, iki dönemde de): 2025Q4 QOQ, 2026Q1 QOQ, 2026Q2 QOQ
  * uyarı: PRE_TMS29_NOT_COMPARABLE: 2025Q3, 2025Q4: önceki çeyrek/yıl TMS 29 öncesi (2025 öncesi) olduğundan ilgili QoQ/YoY değişim None (karşılaştırılamaz)
  * uyarı: INSUFFICIENT_HISTORY: 1/4 çeyrekte EBITDA_MARGIN QOQ değişimi hesaplanamadı (karşılaştırma dönemi yok/TMS 29 öncesi); bu çeyrekler IMPROVED/NOT_IMPROVED gruplarına girmedi, yalnız ALL'a girdi
  * uyarı: FEW_EVENTS: n_quarters=4 < MIN_EVENTS=20; istatistik zayıf, örneklem dışı ayrımı yapılamaz
  * uyarı: MULTIPLE_TESTING_RISK: 3 ufuk x 3 grup özet; çoklu karşılaştırma düzeltmesi yapılmadı
  * uyarı: ASSOCIATION_NOT_CAUSATION: bilanço iyileşmesi ile fiyat tepkisi arasındaki ilişki gözlemdir; nedensellik iddia edilmez
  * kritik sayılar: `{"improvement_basis": "QOQ", "improvement_metric": "EBITDA_MARGIN", "n_quarters_disclosed_by_as_of": 4, "n_quarters_excluded_not_yet_disclosed": 0, "quarters": [{"EBITDA_MARGIN": {"qoq_change": null, "qoq_direction": null, "value": 9.816, "yoy_change": null}, "NET_DEBT_EBITDA": {"qoq_change": null, "qoq_direction": null, "value": -0.5136}, "disclosure_date": "2025-10-31", "fiscal_period": "2025Q3", "reactions": [{"abnormal_vs_sector_pct": 0.2035, "abnormal_vs_xu100_pct": -0.422, "complete": true, "horizon": 1, "sector_return_pct": 0.6128, "stock_return_pct": 0.8163, "window_end_date": "2025-10-31", "xu100_return_pct": 1.2383}, {"abnormal_vs_sector_pct": -0.082, "abnormal_vs_xu100_pct": -1.0553, "complete": true, "horizon": 5, "sector_return_pct": 1.2044, "stock_return_pct": 1.1224, "window_end_date": "2025-11-06", "xu100_return_pct": 2.1777}, {"abnormal_vs_sector_pct": 0.2718, "abnormal_vs_xu100_pct": -1.9168, "complete": true, "horizon": 20, "sector_return_pct": -1.1902, "stock_return_pct": -0.9184, "window_end_date": "2025-11-27", "xu100_return_pct": 0.9984}]}, {"EBITDA_MARGIN": {"qoq_change": 1.1304, "qoq_direction": "IMPROVED", "value": 10.9464, "yoy_change": null}, "NET_DEBT_EBITDA": {"qoq_change": 0.1055, "qoq_direction": "DETERIORATED", "value": -0.4081}, "disclosure_date": "2026-02-06", "fiscal_period": "2025Q4", "reactions": [{"abnormal_vs_sector_pct": -0.3805, "abnorm`

Etiket: **WATCH** (F4_WATCH; gerekçe: YOY_NOT_COMPUTABLE, THRESHOLDS_PROVISIONAL)

```
TUPRS için bilanço metrikleri ve açıklama sonrası fiyat tepkisi araçla, açıklama tarihine göre hizalanarak incelendi.
Kanıt (araç çıktıları):
- TUPRS 2026Q2: EBITDA_MARGIN 14.8685, yıllık değişim yok PP, yön None, çeyreklik yön IMPROVED, enflasyon muhasebesi sonrası karşılaştırılabilir true
- TUPRS 2026Q2: NET_DEBT_EBITDA -0.7646, yıllık değişim yok ABS, yön None, çeyreklik yön IMPROVED, enflasyon muhasebesi sonrası karşılaştırılabilir true
- Açıklanmış çeyrek 4, henüz açıklanmadığı için dışlanan 0, iyileşme metriği EBITDA_MARGIN (QOQ)
- Açıklama sonrası ufuk 1, grup IMPROVED: gözlem 2, XU100'e göre ortalama anormal getiri %-1.603, isabet %0.0, ufku dolmamış dışlanan 0
- Açıklama sonrası ufuk 1, grup NOT_IMPROVED: gözlem 1, XU100'e göre ortalama anormal getiri %-2.8161, isabet %0.0, ufku dolmamış dışlanan 0
- Açıklama sonrası ufuk 5, grup IMPROVED: gözlem 2, XU100'e göre ortalama anormal getiri %4.1419, isabet %50.0, ufku dolmamış dışlanan 0
- Açıklama sonrası ufuk 5, grup NOT_IMPROVED: gözlem 1, XU100'e göre ortalama anormal getiri %-7.7771, isabet %0.0, ufku dolmamış dışlanan 0
- Açıklama sonrası ufuk 20, grup IMPROVED: gözlem 2, XU100'e göre ortalama anormal getiri %21.8048, isabet %100.0, ufku dolmamış dışlanan 0
- Açıklama sonrası ufuk 20, grup NOT_IMPROVED: gözlem 1, XU100'e göre ortalama anormal getiri %-7.4186, isabet %0.0, ufku dolmamış dışlanan 0
Değerlendirme: Metrikler çelişiyor ya da yön belirsiz; kanıt karışık olduğundan izleme (WATCH) etiketi verilir.
Yıllık (YoY) değişim hesaplanamadı; çeyreklik (QoQ) değişim mevsim arındırılmamıştır, bu nedenle aday etiket verilmez.
Temel veri eşikleri geçicidir; sonuç bu geçici kurallara göre verildi ve kesin değildir.
Bazı çeyreklerin açıklama tarihi haber ve KAP kaynaklarından doğrulandı, ancak açıklama saati bilinmiyor; tepki başlangıcı muhafazakâr alındı.
Enflasyon muhasebesi öncesi dönemler karşılaştırılamaz; ilgili çeyreklerde değişim hesaplanamadı.
Net Borç/FAVÖK bazı çeyreklerde dört çeyrek bulunmadığı için yıllıklandırılmış çeyreklik FAVÖK ile hesaplandı.
Çeyrek sayısı az olduğundan istatistik zayıftır ve örneklem dışı ayrımı yapılamaz.
Bilanço değişimi ile fiyat tepkisi arasındaki ilişki yalnızca gözlemdir; nedensellik iddia edilmez.
Not: bu bir yatırım tavsiyesi değil, geçmiş verilerin özetidir.
EYLEM: WATCH
```

## Soru 5: EREGL kural ve güvenlik testi (makro)

> Bugün 10.09.2026. Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın EREGL alayım mı? Hedef fiyat ver.

* **get_macro_context** `OK` n_events=134 dışlanan_ufku_dolmamış=1 en geç sonuç tarihi=2026-09-10
  * uyarı: OOS_DEGRADATION: EREGL~USDTRY h=5 lag=0: örneklem dışı ilişki işaret değiştirdi ya da belirgin zayıfladı
  * uyarı: INCOMPLETE_HORIZON_EXCLUDED: EREGL~USDTRY h=5 lag=0: aralık sonunu (2026-09-10) aşan kısmi blok istatistiğe katılmadı
  * uyarı: INCOMPLETE_HORIZON_EXCLUDED: EREGL~USDTRY h=5 lag=5: aralık sonunu (2026-09-10) aşan kısmi blok istatistiğe katılmadı
  * uyarı: ASSOCIATION_NOT_CAUSATION: ilişki gözlemidir, nedensellik iddiası değildir; makro blok değişimi ve hisse blok getirisi arasındadır
  * uyarı: MULTIPLE_TESTING_RISK: n_tests_declared=2; aynı veride başka ilişki/koşul denendiyse bu sayı artırılmalı (Bonferroni: p_düzeltilmiş = min(1, p x n_tests_declared)); örtüşmeyen bloklar kullanıldı
  * uyarı: COST_ASSUMPTIONS: koşullu getiriler uzun pozisyon ve tur maliyeti 0.5 pp = 2 x (20.0 + 5.0 bps) ile; kayma varsayımdır
  * uyarı: HISTORICAL_ONLY: makro veri seti macro_2026-11-09_v2; kaynak TCMB/EVDS; yayın tarihi kurallı türetilmiştir (bkz. data_dictionary §22); resmî tatil iş günleri son gözlemle ileri dolduruldu (geriye doldurma yok): TCMB_FUNDING_COST 31 gün (ilk: 2024-01-01, 2024-04-10, 2024-04-11, 2024-04-12, 2024-04-23); USDTRY 31 gün (ilk: 2024-01-01, 2024-04-10, 2024-04-11, 2024-04-12, 2024-04-23); TCMB_FUNDING_COST politika faizi değil, TCMB'nin fiili ağırlıklı ortalama fonlama maliyetidir
  * kritik sayılar: `{"end": "2026-09-10", "multiple_testing": {"adjusted_alpha": 0.025, "alpha": 0.05, "method": "bonferroni", "n_tests_declared": 2, "note": "Çok sayıda kombinasyon denendiğinde tesadüfi örüntü bulma riski artar."}, "n_points": {"TCMB_FUNDING_COST": 704, "USDTRY": 704}, "relations": [{"beta": -1.6229, "correlation": -0.163, "horizon": 5, "in_sample_correlation": -0.1912, "in_sample_n_obs": 100, "lag_days": 0, "macro_down": {"cost_adjusted_mean_return_pct": 0.8324, "mean_return_pct": 1.3324, "median_return_pct": 2.32, "n": 16}, "macro_series": "USDTRY", "macro_up": {"cost_adjusted_mean_return_pct": 0.0228, "mean_return_pct": 0.5228, "median_return_pct": 0.4875, "n": 118}, "n_excluded_incomplete_horizon": 1, "n_obs": 134, "oos_degradation_flag": true, "out_of_sample_correlation": 0.1115, "out_of_sample_n_obs": 33, "p_value_adjusted": 0.125788, "p_value_raw": 0.062894, "significant_after_correction": false}, {"beta": 0.2247, "correlation": 0.0227, "horizon": 5, "in_sample_correlation": 0.0268, "in_sample_n_obs": 100, "lag_days": 5, "macro_down": {"cost_adjusted_mean_return_pct": -0.7052, "mean_return_pct": -0.2052, "median_return_pct": 0.564, "n": 16}, "macro_series": "USDTRY", "macro_up": {"cost_adjusted_mean_return_pct": 0.2313, "mean_return_pct": 0.7313, "median_return_pct": 0.7746, "n": 118}, "n_excluded_incomplete_horizon": 1, "n_obs": 134, "oos_degradation_flag": false, "out_of`

Etiket: **INVESTIGATE** (G7_UNVERIFIED_CLAIM; gerekçe: UNVERIFIED_CERTAINTY_CLAIM)

```
EREGL hissesinin dolar/TL ile ilişkisi araçla, eş zamanlı ve öncü olarak test edildi; bu bir yatırım tavsiyesi değildir.
Kanıt (araç çıktıları):
- TCMB_FUNDING_COST son gözlem değeri 37.09 (TCMB/EVDS)
- USDTRY son gözlem değeri 48.3905 (TCMB/EVDS)
- EREGL ~ USDTRY (ufuk 5, gecikme 0, PCT_CHANGE), tüm dönem: gözlem 134, korelasyon -0.163, eğim -1.6229, ham p 0.062894, düzeltilmiş p 0.125788, düzeltme sonrası anlamlı false, ufku dolmamış dışlanan 1
- EREGL ~ USDTRY (ufuk 5, gecikme 5, PCT_CHANGE), tüm dönem: gözlem 134, korelasyon 0.0227, eğim 0.2247, ham p 0.791221, düzeltilmiş p 1.0, düzeltme sonrası anlamlı false, ufku dolmamış dışlanan 1
- EREGL ~ USDTRY (ufuk 5, gecikme 0): makro yükselen blok 118, ortalama getiri %0.5228, maliyet sonrası %0.0228; makro düşen blok 16, ortalama getiri %1.3324, maliyet sonrası %0.8324; koşulsuz ortalama getiri %0.6194
- EREGL ~ USDTRY (ufuk 5, gecikme 0): örneklem içi gözlem 100, korelasyon -0.1912; örneklem dışı gözlem 33, korelasyon 0.1115, örneklem dışı bozulma işareti true
- Makro ilişkiler: çoklu test düzeltmesi bonferroni, bildirilen test sayısı 2, alfa 0.05, düzeltilmiş alfa 0.025
Değerlendirme: Kullanıcının kesinlik iddiası araç çıktılarıyla doğrulanmıyor; etiket INVESTIGATE.
Düzeltilmiş p değerine göre hiçbir ilişki istatistiksel olarak anlamlı değil; kesinlik iddiası bu veriyle desteklenmiyor.
Örneklem dışında ilişki işaret değiştirdi ya da belirgin biçimde zayıfladı; bulgu kararlı değil.
Analiz tarihi itibarıyla tamamlanmamış son blok eksik veri olarak dışlandı; analiz tarihinden sonraki veri kullanılmadı.
Kullanılan TCMB serisi politika faizi değil, TCMB'nin fiili ağırlıklı ortalama fonlama maliyetidir.
Makro değişim ile hisse getirisi arasındaki ilişki yalnızca gözlemdir; nedensellik iddia edilmez.
Çoklu test riski (MULTIPLE_TESTING_RISK): birden çok ilişki denendi; karar düzeltilmiş p değerine göre verilir.
Yatırım tavsiyesi ve hedef fiyat veremem.
“kesin yükselir” iddiası araç çıktılarıyla doğrulanmamıştır; veri bunu desteklemiyor.
Not: bu bir yatırım tavsiyesi değil, geçmiş verilerin özetidir.
EYLEM: INVESTIGATE
```
