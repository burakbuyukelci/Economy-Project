"""Basit olay günlüğü: durum geçişleri, geçersiz araç çağrıları, araç çağrıları.

Bellekte liste tutar; `path` verilirse her olayı JSONL satırı olarak da ekler.
Zaman damgası YOK (determinizm / replay): sıra numarası `seq` yeterlidir.
Kalıcı karar günlüğü (§28) sonraki oturumlarda bunun üzerine kurulacak.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class EventLog:
    def __init__(self, path: Path | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self._path = path

    def append(self, kind: str, **fields: Any) -> dict[str, Any]:
        event = {"seq": len(self.events) + 1, "kind": kind, **fields}
        self.events.append(event)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        return event

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["kind"] == kind]
