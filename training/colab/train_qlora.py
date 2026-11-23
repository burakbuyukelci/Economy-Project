"""Colab (T4 16 GB) QLoRA eğitimi: unsloth/gemma-3-4b-it, 4-bit, seq len <= 8192 (batch 1 + gradient accumulation; OOM ise README geri dönüşü).

Girdi: `train.jsonl` / `val.jsonl` (python -m training.build_dataset çıktısı). Her kayıt `text_messages` (çıkarımdaki metnin BİREBİR aynısı) + `train_mask` taşır.
KAYIP: yalnızca asistan turları (araç çağrıları + nihai metin) ve `<end_of_turn>`; system, soru, politika bloğu, geri bildirim, araç çıktıları ve MASKELİ hatalı
asistan turları -100 (bağlamda kalır). Maskeleme mantığı `training/colab/data.py`'de (yerelde testli; torch gerektirmez).

Kullanım (Colab hücresinde; ayrıntı training/README.md):
    python train_qlora.py --train train.jsonl --val val.jsonl --out outputs/v1                # eğitim + adaptör kaydı
    python train_qlora.py --train train.jsonl --val val.jsonl --dry-run                       # yalnızca tokenizasyon istatistiği (GPU gerekmez)
    python train_qlora.py --train train.jsonl --val val.jsonl --out outputs/v1 --gguf q4_k_m  # eğitim sonrası GGUF (Ollama)

KESİLEBİLİR EĞİTİM (Colab oturumu düşebilir; float32 T4'te adım başına ~153 sn ölçüldü): `--save-steps N` her N adımda kontrol noktası yazar (`--checkpoint-dir` ile Drive gibi
kalıcı bir klasöre), `--resume` en son TAMAMLANMIŞ kontrol noktasından devam eder (yoksa sıfırdan başlar ve söyler), `--max-steps K` epoch yerine K adımda durur
(adaptör yine kaydedilir; sonra `--resume` ve daha büyük `--max-steps` ile sürdürülür). Çıktılar `--out` klasörüne yazılır.
    python train_qlora.py --train train.jsonl --val val.jsonl --out /content/drive/MyDrive/bist/v2 --save-steps 5 --resume
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))   # repo kökü (harness.text_protocol, training.colab.data); Colab paketinde de aynı düzen

from training.colab.compat import bf16_native, first_supported, latest_checkpoint  # noqa: E402
from training.colab.data import IGNORE, build_examples, load_jsonl  # noqa: E402

DEFAULT_MODEL = "unsloth/gemma-3-4b-it"


def text_tokenizer(tokenizer):
    """Gemma 3 `FastModel` bir işlemci (processor) döndürebilir; metin tokenizer'ı `.tokenizer` altındadır."""
    return getattr(tokenizer, "tokenizer", tokenizer)


def make_encoder(tokenizer):
    tok = text_tokenizer(tokenizer)
    return lambda text: tok(text, add_special_tokens=False)["input_ids"]


class PadCollator:
    """Değişken uzunluklu örnekleri doldurur: input_ids -> pad, labels -> -100, attention_mask -> 0."""

    def __init__(self, pad_id: int) -> None:
        self.pad_id = pad_id

    def __call__(self, batch):
        import torch

        n = max(len(b["input_ids"]) for b in batch)
        ids = torch.full((len(batch), n), self.pad_id, dtype=torch.long)
        lab = torch.full((len(batch), n), IGNORE, dtype=torch.long)
        att = torch.zeros((len(batch), n), dtype=torch.long)
        for i, b in enumerate(batch):
            k = len(b["input_ids"])
            ids[i, :k] = torch.tensor(b["input_ids"])
            lab[i, :k] = torch.tensor(b["labels"])
            att[i, :k] = torch.tensor(b["attention_mask"])
        return {"input_ids": ids, "labels": lab, "attention_mask": att}


def schedule_kwargs(args: argparse.Namespace, out: Path) -> dict:
    """Kesilebilir eğitim ayarları (SFTConfig alanları): `max_steps` (>0 ise epoch'u ezer), kontrol noktası sıklığı/klasörü. Saf; torch gerektirmez, testli."""
    ckpt_dir = Path(args.checkpoint_dir) if args.checkpoint_dir else out / "checkpoints"
    kw: dict = {"output_dir": str(ckpt_dir), "max_steps": args.max_steps}
    if args.save_steps and args.save_steps > 0:
        kw.update(save_strategy="steps", save_steps=args.save_steps, save_total_limit=args.save_total_limit)
    else:
        kw.update(save_strategy="no")
    return kw


def report(name: str, stats: dict) -> None:
    print(f"[{name}] kayıt {stats['n_in']} -> kullanılan {stats['n_kept']} (bağlam > {stats['max_len']} nedeniyle elenen {stats['n_dropped_long']}); "
          f"ortalama {stats['mean_len']} / en uzun {stats['longest']} token; eğitilen token payı {stats['train_token_share']:.1%}")
    if stats["n_dropped_long"]:
        print(f"    elenen örnek kimlikleri (ilk 20): {stats['dropped_ids']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gemma 3 4B QLoRA (Unsloth)")
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-seq", type=int, default=8192)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--eval-steps", type=int, default=25)
    ap.add_argument("--seed", type=int, default=3407)
    ap.add_argument("--out", default="outputs/v1", help="adaptör, GGUF ve istatistiklerin yazılacağı klasör (Drive yolu olabilir)")
    ap.add_argument("--max-steps", type=int, default=-1, help="> 0 ise epoch yerine bu kadar optimizer adımı (kısa/kesik koşular)")
    ap.add_argument("--save-steps", type=int, default=0, help="> 0 ise her N adımda kontrol noktası yaz (resume için)")
    ap.add_argument("--save-total-limit", type=int, default=2, help="diskte tutulacak en çok kontrol noktası")
    ap.add_argument("--checkpoint-dir", default=None, help="kontrol noktası klasörü (varsayılan: <out>/checkpoints); kalıcı bir klasör verin")
    ap.add_argument("--resume", action="store_true", help="kontrol noktası klasöründeki en son tamamlanmış kontrol noktasından devam et")
    ap.add_argument("--gguf", default=None, help="eğitim sonrası GGUF niceleme yöntemi (örn. q4_k_m)")
    ap.add_argument("--dry-run", action="store_true", help="yalnızca tokenizasyon/maske istatistiği; model yüklenmez")
    args = ap.parse_args(argv)

    train_recs, val_recs = load_jsonl(args.train), load_jsonl(args.val)
    if args.dry_run:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(args.model)
        model = None
    else:
        from unsloth import FastModel  # noqa: F401  (unsloth, transformers/trl'den ÖNCE içe aktarılmalı)

        model, tokenizer = FastModel.from_pretrained(model_name=args.model, max_seq_length=args.max_seq, load_in_4bit=True, load_in_8bit=False,
                                                     full_finetuning=False)
    encode = make_encoder(tokenizer)
    train_ex, tstats = build_examples(train_recs, encode, args.max_seq)
    val_ex, vstats = build_examples(val_recs, encode, args.max_seq)
    report("train", tstats)
    report("val", vstats)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "data_stats.json").write_text(json.dumps({"train": tstats, "val": vstats, "model": args.model, "args": vars(args)}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.dry_run:
        return 0
    if not train_ex:
        print("eğitim örneği kalmadı (hepsi bağlam sınırını aştı)", file=sys.stderr)
        return 2

    import torch
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    model = FastModel.get_peft_model(
        model, finetune_vision_layers=False, finetune_language_layers=True, finetune_attention_modules=True, finetune_mlp_modules=True,
        r=args.rank, lora_alpha=args.rank, lora_dropout=0, bias="none", random_state=args.seed)
    pad_id = text_tokenizer(tokenizer).pad_token_id or 0
    cols = ("input_ids", "labels", "attention_mask")
    train_ds = Dataset.from_list([{k: e[k] for k in cols} for e in train_ex])
    val_ds = Dataset.from_list([{k: e[k] for k in cols} for e in val_ex]) if val_ex else None
    bf16 = bf16_native(torch.cuda.get_device_capability(0), torch.cuda.is_bf16_supported())   # T4'te emüle bf16 KULLANILMAZ (compat.bf16_native)
    print(f"GPU capability {torch.cuda.get_device_capability(0)} | bf16={bf16}")
    base = dict(
        per_device_train_batch_size=1, per_device_eval_batch_size=1, gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs, learning_rate=args.lr, lr_scheduler_type="linear", warmup_steps=10, weight_decay=0.01, optim="adamw_8bit",
        logging_steps=5, eval_strategy="steps" if val_ds is not None else "no", eval_steps=args.eval_steps, seed=args.seed,
        fp16=not bf16, bf16=bf16, report_to="none", remove_unused_columns=False,
        dataset_kwargs={"skip_prepare_dataset": True},   # veri zaten tokenlanmış ve maskelenmiş
    )
    seq_key = first_supported(SFTConfig, ("max_seq_length", "max_length"))          # TRL sürümüne göre; inspect ile saptanır
    if seq_key is None:
        raise RuntimeError("SFTConfig ne max_seq_length ne max_length kabul ediyor: TRL sürümünü kontrol edin (training/README.md sorun giderme)")
    print(f"SFTConfig dizi uzunluğu alanı: {seq_key}")
    sched = schedule_kwargs(args, out)
    cfg = SFTConfig(**base, **sched, **{seq_key: args.max_seq})
    trainer = SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=train_ds, eval_dataset=val_ds, data_collator=PadCollator(pad_id), args=cfg)
    ckpt = latest_checkpoint(sched["output_dir"]) if args.resume else None
    if args.resume:
        print(f"devam edilen kontrol noktası: {ckpt}" if ckpt else f"kontrol noktası yok ({sched['output_dir']}): sıfırdan başlanıyor")
    result = trainer.train(resume_from_checkpoint=str(ckpt)) if ckpt else trainer.train()
    (out / "train_result.json").write_text(json.dumps(result.metrics, indent=2), encoding="utf-8")
    model.save_pretrained(str(out / "adapter"))
    tokenizer.save_pretrained(str(out / "adapter"))
    print(f"adaptör kaydedildi: {out / 'adapter'}")
    if args.gguf:
        export_gguf(model, tokenizer, out / "gguf", args.gguf)
    return 0


def export_gguf(model, tokenizer, dest: Path, method: str) -> None:
    """Birleştirilmiş modeli GGUF'a çevirir (Unsloth). API adı sürüme göre değişir: önce `quantization_method`, olmazsa `quantization_type`."""
    dest.mkdir(parents=True, exist_ok=True)
    key = first_supported(model.save_pretrained_gguf, ("quantization_method", "quantization_type"))   # sürüme göre; inspect ile saptanır
    if key is None:
        raise RuntimeError("save_pretrained_gguf quantization_method/quantization_type kabul etmiyor: training/README.md'deki elle dönüştürme adımlarını kullanın")
    value = method if key == "quantization_method" else method.upper()
    print(f"save_pretrained_gguf argümanı: {key}={value}")
    model.save_pretrained_gguf(str(dest), tokenizer, **{key: value})
    print(f"GGUF yazıldı: {dest}")


if __name__ == "__main__":
    raise SystemExit(main())
