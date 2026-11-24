"""experiments/chat.py: soru okuma ve döngü; her soru ask.main'e gider (model yerine öğretmen betiği)."""
from __future__ import annotations

from experiments import chat


def _feeder(lines):
    it = iter(lines)

    def f(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return f


def test_single_line_question_runs_immediately():
    assert chat.read_question(_feeder(["THYAO nasıl?", "bu okunmaz"])) == "THYAO nasıl?"


def test_quit_and_eof_return_none():
    assert chat.read_question(_feeder(["q"])) is None
    assert chat.read_question(_feeder([])) is None


def test_leading_blank_lines_ignored_and_multiline_with_backslash():
    assert chat.read_question(_feeder(["", "", "ilk satır \\", "ikinci", ""])) == "ilk satır \\\nikinci"


def test_loop_calls_ask_per_question_and_records(tmp_path, monkeypatch):
    calls = []

    def fake_main(argv, backend_factory=None):
        calls.append(argv)
        return 0
    monkeypatch.setattr(chat.ask, "main", fake_main)
    code = chat.main(["--model", "m", "--as-of", "2026-09-10", "--out", str(tmp_path)], input_fn=_feeder(["soru bir", "soru iki", "q"]))
    assert code == 0 and len(calls) == 2
    a = calls[0]
    assert a[a.index("--question") + 1] == "soru bir" and a[a.index("--as-of") + 1] == "2026-09-10" and a[a.index("--model") + 1] == "m"
    assert a[a.index("--record") + 1].endswith("001.json") and calls[1][calls[1].index("--record") + 1].endswith("002.json")
