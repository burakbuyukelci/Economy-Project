"""Orkestratör: model (LLMBackend) <-> HarnessSession döngüsü. `session.py` model bilmez; model bilgisi yalnızca burada.

Protokol (profil bayraklarından türer, kural mantığı session/final_check'te):
  1. Model araç çağırır (tool_calls); her çağrı `session.call_tool`'dan geçer, sonuç (zarf ya da hata) `tool` mesajı olarak döner.
  2. Araç çağrısız metin = "hazırım". `session.request_explanation()`: reddedilirse eksik adım modele bildirilir, döngü sürer.
  3a. D/E (politika bloğu gösterilir): blok + nihai biçim istemi verilir, model nihai metni yazar (araç yok); ilk metin taslak sayılıp atlanır.
  3b. A–C ve D′ (blok yok): araç çağrısız İLK metin doğrudan nihai metindir.
  4. `session.submit_final`: RETRY ise geri besleme modele gider; ACCEPTED / FALLBACK / RECORDED ise oturum kapanır.
  5. Tur sınırı ya da model hatası: LOOP_ABORTED loglanır; zorlama açık profilde ve açıklama aşaması mümkünse güvenli geri çekilme teslim edilir.
Mesajlar JSON'a çevrilebilir düz sözlüklerdir (replay / eğitim kaydı için `RunResult.messages`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from harness import settings
from harness.llm_backend import LLMBackend, LLMError, ModelReply
from harness.model_view import model_view
from harness.session import FinalResult, HarnessSession
from harness.tool_view import estimate_tokens, model_tool_specs
from schemas.enums import AllowedAction

SYSTEM_PROMPT_VERSION = "3"   # eğitim/çıkarım istem biçimi uyumu için: istem değişince artırılır (2: kısa araç tanımları + OOS kuralı; 3: model_view, null alan = yok)

FINAL_INSTRUCTION = ("Araç çıktılarına dayanarak nihai açıklamayı şimdi yaz. Yalnızca araç çıktılarındaki sayıları kullan, kendin hesaplama yapma; "
                     "yatırım tavsiyesi verme. Son satır tam olarak yukarıdaki EYLEM satırı olmalı.")
TOOLS_CLOSED = "Nihai aşamadasınız: artık araç çağrısı yapılamaz. Yalnızca nihai açıklamayı yazın."


@dataclass
class RunResult:
    session: HarnessSession
    final: FinalResult | None            # teslim edilen sonuç (ABORTED ve geri çekilme yoksa None)
    messages: list[dict[str, Any]]
    status: str                          # "DELIVERED" | "ABORTED"
    abort_reason: str | None = None      # "TURN_LIMIT" | "MODEL_ERROR"
    n_model_turns: int = 0


# =============================== istem ve araç tanımları ===============================
def build_system_prompt(session: HarnessSession) -> str:
    labels = ", ".join(a.value for a in AllowedAction)
    parts = [
        "Sen BIST 100 hisseleri için finansal analiz yorumcususun. Hesaplamayı Python araçları yapar; sen yalnızca elindeki bilgiye dayanarak yorumlar ve açıklarsın.",
        "KURALLAR:\n"
        "1. Sayılar yalnızca araç çıktısından gelir; elinde olmayan sayıyı yazma, kendin hesaplama (oran, fark, yüzde türetme) yapma.\n"
        "2. Yatırım tavsiyesi, al/sat emri, hedef fiyat ve kesinlik ifadeleri (\"kesin yükselir\", garanti) yasaktır. Doğrulanmamış bir iddiayı tırnak içinde "
        "alıntılayıp doğrulanmadığını söyle.\n"
        "3. Analiz tarihinden (as_of) sonrasına ait bilgi kullanma.\n"
        "4. Eksik veri, az olay, örneklem dışı bozulma ve çoklu test riskini açıkça belirt; nedensellik iddiası kurma.\n"
        "5. Araç çıktısında bulunmayan alan boş (null) demektir. `view_trimmed` varsa o bölümler bağlam için kısaltılmıştır; kısaltılan sayıları yazma.",
        f"NİHAİ ÇIKTI: açıklamanın son satırı tam olarak `EYLEM: <ETİKET>` olmalı. İzinli etiketler: {labels}.",
    ]
    if session.visible_tools:
        tools = ("ARAÇ KULLANIMI: gerekli araçları doğru parametrelerle çağır; her çağrıda as_of = sorudaki analiz tarihi "
                 f"({session.as_of.isoformat()}). Belirtmediğin parametreler varsayılanlarla çalışır. Örneklem dışı doğrulama için split_date / "
                 "out_of_sample_start ver (as_of yılının 1 Ocak'ı ya da sorudaki başlangıç; run_backtest'te strategy.train_end bir gün öncesi): "
                 "verilmezse analiz INVESTIGATE kalır.")
        if session.profile.show_policy_label:
            tools += (" Araçlarla işin bitince araç çağırmadan `HAZIR` yaz; ardından harness sana politika kararını ve gerekçelerini "
                      "verip nihai açıklamayı isteyecek.")
        else:
            tools += " Araçlarla işin bitince araç çağırmadan nihai açıklamayı yaz."
        parts.insert(2, tools)
    return "\n\n".join(parts)


def tool_specs(session: HarnessSession) -> list[dict[str, Any]]:
    """MODELE gösterilen araçlar (MCP'den bağımsız yalın biçim); profilin gizlediği harness-içi araçlar yoktur."""
    return model_tool_specs(session.visible_tools)


# =============================== döngü ===============================
def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def run_session(question: str, backend: LLMBackend, *, profile: str | None = None, max_turns: int | None = None,
                session: HarnessSession | None = None, **session_kwargs: Any) -> RunResult:
    """Bir soru için tam oturum: araç döngüsü -> nihai metin -> denetim/yeniden deneme -> kapanış."""
    if session is None:
        session = HarnessSession.from_question(question, profile=profile, **session_kwargs)
    limit = settings.AGENT_MAX_TURNS if max_turns is None else max_turns
    specs = tool_specs(session)
    messages: list[dict[str, Any]] = [{"role": "system", "content": build_system_prompt(session)},
                                      {"role": "user", "content": question}]
    turns = 0
    final: FinalResult | None = None
    final_phase = False
    try:
        while turns < limit:
            turns += 1
            offered = None if (final_phase or not specs) else specs
            reply: ModelReply = backend.chat(messages, offered)
            # bağlam ölçümü: karakter/3 tahmini ile Ollama'nın gerçek prompt_eval_count'u (varsa) yan yana (hedef ≤ 8192 token)
            session.log.append("MODEL_TURN", turn=turns, estimated_prompt_tokens=estimate_tokens(messages=messages, tools=offered),
                               prompt_tokens=reply.prompt_tokens, completion_tokens=reply.completion_tokens,
                               n_tool_calls=len(reply.tool_calls))
            if reply.has_tool_calls:
                if final_phase:
                    messages += [_assistant(reply), {"role": "user", "content": TOOLS_CLOSED}]
                    continue
                messages.append(_assistant(reply))
                for tc in reply.tool_calls:
                    result = session.call_tool(tc.name, dict(tc.arguments))
                    payload = (model_view(result.envelope, subject=_subject(session)) if result.ok else result.error)
                    messages.append({"role": "tool", "name": tc.name, "content": _dump(payload)})
                continue
            text = reply.text
            if not final_phase:
                decision = session.request_explanation()
                if not decision.allowed:
                    messages += [{"role": "assistant", "content": text},
                                 {"role": "user", "content": f"Açıklama aşamasına geçilemedi ({decision.code}): {decision.message}. "
                                                              "Eksik adımları araç çağrılarıyla tamamlayın."}]
                    continue
                final_phase = True
                context = session.explanation_context()
                if context:                     # D/E: önce blok, sonra nihai metin; ilk metin taslaktı
                    messages += [{"role": "assistant", "content": text},
                                 {"role": "user", "content": f"{context}\n\n{FINAL_INSTRUCTION}"}]
                    continue
            outcome = session.submit_final(text)
            messages.append({"role": "assistant", "content": text})
            if outcome.status == "RETRY":
                messages.append({"role": "user", "content": outcome.feedback or ""})
                continue
            final = outcome
            break
        else:
            return _abort(session, messages, turns, "TURN_LIMIT", f"{limit} tur içinde nihai metin teslim edilmedi")
    except LLMError as exc:
        return _abort(session, messages, turns, "MODEL_ERROR", str(exc))
    session.close()
    return RunResult(session, final, messages, "DELIVERED", None, turns)


def _subject(session: HarnessSession) -> str | None:
    """Etiket politikasıyla aynı özne kuralı: soruda TEK hisse varsa o (aksi halde sıralamadaki en çok geride kalan; model_view bulur)."""
    return session.question_tickers[0] if len(session.question_tickers) == 1 else None


def _assistant(reply: ModelReply) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": reply.text}
    if reply.tool_calls:
        msg["tool_calls"] = [{"function": {"name": tc.name, "arguments": dict(tc.arguments)}} for tc in reply.tool_calls]
    return msg


def _abort(session: HarnessSession, messages: list[dict[str, Any]], turns: int, reason: str, message: str) -> RunResult:
    session.log.append("LOOP_ABORTED", reason=reason, message=message, turns=turns)
    final: FinalResult | None = None
    # geri çekilme yalnızca zorlama açıksa ve açıklama aşaması mümkünse (peek: geçersiz çağrı sayacını şişirmez)
    if session.profile.enforce_final_check and session.machine.peek_explanation().allowed:
        if session.request_explanation().allowed:
            final = session.deliver_fallback(reason)
            session.close()
    return RunResult(session, final, messages, "ABORTED", reason, turns)
