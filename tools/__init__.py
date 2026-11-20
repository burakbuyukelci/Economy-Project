"""Deterministik araçlar (BİLGİSAYAR 1). Ağ kullanmaz; yalnızca data/snapshots okur.

ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ (harness bunu çağırır; tests/contract/test_tool_entrypoint.py denetler):

    tools/<tool_name>.py  ->  run(params: dict) -> dict

  * Modül adı = schemas.enums.ToolName değeri (ör. tools/get_stock_history.py).
  * `run` TEK parametre alır (`params`); dönüş, schemas.envelope.ToolEnvelope'a uyan düz, JSON'a
    çevrilebilir bir `dict`'tir. Girdi sözlüğünü değiştirmez.
  * Hatalar zarfla bildirilir (status="ERROR", error={code, message}): UNKNOWN_TICKER, NO_DATA, INVALID_PARAMS.
    Tek istisna: `as_of` yok/geçersizse zarf kurulamaz ve tools.common.InvalidToolCall fırlatılır
    (harness bunu "geçersiz araç çağrısı" sayar).
  * Test/çevrimdışı çalıştırma için ayrıca `run_on(params, *, snapshot_root, data_version)` bulunabilir;
    bu sözleşmenin parçası değildir, harness kullanmamalıdır.
"""
