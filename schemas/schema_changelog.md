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
