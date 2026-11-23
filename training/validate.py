"""Kayıt doğrulama hattı (training/RULES.md): geçmeyen kayıt eğitim setine ALINMAZ.

Oturum düzeyi: etiket = politika; sayı halüsinasyonu 0 ve KANITSIZ (UNEVIDENCED) sayı 0; eylem koruması ihlali 0; tüm zarflar gerçek v2 ve şema sürümü güncel;
geri çekilme yok; beklenmeyen hata zarfı yok (kurtarma yörüngelerindeki BEKLENEN hatalar hariç); aday etiketlerde not; bağlam sınırı.
Veri kümesi düzeyi: sızıntı yok, bölme boyutları, tek etiket payı <= %80.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from harness.action_guard import check_final_output
from harness import settings
from harness.mock_tools import aux_dataset_versions, is_training_eligible
from harness.number_verifier import verify_session
from schemas.common import SCHEMA_VERSION
from training import spec
from training.teacher import Generated

CANDIDATES = {"POTENTIAL_CATCH_UP_CANDIDATE", "TECHNICAL_REVERSAL_CANDIDATE", "FUNDAMENTAL_IMPROVEMENT_CANDIDATE"}
EXPECTED_ERRORS = {"as_of": "AS_OF_MISMATCH", "malformed": "MALFORMED_TOOL_CALL", "early": "PRECONDITION_FAILED"}


def session_problems(g: Generated) -> list[str]:
    s, res = g.session, g.result
    out: list[str] = []
    final = res.final
    if res.status != "DELIVERED" or final is None:
        return [f"oturum teslim edilmedi: {res.status} {res.abort_reason}"]
    if final.status != "ACCEPTED":
        out.append(f"nihai durum {final.status} (ACCEPTED bekleniyordu)")
    if [e for e in s.events if e["kind"] == "FINAL_FALLBACK"]:
        out.append("güvenli geri çekilme kullanıldı")
    pol = s.policy
    text = s.machine.explanation or ""
    if pol is None or s.machine.action != pol.label:
        out.append(f"etiket politikadan farklı: {s.machine.action} != {pol.label if pol else None}")
    rep = verify_session(s, text)
    if rep.n_hallucinated or rep.n_unevidenced:
        out.append(f"sayı doğrulama: halüsinasyon {rep.n_hallucinated}, kanıtsız {rep.n_unevidenced}: "
                   f"{[r.claim.raw for r in rep.claims if r.verdict in ('HALLUCINATION', 'UNEVIDENCED')][:5]}")
    guard = check_final_output(text, required_action=pol.label if pol else None)
    if not guard.ok:
        out.append(f"eylem koruması: {[(v.code, v.phrase) for v in guard.violations][:4]}")
    for r in s.store.records:
        env = r.envelope
        if not is_training_eligible(env):
            out.append(f"eğitime uygun olmayan zarf: {env['tool']} {env['data_version']} {aux_dataset_versions(env)}")
        if env.get("schema_version") != SCHEMA_VERSION:
            out.append(f"şema sürümü {env.get('schema_version')} != {SCHEMA_VERSION}: {env['tool']}")
        if env["status"] != "OK":
            out.append(f"hata zarfı: {env['tool']} {env.get('error')}")
    for r in s.store.records:               # RULES.md kural 2: relate_to[].split_date = as_of yılının 1 Ocak'ı (ya da sorudaki OOS başlangıcı)
        if r.envelope["tool"] == "get_macro_context":
            for rel in r.envelope["params"].get("relate_to") or []:
                if rel.get("split_date") != f"{g.question.as_of.year}-01-01":
                    out.append(f"relate_to split_date {rel.get('split_date')} != {g.question.as_of.year}-01-01")
    expected = EXPECTED_ERRORS.get(g.recovery or "")
    codes = [e.get("code") for e in s.events if e["kind"] == "INVALID_TOOL_CALL"]
    if codes != ([expected] if expected else []):
        out.append(f"geçersiz çağrılar {codes}, beklenen {[expected] if expected else []}")
    if g.recovery == "final_violation":
        if final.attempt != 2:
            out.append(f"final_violation yörüngesinde deneme {final.attempt} (2 bekleniyordu)")
    elif final.attempt != 1:
        out.append(f"nihai metin {final.attempt}. denemede kabul edildi")
    if pol and pol.label.value in CANDIDATES and not ("örnek küçük" in text and "belirsizlik var" in text):
        out.append("aday etikette 'örnek küçük, belirsizlik var' notu yok")
    if res.messages[-1]["role"] != "assistant":
        out.append("son mesaj asistan değil")
    return out


def too_long(record: dict[str, Any], max_tokens: int | None = None) -> bool:
    return record["tokens"] > (max_tokens or spec.MAX_TOKENS)


def dataset_problems(records: list[dict[str, Any]], questions: list[Any], *, max_label_share: float = 0.80) -> list[str]:
    from training.splits import leakage_problems

    out = list(leakage_problems(questions))
    for split, n in spec.SIZES.items():
        got = sum(1 for r in records if r["split"] == split)
        if got != n:
            out.append(f"{split}: {got} kayıt, hedef {n}")
    if records:
        label, count = Counter(r["label"] for r in records).most_common(1)[0]
        if count / len(records) > max_label_share:
            out.append(f"etiket payı {label} = {count / len(records):.2f} > {max_label_share}")
    ids = Counter(r["id"] for r in records)
    out += [f"yinelenen kimlik {i}" for i, c in ids.items() if c > 1]
    for r in records:
        if r["versions"]["schema"] != SCHEMA_VERSION or any(not v.startswith("snap_") or not v.endswith("_v2") for v in r["versions"]["data"]):
            out.append(f"{r['id']}: sürüm alanları geçersiz {r['versions']}")
        bad_aux = [v for v in r["versions"].get("fundamentals", []) if v not in settings.ACCEPTED_FUNDAMENTALS_VERSIONS]
        if bad_aux:
            out.append(f"{r['id']}: kabul edilmeyen bilanço veri seti sürümü {bad_aux}")
        if r["type"] == "fundamental" and not r["versions"].get("fundamentals"):
            out.append(f"{r['id']}: bilanço oturumunda bilanço veri seti sürümü yok")
        bad_macro = [v for v in r["versions"].get("macro", []) if v not in settings.ACCEPTED_MACRO_VERSIONS]
        if bad_macro:
            out.append(f"{r['id']}: kabul edilmeyen makro veri seti sürümü {bad_macro}")
        if r["type"] == "macro" and not r["versions"].get("macro"):
            out.append(f"{r['id']}: makro oturumunda makro veri seti sürümü yok")
        if len(r["train_mask"]) != len(r["text_messages"]) or not any(r["train_mask"]):
            out.append(f"{r['id']}: kayıp maskesi geçersiz")
    return out


def dumps_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
