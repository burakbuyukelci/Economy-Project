"""Karar kaydı (decision log, proje dokümanı §28): bir oturumun yeniden oynatılabilir TAM kaydı.

Kayıt: soru metni (modelin gördüğü), analiz tarihi, profil, model adı, TÜM mesajlar (sistem istemi, model yanıtları, araç yanıtları), özet (araç `input_hash` sırası, nihai metin,
etiket, politika kuralı, kanıt `lock_hash`, sayı denetimi), committed kanıt kümesi, veri seti sürümleri ve (varsa) insan incelemesi. `experiments.replay` bu kaydı okuyup oturumu
yeniden koşturur ve özetin birebir aynı çıktığını doğrular (tekrarlanabilirlik: aynı girdi → aynı çıktı).
"""
from __future__ import annotations

from typing import Any

from harness.mock_tools import aux_dataset_versions
from harness.routing import ReviewStatus, State
from harness.session import HarnessSession

FORMAT = 1


def summary_of(session: HarnessSession) -> dict[str, Any]:
    """Karşılaştırılan çekirdek özet (replay bunun aynı çıkmasını bekler)."""
    ev = session.events
    pol = session.policy
    delivered = session.final_metrics()["delivered_level"]
    return {
        "tool_hashes": [e["input_hash"] for e in ev if e["kind"] == "TOOL_CALL" and e.get("status") == "OK"],
        "tool_names": [e["tool"] for e in ev if e["kind"] == "TOOL_CALL" and e.get("status") == "OK"],
        "final_text": session.machine.explanation,
        "action": delivered.get("action"),
        "policy_label": pol.label.value if pol else None,
        "rule_id": pol.rule_id if pol else None,
        "lock_hash": next((e["lock_hash"] for e in ev if e["kind"] == "EVIDENCE_LOCKED"), None),
        "n_number_claims": delivered.get("n_number_claims"),
        "n_hallucinated": delivered.get("n_hallucinated"),
        "n_unevidenced": delivered.get("n_unevidenced"),
        "n_invalid_calls": session.machine.n_invalid_calls,
    }


def build_record(session: HarnessSession, messages: list[dict[str, Any]], *, question: str, model: str, review: dict[str, str] | None = None) -> dict[str, Any]:
    envs = [r.envelope for r in session.store.records]
    snap = session.evidence_snapshot()
    aux = sorted({v for e in envs for v in aux_dataset_versions(e)})
    return {
        "format": FORMAT, "question": question, "as_of": session.as_of.isoformat(), "as_of_source": session.as_of_source,
        "profile": session.profile.name, "model": model, "messages": messages, "summary": summary_of(session),
        "committed_evidence": snap["committed_evidence_set"] if snap else [],
        "data_versions": {"price": sorted({e["data_version"] for e in envs}), "fundamentals": [v for v in aux if v.startswith("fundamentals_")],
                          "macro": [v for v in aux if v.startswith("macro_")]},
        "review": review,
    }


def compare(recorded: dict[str, Any], replayed: dict[str, Any]) -> list[str]:
    """Alan alan karşılaştırma; farklı olanların adı ve kısa değerleri."""
    diffs = []
    for k in recorded:
        if recorded[k] != replayed.get(k):
            a, b = str(recorded[k])[:90], str(replayed.get(k))[:90]
            diffs.append(f"{k}: kayıt={a} | oynatma={b}")
    return diffs


def attach_review(session: HarnessSession, review: dict[str, str] | None) -> None:
    """İnsan incelemesini oturum KAPANMADAN hemen önce kaydeder (`run_session` teslimden sonra `close()` çağırır; kapandıktan sonra inceleme reddedilir).
    `close` yalnızca bu oturum için sarılır; durum makinesi kuralları değişmez (inceleme yalnızca HUMAN_REVIEW durumunda ve profil E gibi inceleme açıkken kaydedilir)."""
    if not review:
        return
    original = session.close

    def close_with_review() -> None:
        if session.profile.human_review and session.machine.state == State.HUMAN_REVIEW and session.machine.explanation:
            session.record_human_review(ReviewStatus(review["decision"]), review["reviewer"], review["reason"])
        original()

    session.close = close_with_review  # type: ignore[method-assign]
