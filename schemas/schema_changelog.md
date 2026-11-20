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
