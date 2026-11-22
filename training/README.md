# v2 eğitim hattı: veri → Colab QLoRA → GGUF → Ollama → değerlendirme

> **v2 (üreteç sürümü 2):** v1'e ek olarak **bilanço oturumları (Soru 4)**: `get_fundamental_metrics` + `calculate_fundamental_change`, F1–F4 etiketleri, 600/50/100 oturum. Makro (Soru 5) oturumları YOK: makro snapshot'ı main'de yok (gelince artımlı v2.1). Bilanço veri seti sürümü `fundamentals_2026-11-23_v1` (kabul listesi: `harness/settings.py`); kapsam sınırı ve etiket dağılımı: `docs/harness_design.md` §14.4. v1 verisi ve v1 modeli ile v2 KARIŞTIRILMAZ.

Model: **Gemma 3 4B** (`unsloth/gemma-3-4b-it`), 4-bit QLoRA, T4 16 GB, sequence length **≤ 8192** (batch 1 + gradient accumulation; OOM geri dönüşü aşağıda). Araç çağırma **metin protokolüyle** (Gemma 3'ün Ollama'da yerel araç desteği yok;
`docs/harness_design.md` 13.4). Kural dosyası: `training/RULES.md` (v1'e uygulandı: yalnızca gerçek v2 araç çıktıları, şema 1.3.0, etiket politikadan, sayılar yalnızca kilitli kanıttan).

Bu bilgisayarlar arasında iş bölümü: **veri üretimi ve testler Bilgisayar 2'de** (kod), **eğitim Colab'da**, **GGUF/Ollama ve model testleri Bilgisayar 1'de**.

## 0. Gereksinimler (Bilgisayar 1)
* Depo + `.venv` + `data/snapshots/` (v2). `git pull --rebase`, `pytest` yeşil.
* Ollama kurulu (yalnızca yerel; `HARNESS_OLLAMA_HOST` varsayılanı `http://127.0.0.1:11434`).
* Colab hesabı (T4 yeter). Eğitim yaklaşık 1–2 saat.

## 1. Veriyi üret (tek komut, belirlenimli)
```
python -m training.build_dataset --out data/training/v2
```
* Çıktı: `data/training/v2/{train,val,test}.jsonl`, `report.json` (dağılımlar, elenenler), `manifest.json`. **Dosyalar commit edilmez** (`.gitignore`); aynı tohumla yeniden üretilir.
* Boyut hedefi: eğitim 600, doğrulama 50, test 100 oturum. Bağlam sınırını (8192 token) aşan oturumlar elenir; `report.json > too_long_rate_by_type` elenme oranını tip bazında verir (hedef < %5), eksikler `shortfall` içindedir.
* **DUR koşulu:** tek etiket payı > %80 ise komut çıkış kodu 2 verir. `report.json > overall_labels` ve `top_label_share`'e bakın.
* Gerçek Gemma tokenizer ile sayım için (önerilir; yoksa karakter tahmini kullanılır):
  `curl -L -o training/.cache/tokenizer.json https://huggingface.co/unsloth/gemma-3-4b-it/resolve/main/tokenizer.json` ve `pip install tokenizers`.
* Kayıt biçimi: her satır `messages` (yapısal), `text_messages` (**modele giden metnin birebir aynısı**: sistem + araç bloğu, soru, `<tool_call>`/`<tool_response>`…), `train_mask`
  (yalnızca asistan turları), `label`, `rule_id`, `versions`, `tokens`. **Maskeli turlar:** hata-kurtarma yörüngelerindeki (≈%10) HATALI asistan turu bağlamda kalır ama kayıpta DEĞİLDİR.

## 2. Colab paketini hazırla
```
python -m training.colab.make_bundle --data data/training/v2 --out colab_bundle.zip
```
`colab_bundle.zip` = eğitim kodu + `train.jsonl` + `val.jsonl`.

## 3. Colab'da eğit
1. colab.research.google.com → *Dosya → Not defteri yükle* → `training/colab/train_qlora.ipynb`.
2. *Çalışma zamanı → Çalışma zamanı türünü değiştir → T4 GPU*.
3. Hücreleri sırayla çalıştırın: GPU kontrolü → `pip install unsloth` → `colab_bundle.zip` yükle → **kuru çalıştırma** (`--dry-run`: kaç örnek ≤ 8192 token, eğitilen token payı; GPU/model gerekmez) → eğitim → `result.zip` indir.
4. Eğitim komutu (not defterindekiyle aynı): `python training/colab/train_qlora.py --train train.jsonl --val val.jsonl --out outputs/v1 --epochs 2 --gguf q4_k_m`.
   Varsayılanlar: LoRA r=16, lr 2e-4, batch 1 × grad-accum 8, adamw_8bit, her 25 adımda doğrulama kaybı. **Kayıp yalnızca asistan turlarında** (`training/colab/data.py`).
5. Çıktılar: `outputs/v1/adapter/` (LoRA), `outputs/v1/gguf/*.gguf` (Q4_K_M), `data_stats.json` (kaç örnek elendi, token payları), `train_result.json`.

**Sorun giderme**
| Belirti | Çözüm |
|---|---|
| CUDA OOM (8192'de T4 16 GB) | **Geri dönüş (6144 + ek kırpma):** veriyi `python -m training.build_dataset --out data/training/v2_6k --max-tokens 6144 --tight` ile yeniden üretin (model görünümü SIKI MOD: ufuk blokları yalnızca kanıtın seçtiği ufuklarla), Colab'da `--max-seq 6144`, Modelfile `num_ctx 6144` ve canlıda `HARNESS_VIEW_TIGHT=1`. Önce hafif önlem: `--grad-accum 16`, "Runtime → Restart". |
| `SFTConfig` hatası | Betik `max_seq_length` / `max_length` adından hangisinin geçerli olduğunu `inspect.signature` ile saptar ve çıktıda yazar (`SFTConfig dizi uzunluğu alanı: ...`); ikisi de yoksa açık hata verir: `pip install -q "trl<0.20"` ya da Unsloth'u güncelleyin. |
| `save_pretrained_gguf` hatası (argüman adı `quantization_method`/`quantization_type` inspect ile seçilir; ikisi de yoksa açık hata) | Elle: `model.save_pretrained_merged("merged", tokenizer, save_method="merged_16bit")`, sonra `llama.cpp/convert_hf_to_gguf.py merged --outtype f16` ve `llama-quantize ...f16.gguf gemma3-bist-q4_k_m.gguf Q4_K_M`. |
| Eğitim kaybı düşmüyor | `data_stats.json > train_token_share` çok küçükse (< %3) maske hatası olabilir: `pytest tests/training/test_colab_data.py`. |
| Hepsi elendi (`eğitim örneği kalmadı`) | `--max-seq 8192` ve tokenizer: kayıtlar `tokens` alanıyla önceden süzülmüştür; farklı model/tokenizer kullandıysanız sayılar değişir. |

**Kesilebilir eğitim.** Colab T4'te Gemma 3 float32 eğitilir (~153 sn/adım; 75 adımlık 1 epoch ~3,2 saat; GPU seçimine bağlı). `--save-steps 5 --checkpoint-dir /content/drive/MyDrive/bist_ckpt --resume` kontrol noktalarını Drive'a yazar ve oturum düşünce kaldığı yerden devam eder;
`--max-steps K` epoch yerine K adımda durur (adaptör yine kaydedilir). Not defteri bu bayraklarla gelir.

## 4. Ollama'ya al (Bilgisayar 1)
1. `result.zip`'i açın; GGUF'u `training/ollama/gemma3-bist-q4_k_m.gguf` olarak kaydedin.
2. `ollama create gemma3-bist -f training/ollama/Modelfile` — `Modelfile` kendi sohbet şablonumuzu içerir (eğitim metniyle aynı: `<start_of_turn>user|model`; `system` rolü yok, harness sistem metnini ilk user mesajına ekler; `<bos>` şablonda YOK).
3. **Şablon doğrulaması (zorunlu):** `python -m experiments.check_template --model gemma3-bist --records data/training/v2/val.jsonl --n 5`
   `OK` satırları: Modelfile şablonu eğitim metniyle aynı token sayısını veriyor. `FARK` varsa `TEMPLATE`'i düzeltin (fazla satır sonu, çift BOS, system rolü).
4. Harness modeli: `set HARNESS_MODEL=gemma3-bist` (PowerShell: `$env:HARNESS_MODEL="gemma3-bist"`); araç modu varsayılan `text`.
5. Bağlam: ilk gerçek koşuda `MODEL_TURN` olaylarındaki `prompt_tokens` (Ollama `prompt_eval_count`) ile `estimated_prompt_tokens`'ı karşılaştırın; sayılar ≤ 8192 olmalıdır (üretim payı için pratikte ≤ ~7500).

## 5. Değerlendirme (A–E x temel/ince ayarlı) — Colab GPU'da (`experiments/colab/eval_ollama.ipynb`, paket: `python -m experiments.colab.make_eval_bundle`; ayrıntı `docs/harness_design.md` §14.5)
```
python -m experiments.eval_runner --questions data/training/v2/test.jsonl --n 40 --models gemma3:4b gemma3-bist --out reports/eval_v2   # kesilirse aynı komut kaldığı yerden devam eder (--max-runs R ile bölünür)
```
* `reports/eval_v1/results.csv` (soru x profil x model x tekrar) ve `summary.json` (model|profil başına: sayısal halüsinasyon oranı, geçersiz araç çağrısı oranı, kanıtsız sayı oranı,
  kural ihlali oranı (teslim ve deneme düzeyi), tavsiye dili, geri çekilme, zorunlu adım atlama, etiket uyumu, tekrarlanabilirlik, bağlam).
* `--profiles A B` ile alt küme, `--repeats 2` ile tekrarlanabilirlik, `--n` ile soru sayısı. Temel model: `gemma3:4b` (önce `ollama pull gemma3:4b`).
* Colab'da da çalışır (yalnızca pydantic, pandas, numpy, pyarrow + `data/snapshots/` + Ollama); `experiments/requirements.txt`.
* Hocanın metrikleri ve bu çıktıların eşlemesi: `docs/harness_design.md` bölüm 14.

## 6. Veriyi yeniden üretme / genişletme
* Aynı komut aynı veriyi üretir (`--seed 42`). Sürüm değişince (`GENERATOR_VERSION`, `SYSTEM_PROMPT_VERSION`, `TEXT_PROTOCOL_VERSION`, şema) veriyi YENİDEN üretin; eski kayıtlar karıştırılmaz.
* Yeni araç (makro, haber) gerçek olunca (bilanço v2'de eklendi): `harness/settings.py` / `training/spec.py REAL_TOOLS`, `training/questions.py` (şablon + `BUILDERS`), `training/teacher.py plan_calls`,
  `training/composer.py` (kanıt seçimi), `spec.TYPE_SHARES`; mevcut tiplerin soruları değişmez.
