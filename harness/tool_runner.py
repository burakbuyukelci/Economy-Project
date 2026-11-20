"""Araç çağrısını ayarlara göre mock'a ya da gerçek araca yönlendirir.

Gerçek araç: `tools/<araç_adı>.py` içinde `run(params: dict) -> dict` (importlib ile geç yüklenir;
modül henüz yoksa yalnızca o araç çağrıldığında hata verir).
"""
from __future__ import annotations

import importlib
from typing import Any

from harness import settings
from harness.mock_tools import run_mock_tool
from schemas.enums import ToolName


_import_module = importlib.import_module  # testlerde değiştirilebilsin diye ayrı ad


class RealToolUnavailable(RuntimeError):
    """Backend 'real' seçildi ama modül/fonksiyon bulunamadı."""


class ToolRejected(Exception):
    """Gerçek araç çağrıyı reddetti (sözleşme: yalnızca as_of yok/bozuksa tools.common.InvalidToolCall).

    Oturum bunu 'geçersiz araç çağrısı' olarak loglar; durum ilerlemez. Diğer hatalar (UNKNOWN_TICKER,
    NO_DATA, INVALID_PARAMS) zaten status=ERROR zarfıyla döner ve istisna OLUŞTURMAZ.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def run_tool(tool: ToolName | str, params: dict[str, Any]) -> dict[str, Any]:
    tool = ToolName(tool)
    if settings.backend_for(tool) == "mock":
        return run_mock_tool(tool, params)

    module_name = settings.REAL_TOOL_MODULE_TEMPLATE.format(tool=tool.value)
    try:
        module = _import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:  # modülün KENDİ içindeki eksik bağımlılık gerçek bir hatadır, gizleme
            raise
        raise RealToolUnavailable(f"{tool.value}: {module_name} bulunamadı") from exc
    entry = getattr(module, settings.REAL_TOOL_ENTRYPOINT, None)
    if entry is None:
        raise RealToolUnavailable(f"{module_name}.{settings.REAL_TOOL_ENTRYPOINT} tanımlı değil")
    from tools.common import InvalidToolCall  # araç modülü zaten yüklü; sınıfı gerçek kaynağından al

    try:
        return entry(params)
    except InvalidToolCall as exc:
        raise ToolRejected("AS_OF_INVALID", str(exc)) from exc
