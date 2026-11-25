"""experiments/build_submission.py: bilgi tabanı ve manifest yardımcıları (ağır paketleme olmadan)."""
from __future__ import annotations

from experiments import build_submission as bs


def test_chunks_split_on_headings_and_keep_path():
    text = "# A\nintro\n## B\nbody b\n### C\nbody c\n## D\nbody d"
    got = dict(bs._chunks(text))
    assert got["A"] == "intro" and got["A > B"] == "body b" and got["A > B > C"] == "body c" and got["A > D"] == "body d"


def test_long_section_is_split_on_paragraph_boundaries():
    para = "x" * 2000
    parts = bs._chunks("# T\n" + "\n\n".join([para] * 3))
    # iki paragraf 3500 sınırını aşar (4000) -> her paragraf ayrı parça
    assert len(parts) == 3 and all(len(p[1]) <= 2000 for p in parts) and "(bölüm 1/3)" in parts[0][0]


def test_knowledge_base_has_sources_and_states_no_runtime_retrieval():
    kb = bs.build_knowledge_base()
    assert kb["runtime_retrieval"] is False and kb["n_documents"] > 50 and kb["sources"]
    d = kb["documents"][0]
    assert d["id"] and d["text"] and len(d["source"]["file_sha256"]) == 64 and d["source"]["file"].startswith("docs/")
    assert len({x["id"] for x in kb["documents"]}) == kb["n_documents"]          # kimlikler benzersiz
    assert kb == bs.build_knowledge_base()                                          # belirlenimli


def test_model_info_adapter_hash_is_a_sha256():
    import json
    info = json.loads((bs.ROOT / "training" / "model_info.json").read_text(encoding="utf-8"))
    assert len(info["adapter"]["sha256"]) == 64 and len(info["local_runtime_artifact"]["sha256"]) == 64
