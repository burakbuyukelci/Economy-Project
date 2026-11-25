"""Basit olay günlüğü: durum geçişleri, geçersiz araç çağrıları, araç çağrıları.

Bellekte liste tutar; `path` verilirse her olayı JSONL satırı olarak da ekler.
Varsayılanda zaman damgası YOK (determinizm / replay): sıra numarası `seq` yeterlidir. `timestamps=True` (canlı `ask --trace`) her olaya UTC `ts` ekler;
bu yalnızca iz kaydı içindir, kanıt hash'lerine ve replay özetine girmez.
Kalıcı karar günlüğü (§28) sonraki oturumlarda bunun üzerine kurulacak.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventLog:
    def __init__(self, path: Path | None = None, *, timestamps: bool = False) -> None:
        self.events: list[dict[str, Any]] = []
        self._path = path
        self._timestamps = timestamps

    def append(self, kind: str, **fields: Any) -> dict[str, Any]:
        event = {"seq": len(self.events) + 1, "kind": kind, **fields}
        if self._timestamps:
            event["ts"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self.events.append(event)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        return event

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["kind"] == kind]
