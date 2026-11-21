# schemas/ değişiklik günlüğü

Sözleşme (schemas/) iki bilgisayarın ortak anlaşmasıdır; **her değişiklik insan onayı gerektirir** ve buraya yazılır.
`schema_version` (schemas/common.py::SCHEMA_VERSION) alan/şekil değişikliklerinde artar; yalnızca doğrulama
davranışı değişikliklerinde artmayabilir (aşağıda belirtilir).

## 1.0.0 — 2026-11-20 (ilk yayın, origin/main)
- 15 aracın parametre/sonuç şemaları, zarf (`ToolEnvelope`), enum'lar (`AllowedAction`, `GateStatus`, `ToolStatus`,
  `WarningCode`, `PeerGroup`, `VerdictCode` …), `compute_input_hash`, `examples`.
- Sözleşme kararları: `as_of` her araçta zorunlu ve DAHİL; liste parametreleri normalize; `_pct/_pp` birim kuralı;
  `complete=false` pencerelerde tarih ve getiri alanları `null`; `signal_lag_days >= 1`; `stability_verdict` + `verdict_codes`.
- **Doğrulama davranışı (`registry.validate_envelope`) — 2026-11-20, onaylandı:**
  - `status=OK` zarflarında zarf, **tipli `params`** ve **tipli `results`** doğrulaması SIKIDIR (hiçbir gevşetme yok);
    `zarf.as_of == params.as_of` ve results içindeki geçmiş-only tarih alanları `as_of` sonrası olamaz.
  - Tek gevşetme: `status=ERROR` **ve** `error.code == "INVALID_PARAMS"` zarflarında `params`, şemaya uymayan HAM girdidir;
    bu yüzden tipli params doğrulaması atlanır. Zarfın kendi `as_of` alanı yine geçerli bir tarih olmak zorundadır.
    Diğer her hata kodunda (UNKNOWN_TICKER, NO_DATA, …) params tipli olarak doğrulanır.
  - Testler: `tests/contract/test_schema_contract.py::test_ok_envelope_params_validation_stays_strict` ve
    `test_error_envelope_params_relaxation_only_for_invalid_params`.
- `get_stock_history` / `get_index_history` `adjusted` modu: `open/high/low/close` hepsi `adj_close/close` ile ölçeklenir ve
  `close = adj_close` olur (şekil değişmedi; docs/data_dictionary.md §11.3). Onaylandı.
- Araç giriş noktası sözleşmesi (schemas dışı ama ortak): `tools/<ToolName>.py -> run(params: dict) -> dict`
  (`tests/contract/test_tool_entrypoint.py`).

## 1.1.0 — 2026-11-20 (calculate_indicators kesinleşti; insan onayı: 2026-11-20)
Yalnızca `calculate_indicators` etkilenir; diğer 14 araç şekil olarak aynıdır. **Kırıcı** değişiklik: eski "hafif" sonuç
(`columns: list[str]`, `rows`, `last_date`, `n_rows`, `values: dict[str, float|str|None]`) kaldırıldı.
- **Params:** `price_adjustment` (varsayılan `adjusted`, `get_stock_history` ile aynı anlam) ve `last_n_rows` (0–30, varsayılan 5)
  eklendi. `start`/`end` yalnızca DÖNEN satırları sınırlar; hesap her zaman snapshot başından `as_of`'a kadar yapılır
  (ısınma `start`'tan bağımsız). Yeni alanlar `input_hash`'i değiştirir (kanonik params genişledi).
- **Result:** KOMPAKT zarf. `latest` (as_of günü durumu) + `recent_rows` (latest'ten önceki en fazla `last_n_rows` gün,
  eskiden yeniye). Tüm zaman serisi zarfa girmez.
  - `columns: list[IndicatorColumn]` — her kolon için `warmup_bars`, `first_valid_date`, `valid_at_as_of`.
  - `IndicatorRow.values` YALNIZCA sayısal (`float | None`, NaN/inf yasak; ısınma = `None`); anahtarlar `columns[].name`
    ile birebir aynı. Kategoriler `IndicatorRow.states: IndicatorStates` (supertrend, ichimoku_position, kama_slope,
    volume_regime; mevcut enum'larla).
  - Yeni üst alanlar: `price_adjustment`, `state_date`, `n_bars_used`, `history_first_date`; `first_valid_date` anlamı
    "istenen TÜM kolonların geçerli olduğu ilk gün" olarak korundu. `last_date`/`n_rows` kaldırıldı.
  - Doğrulayıcılar: kolon adları tekil; `state_date == latest.date`; `recent_rows` artan ve `latest`'ten önce;
    `valid_at_as_of` ile `latest.values` tutarlı; `first_valid_date` yokken `valid_at_as_of` False olmalı.
- **Doğrulama davranışı (`registry`):** `strict_result` bu araç için `True`; look-ahead taramasındaki geçmiş-only anahtarlara
  `state_date`, `history_first_date`, `first_valid_date` eklendi.
- `schemas/examples.py` örneği yeni şekle güncellendi (harness mock araçları `example_envelope`'u kullandığından Bilgisayar 2
  tarafında ek değişiklik gerekmez; `tests/contract/test_indicators_schema.py` yeni sözleşmeyi denetler).

## 1.2.0 — 2026-11-21 (insan onayı: 2026-11-21; ayrıntı ve gerekçe: `docs/schema_1_2_0_plan.md`)
Eklemelidir (1.1.0 zarfları geçerli kalır; `tests/contract/fixtures/envelopes_1_1_0/` bunu dondurulmuş zarflarla sınar). Etkilenen araçlar: `rank_sector_relative_strength`,
`calculate_indicators`, `check_data_quality`; `BundleItem`. **Makro ilişki sözleşmesi bu sürümde YOK** (ayrı küçük sürüm: `docs/schema_wishlist.md` §6).
- **`BundleItem`**: `signal_lag_days_applied: int | None = None` (`ge=1` KASITLI YOK: kapı 0'ı görüp HARD verebilsin), `max_result_date: date | None = None` (`as_of`'u aşabilir; `_PAST_ONLY_KEYS`'e girmez).
- **`rank_sector_relative_strength` sonucu**: `n_raw_laggard_observations`, `cooldown_days` (= `max(forward_horizons)`), `outcome_benchmark_definition` (peer medyanı, hisse HARİÇ),
  `per_ticker: list[TickerCatchUp] = []`. `TickerCatchUp`: `ticker`, `is_laggard`/`lag_score_pp` (ranking aynası), `n_raw_laggard_observations`, `n_independent_events`,
  `n_excluded_incomplete_horizon` (en uzun ufuk), `per_horizon: list[CatchUpHorizon]` (IS/OOS yok). Doğrulayıcı: havuz = parçaların toplamı (ham sayı, ufuk başına tamamlanmış/dışlanan/başarı/yanlış pozitif),
  `n_independent_events == n_events_complete + n_excluded` her ufukta, `n_independent_events <= n_raw`, aynalar `ranking` ile aynı. `historical_catch_up` aynen kalır. Tek hisseli grup: alanlar `None` / `[]`.
- **`calculate_indicators`**: params `include_columns_meta: bool = False`, `value_columns: list[ColumnName] | None = None`; `last_n_rows` varsayılanı **5 → 0** (aralık aynı). Sonuç `columns_meta_included: bool = True`
  (False iken `columns == []`), `invalid_columns_at_as_of: list[ColumnName] | None = None` (`latest.values`'ı `None` olan kolonlar, sıralı; doğrulayıcı `latest` ile tutarlılığı denetler).
  `ColumnName` `schemas/common.py`'e taşındı (`schemas.results.ColumnName` aynı kalır).
- **`check_data_quality` sonucu**: `issue_counts: dict[DQCode, int] | None = None` (hard+soft birlikte; doğrulayıcı listelerle birebir, sıfır girdi yok). `gate_reason` metni değişmedi.
- **`TickerQuality`** yalnızca açıklama düzeltmesi: `n_price_jumps_over_limit` (limit + `PRICE_JUMP_TOLERANCE_PP`, `classify_price_jumps` ile aynı kural), `last_data_age_days` (`as_of`'a kadarki son satıra göre).
- **Doğrulama davranışı (`registry.validate_envelope`) — onaylı (D1):** `schema_version >= 1.2.0` damgalı ve `status=OK` zarflarda yeni alanlar `None` olamaz: rank (>= 2 üyeli grupta) `n_raw_laggard_observations`,
  `cooldown_days`, `outcome_benchmark_definition`, `per_ticker` boş değil; indicators `invalid_columns_at_as_of`; check_data_quality `issue_counts`. 1.1.0 damgalı zarflarda Optional kalır.
- **Yeni yardımcı (D5):** `schemas.registry.max_result_date(results)`: sonuçtaki en geç geçmiş-only tarih (`BundleItem.max_result_date` için; harness `bundle_items` çağırır). `run_backtest` için `last_exit_date`
  (trade_log kısaltılsa bile en geç çıkış) araç yazılırken eklenecek (`docs/schema_wishlist.md` §7).
- **`input_hash` etkisi:** `calculate_indicators` için TÜM hash'ler değişir (iki yeni param + `last_n_rows` varsayılanı); `check_data_quality` için yalnızca boş olmayan `analysis_bundle` (öğeler iki `null` alan kazanır).
  Hash tanımı değişmedi; `schema_version` hash'e girmez.
- `schemas/examples.py`: `example_rank_with_per_ticker(results, subject, ...)` yardımcısı (sentetik rank zarfı kuranlar için: aynalar ranking'ten, özne havuz bloklarını taşır, diğerleri n=0, toplamlar tutarlı); rank örneği 3 satırlı sıralama + `per_ticker` (havuzla toplamı tutar); indicators varsayılan örneği hafif, kolon meta'lı varyant `example_envelope_indicators_full()`; kapı örneğinde `issue_counts`.
