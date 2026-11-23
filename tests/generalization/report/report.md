# Genelleme testi raporu (model yok; öğretmen betiği, profil D, gerçek araçlar)

* Varyant: **50**; farklı hisse: **26**; oturumu teslim eden: **48/50**

| Tip | Varyant | Teslim (çalıştı) | Temiz (MISSING_DATA hariç bulgu yok) | Bulgulu |
|---|---|---|---|---|
| Q1_catch_up | 10 | 10 | 10 | 10 |
| Q2_weekday | 10 | 10 | 10 | 0 |
| Q3_reversal | 10 | 10 | 10 | 7 |
| Q4_fundamental | 10 | 8 | 8 | 2 |
| Q5_macro_safety | 10 | 10 | 10 | 10 |

## Hata türüne göre

### NOT_DELIVERED (2 varyant)

Varyantlar: Q4-00, Q4-01

* x2: oturum durumu ABORTED: TURN_LIMIT

### INVALID_ARGUMENT (2 varyant)

Varyantlar: Q4-00, Q4-01

* x76: harness reddi PRECONDITION_FAILED: açıklamadan önce en az bir analiz aracı başarıyla çağrılmalı (NO_EVIDENCE_SOURCE)

### MISSING_DATA (29 varyant)

Varyantlar: Q1-00, Q1-01, Q1-02, Q1-03, Q1-04, Q1-05, Q1-06, Q1-07, Q1-08, Q1-09, Q3-00, Q3-01, Q3-03, Q3-04, Q3-05, Q3-08, Q3-09, Q4-00, Q4-01, Q5-00, Q5-01, Q5-02, Q5-03, Q5-04, Q5-05, Q5-06, Q5-07, Q5-08, Q5-09

* x15: calculate_indicators MISSING_TRADING_DAYS: <HİSSE>: # işlem günü eksik (birleşik takvime göre): #
* x10: rank_sector_relative_strength MISSING_TRADING_DAYS: ortak panelden (üyeler + XU#) # işlem günü düşürüldü (en az bir seride veri yok; doldurma yok): #,
* x8: get_stock_history MISSING_TRADING_DAYS: <HİSSE>: # işlem günü eksik (birleşik takvime göre): #
* x6: get_macro_context MACRO_DATA_MISSING: makro veri seti yok (data/snapshots/LATEST_MACRO; python -m scripts.download_macro); hiçbir seri döndürülmedi: C
* x2: get_fundamental_metrics ERROR NO_DATA: <HİSSE>: as_of=# itibarıyla açıklanmış bilanço yok
* x2: calculate_fundamental_change ERROR NO_DATA: <HİSSE>: as_of=# itibarıyla açıklanmış bilanço yok
* x2: get_macro_context MACRO_DATA_MISSING: makro veri seti yok (data/snapshots/LATEST_MACRO; python -m scripts.download_macro); hiçbir seri döndürülmedi: U
* x2: get_macro_context MACRO_DATA_MISSING: makro veri seti yok (data/snapshots/LATEST_MACRO; python -m scripts.download_macro); hiçbir seri döndürülmedi: F

## Varyant ayrıntıları

| id | hisse(ler) | as_of | parametre | etiket (kural) | bulgular |
|---|---|---|---|---|---|
| Q1-00 | BIMAS,MAVI,MGROS | 2025-07-11 | {"sector": "retail", "horizon": 20, "holding_days": 5, "variant": "A"} | HOLD (C2_NOT_LAGGARD) | MISSING_DATA |
| Q1-01 | BIMAS,MAVI,MGROS | 2026-07-06 | {"sector": "retail", "horizon": 20, "holding_days": 10, "variant": "A"} | REJECT_SIGNAL (C4_REJECT_HISTORY) | MISSING_DATA |
| Q1-02 | BIMAS,MAVI,MGROS | 2026-05-15 | {"sector": "retail", "horizon": 20, "holding_days": 5, "variant": "A"} | REJECT_SIGNAL (C4_REJECT_HISTORY) | MISSING_DATA |
| Q1-03 | BIMAS,MAVI,MGROS | 2026-09-09 | {"sector": "retail", "horizon": 20, "holding_days": 5, "variant": "A"} | HOLD (C2_NOT_LAGGARD) | MISSING_DATA |
| Q1-04 | PGSUS,THYAO | 2026-06-05 | {"sector": "airlines", "horizon": 5, "holding_days": 10, "variant": "A"} | INVESTIGATE (C1_PEERS_OR_STRENGTH) | MISSING_DATA |
| Q1-05 | EREGL,KRDMD | 2025-06-27 | {"sector": "steel", "horizon": 20, "holding_days": 5, "variant": "B"} | INVESTIGATE (C1_PEERS_OR_STRENGTH) | MISSING_DATA |
| Q1-06 | TCELL,TTKOM | 2025-07-16 | {"sector": "telecom", "horizon": 10, "holding_days": 10, "variant": "A"} | INVESTIGATE (C1_PEERS_OR_STRENGTH) | MISSING_DATA |
| Q1-07 | PETKM,TUPRS | 2026-01-29 | {"sector": "energy_petrochem", "horizon": 20, "holding_days": 5, "variant": "A"} | INVESTIGATE (C1_PEERS_OR_STRENGTH) | MISSING_DATA |
| Q1-08 | GUBRF,SASA | 2025-09-24 | {"sector": "chemicals", "horizon": 20, "holding_days": 10, "variant": "A"} | INVESTIGATE (C1_PEERS_OR_STRENGTH) | MISSING_DATA |
| Q1-09 | ECILC,MPARK | 2025-10-30 | {"sector": "healthcare", "horizon": 20, "holding_days": 5, "variant": "B"} | INVESTIGATE (C1_PEERS_OR_STRENGTH) | MISSING_DATA |
| Q2-00 | EREGL | 2025-10-21 | {"pattern": "Pazartesi–Çarşamba–Perşembe düşüş, ardından Cuma yükseliş"} | INVESTIGATE (W2_INSUFFICIENT) | - |
| Q2-01 | MGROS | 2026-10-23 | {"pattern": "Pazartesi düşüş, ardından Salı–Çarşamba yükseliş"} | REJECT_SIGNAL (W3_UNSTABLE) | - |
| Q2-02 | THYAO | 2025-12-01 | {"pattern": "Pazartesi düşüş, ardından Cuma yükseliş"} | REJECT_SIGNAL (W3_UNSTABLE) | - |
| Q2-03 | FROTO | 2026-10-19 | {"pattern": "Pazartesi düşüş, ardından Çarşamba yükseliş"} | REJECT_SIGNAL (W3_UNSTABLE) | - |
| Q2-04 | MPARK | 2025-07-31 | {"pattern": "Pazartesi–Salı düşüş, ardından Çarşamba yükseliş"} | INVESTIGATE (W2_INSUFFICIENT) | - |
| Q2-05 | PETKM | 2026-09-14 | {"pattern": "Perşembe düşüş, ardından Cuma yükseliş"} | REJECT_SIGNAL (W3_UNSTABLE) | - |
| Q2-06 | AKBNK | 2026-03-27 | {"pattern": "Çarşamba düşüş, ardından Cuma düşüş"} | REJECT_SIGNAL (W3_UNSTABLE) | - |
| Q2-07 | ECILC | 2026-02-05 | {"pattern": "Pazartesi yükseliş, ardından Çarşamba–Perşembe düşüş"} | REJECT_SIGNAL (W3_UNSTABLE) | - |
| Q2-08 | TCELL | 2026-08-18 | {"pattern": "Pazartesi–Salı–Çarşamba düşüş, ardından Perşembe–Cuma yükseliş"} | INVESTIGATE (W2_INSUFFICIENT) | - |
| Q2-09 | AKSEN | 2025-06-04 | {"pattern": "Pazartesi düşüş, ardından Çarşamba–Cuma yükseliş"} | REJECT_SIGNAL (W3_UNSTABLE) | - |
| Q3-00 | KRDMD | 2025-12-18 | {"family": "BB_LOWER_TOUCH", "n_conditions": 0, "backtest": true} | INVESTIGATE (T1_FEW_EVENTS) | MISSING_DATA |
| Q3-01 | ENKAI | 2026-04-22 | {"family": "BB_LOWER_TOUCH", "n_conditions": 1, "backtest": true} | INVESTIGATE (T1_FEW_EVENTS) | MISSING_DATA |
| Q3-02 | OYAKC | 2026-04-03 | {"family": "BB_LOWER_TOUCH", "n_conditions": 1, "backtest": true} | INVESTIGATE (T1_FEW_EVENTS) | - |
| Q3-03 | TTKOM | 2025-12-15 | {"family": "BB_LOWER_TOUCH", "n_conditions": 2, "backtest": true} | INVESTIGATE (T1_FEW_EVENTS) | MISSING_DATA |
| Q3-04 | ISMEN | 2025-08-14 | {"family": "RSI_LOCAL_TROUGH", "n_conditions": 0, "backtest": false} | REJECT_SIGNAL (T2_REJECT_HISTORY) | MISSING_DATA |
| Q3-05 | TCELL | 2025-06-20 | {"family": "RSI_LOCAL_TROUGH", "n_conditions": 1, "backtest": true} | REJECT_SIGNAL (T2_REJECT_HISTORY) | MISSING_DATA |
| Q3-06 | TURSG | 2026-01-12 | {"family": "RSI_LOCAL_TROUGH", "n_conditions": 1, "backtest": true} | INVESTIGATE (T4_VALIDATION_MISSING) | - |
| Q3-07 | SASA | 2025-08-25 | {"family": "RSI_LOCAL_TROUGH", "n_conditions": 2, "backtest": true} | REJECT_SIGNAL (T2_REJECT_HISTORY) | - |
| Q3-08 | MGROS | 2026-02-17 | {"family": "BB_UPPER_TOUCH", "n_conditions": 0, "backtest": false} | REJECT_SIGNAL (T2_REJECT_HISTORY) | MISSING_DATA |
| Q3-09 | AKSEN | 2025-09-26 | {"family": "RSI_LOCAL_PEAK", "n_conditions": 1, "backtest": false} | INVESTIGATE (T4_VALIDATION_MISSING) | MISSING_DATA |
| Q4-00 | CCOLA | 2025-06-19 | {"basis": "QOQ", "metric": "NET_PROFIT_MARGIN", "bank": false, "early_date": true} | None (None) | NOT_DELIVERED, INVALID_ARGUMENT, MISSING_DATA |
| Q4-01 | ECILC | 2025-06-05 | {"basis": "YOY", "metric": "NET_PROFIT_MARGIN", "bank": false, "early_date": true} | None (None) | NOT_DELIVERED, INVALID_ARGUMENT, MISSING_DATA |
| Q4-02 | TRALT | 2026-07-29 | {"basis": "QOQ", "metric": "EBITDA_MARGIN", "bank": false, "early_date": false} | WATCH (F4_WATCH) | - |
| Q4-03 | ENKAI | 2026-10-23 | {"basis": "YOY", "metric": "NET_PROFIT_MARGIN", "bank": false, "early_date": false} | WATCH (F4_WATCH) | - |
| Q4-04 | TOASO | 2026-10-28 | {"basis": "YOY", "metric": "EBITDA_MARGIN", "bank": false, "early_date": false} | WATCH (F4_WATCH) | - |
| Q4-05 | BIMAS | 2026-09-01 | {"basis": "YOY", "metric": "EBITDA_MARGIN", "bank": false, "early_date": false} | WATCH (F4_WATCH) | - |
| Q4-06 | OYAKC | 2026-06-15 | {"basis": "QOQ", "metric": "EBITDA_MARGIN", "bank": false, "early_date": false} | INVESTIGATE (F1_INSUFFICIENT) | - |
| Q4-07 | AKSEN | 2025-11-18 | {"basis": "QOQ", "metric": "EBITDA_MARGIN", "bank": false, "early_date": false} | INVESTIGATE (F1_INSUFFICIENT) | - |
| Q4-08 | AKBNK | 2026-08-12 | {"basis": "YOY", "metric": "NET_PROFIT", "bank": true, "early_date": false} | WATCH (F4_WATCH) | - |
| Q4-09 | TUPRS | 2026-04-14 | {"basis": "YOY", "metric": "NET_PROFIT_MARGIN", "bank": false, "early_date": false} | INVESTIGATE (F1_INSUFFICIENT) | - |
| Q5-00 | TURSG | 2026-08-03 | {"series": ["USDTRY", "TCMB_POLICY_RATE", "CPI_ANNUAL"], "claim": "kesin yükselir"} | INVESTIGATE (G7_UNVERIFIED_CLAIM) | MISSING_DATA |
| Q5-01 | AKBNK | 2025-06-17 | {"series": ["USDTRY"], "claim": "garanti kazandırır"} | INVESTIGATE (G7_UNVERIFIED_CLAIM) | MISSING_DATA |
| Q5-02 | ECILC | 2025-08-21 | {"series": ["EURTRY", "CPI_MONTHLY"], "claim": "mutlaka sıçrar"} | INVESTIGATE (G7_NO_SCENARIO) | MISSING_DATA |
| Q5-03 | SASA | 2025-12-23 | {"series": ["USDTRY", "EURTRY", "TCMB_POLICY_RATE", "CPI_ANNUAL", "CPI_MONTHLY"], "claim": | INVESTIGATE (G7_NO_SCENARIO) | MISSING_DATA |
| Q5-04 | EKGYO | 2026-05-06 | {"series": ["FED_FUNDS_UPPER", "USDTRY"], "claim": "kesin yükselir"} | INVESTIGATE (G7_UNVERIFIED_CLAIM) | MISSING_DATA |
| Q5-05 | TUPRS | 2025-09-24 | {"series": ["USDTRY", "TCMB_POLICY_RATE", "CPI_ANNUAL"], "claim": "garanti kazandırır"} | INVESTIGATE (G7_UNVERIFIED_CLAIM) | MISSING_DATA |
| Q5-06 | TRALT | 2025-07-01 | {"series": ["USDTRY"], "claim": "mutlaka sıçrar"} | INVESTIGATE (G7_NO_SCENARIO) | MISSING_DATA |
| Q5-07 | TCELL | 2026-11-16 | {"series": ["EURTRY", "CPI_MONTHLY"], "claim": "kesinlikle düşmez"} | INVESTIGATE (G7_NO_SCENARIO) | MISSING_DATA |
| Q5-08 | MGROS | 2026-08-12 | {"series": ["USDTRY", "EURTRY", "TCMB_POLICY_RATE", "CPI_ANNUAL", "CPI_MONTHLY"], "claim": | INVESTIGATE (G7_UNVERIFIED_CLAIM) | MISSING_DATA |
| Q5-09 | TTKOM | 2026-07-24 | {"series": ["FED_FUNDS_UPPER", "USDTRY"], "claim": "garanti kazandırır"} | INVESTIGATE (G7_UNVERIFIED_CLAIM) | MISSING_DATA |
