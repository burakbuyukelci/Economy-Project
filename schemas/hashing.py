"""input_hash tanımı (SÖZLEŞME): sha256( kanonik JSON {tool, params, data_version} ).

  * params, şema modeliyle doğrulanıp normalize edilmiş hâliyle (varsayılanlar açık, listeler
    sıralı-tekil) `model_dump(mode="json")` olarak hash'lenir.
  * Anahtarlar sıralı, boşluksuz, ensure_ascii=False, UTF-8.
  * data_version dahil: veri değişirse hash değişir (kanıt bütünlüğü).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_input_hash(tool: str, params: dict[str, Any], data_version: str) -> str:
    blob = json.dumps(
        {"tool": str(getattr(tool, "value", tool)), "params": params, "data_version": data_version},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
