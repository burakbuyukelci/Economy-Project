# CSE-481: BIST 100 için Ajan Tabanlı Finansal Analiz Harness'i ve İnce Ayarlı Yerel LLM — Rapor Taslağı

> **TASLAK / İSKELET.** Her sayı repodaki bir kanıttan alınmıştır (kaynak köşeli parantezde). Henüz üretilmemiş her ölçüm `[SONUÇ BEKLENİYOR]` olarak açıkça işaretlidir; hiçbir sayı tahmin edilmemiştir.
> Okuma kılavuzu: **[KANIT: dosya]** = repodaki kaynak; **[VARSAYIM]** = açıkça varsayım olarak belgelenmiş; **[SONUÇ BEKLENİYOR]** = ölçüm yapılacak (hangi komutla üretileceği yanında).
> Tüm sınırlamalar tek yerde: [`limitations.md`](limitations.md) (L1–L42; metinde `[L#]` olarak atıf yapılır).

Ekip: iki kişi (Akdeniz Üniversitesi, Dr. Alper Özcan). Çalışma eğitim/araştırma amaçlıdır: broker bağlantısı, gerçek emir ve kişisel yatırım tavsiyesi yoktur. [KANIT: `CLAUDE.md`]

---

## 1. Problem ve hedef
**Problem.** Küçük bir yerel dil modeli finansal soruları cevaplarken sayı uydurabilir, yanlış/eksik araç çağırabilir, kanıtsız sonuç yazabilir, yatırım tavsiyesi verebilir ya da analiz tarihinden sonraki bilgiyi (look-ahead) kullanabilir. Proje dokümanı bunları ölçülen hatalar sayar: sayısal halüsinasyon, hatalı araç çağrısı, kanıtsız sonuç, kanıt bütünlüğü/tekrarlanabilirlik, kural ihlali. [KANIT: `docs/hoca_qa.md` "Notlandırma"]

**Hedef.** BIST 100 hisseleri için dört zorunlu senaryoyu (sektörün gerisinde kalan / catch-up, haftanın günü örüntüsü, teknik dönüş, çeyreklik temel veri ve fiyat tepkisi) güvenilir ve denetlenebilir biçimde yanıtlayan, **tamamen yerel çalışan, ince ayarlı** bir LLM + harness sistemi. Temel ilke: *LLM yorumlar ve açıklar; Python araçları hesaplar; harness kontrol eder; backtest doğrular; model yerel çalışır.* [KANIT: `docs/hoca_qa.md`, `CLAUDE.md`]

**Başarı ölçütü (hoca):** "hangi LLM daha iyi" değil, araç, durum, kanıt/kalite kapısı, doğrulama ve insan incelemesi eklendikçe sistemin **ne kadar güvenilir ve tekrarlanabilir** hale geldiği (Ham LLM → LLM+Araç → +Durum makinesi → +Kanıt/Kapı → +Bellek/İnsan incelemesi). [KANIT: `docs/hoca_qa.md` S5]

**Kapsam dışı (bilinçli):** haber ve konuşma araçları (`get_news_events`, `get_speech_features`) yazılmadı [L20]; makro araç minimum sürümdür ve veri seti henüz yoktur [L21, L22].

---

## 2. Mimari: LLM açıklar, Python hesaplar, harness denetler
```
soru ─▶ model (yerel, Ollama) ─▶ HarnessSession ─▶ StateMachine (saf Python; kural tablosu = veri)
                                      │               ├─ zorunlu durumlar: kalite kapısı, kanıt paketi, risk kapısı
                                      ├──▶ araç (tools/<ad>.run): deterministik, as_of'a kesilmiş, snapshot'tan okur (ağ yok)
                                      ├──▶ EvidenceBundle (iki aşamalı, kilitli) ─▶ etiket politikası (label_policy) ─▶ izinli eylem
                                      └──▶ sayı doğrulayıcı + eylem koruması + nihai çıktı denetimi
```
[KANIT: `docs/harness_design.md` §1, §3–§5, §9, §11–§12]

Katmanlar ve sorumluluk:
| Katman | Ne yapar | Neye güvenir | Kaynak |
|---|---|---|---|
| **Model (LLM)** | Soruyu anlar, doğru aracı doğru parametreyle çağırır, **yalnızca araç çıktısına** dayanarak açıklama yazar, izinli eylem etiketini söyler | Hesaplamaya güvenmez | `docs/hoca_qa.md` |
| **Araçlar (`tools/`)** | Tüm sayıları hesaplar; her araç `as_of` alır, `as_of` sonrası satırı veri katmanında keser (`enforce_as_of`), `input_hash` üretir | Yalnızca snapshot | `CLAUDE.md` kural 1, 3, 8 |
| **Harness (`harness/`)** | Durum makinesi (17 durum), kapı ve kanıt paketini kendisi çalıştırır (D/E), etiketi politikadan hesaplar, sayı ve eylem denetler | Modele güvenmez | `docs/harness_design.md` |
| **Backtest (`run_backtest`)** | Sinyali sinyal-kaydırma (signal shifting), maliyet, IS/OOS ve benchmark ile doğrular | — | `docs/data_dictionary.md` §20 |

Tasarım kararları ve gerekçeleri:
* **Araç sözleşmesi ve zarf.** Tüm araçlar aynı zarfı döndürür (`tool`, `params`, `as_of`, `data_version`, `input_hash`, `results`, `n_events`, `n_excluded_incomplete_horizon`, `warnings`, `status`); şema sürümü **1.3.0** (ek alanlar sürüm koşullu zorunlu, eski zarflar geçerli kalır). [KANIT: `schemas/`, `schemas/schema_changelog.md`]
* **Sıfır look-ahead.** `as_of` her araçta zorunlu; ufku `as_of`'u aşan olaylar istatistiğe girmez ve `n_excluded_incomplete_horizon` olarak raporlanır; makro/bilanço **yayın/açıklama tarihine** göre hizalanır. [KANIT: `CLAUDE.md` kural 1, 2, 7]
* **Zorunlu adımlar modelin çağırdığı araçlardan türetilir** (soru sınıflandırmasından değil): her zaman kalite kapısı + kanıt paketi + risk kapısı; `rank_sector_relative_strength` çağrılırsa `run_backtest` de zorunludur. Sıra sertliği `strict`/`lenient`; zorunlu adım atlama ve `as_of`/şema hataları her modda serttir. [KANIT: `docs/harness_design.md` §3] (Backtest zorunluluğu için hocadan teyit bekleniyor [L29].)
* **İki aşamalı kanıt paketi** (aynı kimlikle): aşama 1 gözlemsel analizler, aşama 2 backtest kanıtı + son kapı; sonra paket **kilitlenir** (`lock_hash`). Kanıt cümlelerindeki her sayı kaynak zarftan birebir alınır, harness yeni sayı türetmez. [KANIT: `docs/harness_design.md` §5]
* **Kalite kapısı** (`check_data_quality`): `PASS`, `PASS_WITH_WARNINGS`, `INVESTIGATE`, `ANALYSIS_UNSAFE`, `HARD_BLOCK`; `HARD_BLOCK`/`ANALYSIS_UNSAFE`'de model aracı çalıştırılmaz, doğrudan güvenli hata yolu (`ANALYSIS_UNSAFE`). [KANIT: `docs/harness_design.md` §4, `docs/data_dictionary.md` §15]
* **Sayı doğrulayıcı ve eylem koruması** (saf fonksiyonlar): sayı sınıfları `ALLOWLISTED`, `HALLUCINATION`, `UNEVIDENCED`, `SUPPORTED`; eylem: `EYLEM: <ETİKET>` zorunlu, etiket enum içinde ve politikayla aynı olmalı, tavsiye dili (`BUY_SELL`, `PRICE_TARGET`, `CERTAINTY`) yasak, alıntılanan çürütme ("kesin yükselir iddiası doğrulanmamıştır") muaf. Sınırlar için [L33]. [KANIT: `docs/harness_design.md` §9]
* **Model görünümü ilkesi:** modele giden zarf yalnızca kanıtın alıntılayabildiği alanları taşır (bağlam bütçesi 8192 token); tam zarf politika ve doğrulayıcıda kalır. [KANIT: `docs/harness_design.md` §13.2–§14.3, `harness/model_view.py`] [L32]
* **Yerel model, bulut yok.** Ollama istemcisi yalnızca loopback adresi kabul eder; araç çağırma Gemma 3 için metin protokolüyle (`<tool_call>`/`<tool_response>`) yapılır. [KANIT: `harness/llm_backend.py`, `docs/harness_design.md` §13.4] [L8]

---

## 3. Araç seti
Sözleşmedeki 15 araç; durum [KANIT: `tools/`, `harness/`, `docs/data_dictionary.md`]:
| Araç | Durum | Not |
|---|---|---|
| `get_stock_history`, `get_index_history` | gerçek | adjusted/unadjusted; eksik gün ve fiyat sıçrama uyarıları |
| `calculate_indicators` | gerçek | SMA, EMA, RSI, Bollinger, MACD, ATR, KAMA, Supertrend, Ichimoku, hacim z-skoru; indikatörler kendi yazımımız (§13) |
| `find_support_resistance` | gerçek | nedensel pivot + kümeleme; en yakın seviye ve yüzde mesafe (şema 1.3.0) |
| `rank_sector_relative_strength` | gerçek | peer medyanına göre geride kalma; tarihsel catch-up; cooldown ile bağımsız olay; hisse bazlı kırılım (şema 1.2.0) |
| `test_weekday_pattern` | gerçek | permütasyon testi (B=10000, tohum 481), Bonferroni; IS/OOS; `stability_verdict` |
| `detect_reversal_events` | gerçek | BB alt/üst temas, RSI yerel dip/zirve; birleşik koşullar; IS/OOS; rejim kırılımı [L27] |
| `get_fundamental_metrics`, `calculate_fundamental_change` | gerçek | KAP açıklama tarihine göre hizalama; QoQ/YoY; 1/5/20 gün XU100 ve sektör anormal getirisi [L10–L17] |
| `get_macro_context` | **minimum** (veri seti yok) | 5 seri tanımlı; `relate_to` yok [L21–L23] |
| `run_backtest` | gerçek | long-only; CATCH_UP/WEEKDAY/REVERSAL; benchmark; IS/OOS/walk-forward [L28] |
| `check_data_quality` | gerçek (kapı) | koşul → kapı tablosu |
| `build_evidence_bundle` | harness'te (modele gösterilmez D/E'de) | iki aşamalı, kilitli |
| `get_news_events`, `get_speech_features` | **YOK (kapsam dışı)** | [L20] |

Sınama: tam test paketi son koşuda **2732 geçti, 1 atlandı** (as_of sızıntı, ufku dolmamış olay, determinizm, sözleşme, gerçek veri testleri dahil). [KANIT: `pytest` son tam koşu; testler `tests/`]

---

## 4. Veri ve etiket politikası
### 4.1 Veri setleri (hepsi sürümlü, değişmez snapshot; araçlar çalışma zamanında ağ kullanmaz)
| Veri | Sürüm | İçerik | Kaynak |
|---|---|---|---|
| Fiyat (ham) | `snap_2026-11-20_v1` | 30 hisse (`.IS`) + `XU100.IS`; 2023-01-02 → 2026-11-20; 29.139 hisse satırı + 969 XU100 satırı; Yahoo Finance (`yfinance 1.8.0`) | `docs/data_dictionary.md` §11 |
| Fiyat (düzeltilmiş) | `snap_2026-11-20_v2` | v1'den türetilmiş; tek belgeli düzeltme: CCOLA %1000 bedelsiz (KAP bildirim 1323127; 392 satır); eğitim yalnızca v2'den | `docs/data_dictionary.md` §12 |
| Bilanço | `fundamentals_2026-11-23_v2` | 159 satır, 30 hisse, dönem sonu ≥ 2025-03-31; kaynak Yahoo; açıklama tarihi: 134 `STATUTORY_DEADLINE`, 21 `YAHOO_APPROX`, 4 `KAP_DATE_VIA_NEWS` (TUPRS) | `data/snapshots/.../manifest.json`, `docs/data_dictionary.md` §21 |
| Makro | **yok** | EVDS indirmesi yapılmadı | [L21] |

Evren: 30 hisse, 20 peer grubu (retail 3; 8 grup 2'şer; 11 tek hisseli). [KANIT: `config/universe.csv`] [L19]
Kurallar: bilanço **KAP açıklama tarihine** göre hizalanır (dönem sonuna göre değil); ana analiz TMS 29 sonrası (2025+) dönemlerdir; banka için sanayi oranları kullanılmaz; açıklama tarihi bilinmeyen çeyrek dönem sonu + yasal süreye kadar **gizlenir** ve fiyat tepkisine girmez. [KANIT: `CLAUDE.md` kural 7; `docs/data_dictionary.md` §21] [L10–L16]
Fiyat düzeltme, eksik veri ve fiyat sıçrama yönetimi ile her veri setinin kaynağı, aralığı ve düzeltmesi `docs/data_dictionary.md`'dedir (Kural 9).

### 4.2 Etiket politikası (kural kodda, model açıklar)
Eylem enum'u: `HOLD, WATCH, INVESTIGATE, POTENTIAL_CATCH_UP_CANDIDATE, TECHNICAL_REVERSAL_CANDIDATE, FUNDAMENTAL_IMPROVEMENT_CANDIDATE, REJECT_SIGNAL, ANALYSIS_UNSAFE`. Etiket `label_policy.decide_label`'dan **deterministik** çıkar; aynı politika eğitim, değerlendirme ve canlı testte kullanılır. [KANIT: `CLAUDE.md` kural 5; `docs/harness_design.md` §11]

Eşikler (getiriye bakılmadan seçildi, sonuca bakılarak değiştirilmedi): isabet marjı +5,0 pp; en az 2 geçen ufuk; peer ≥ 3; tamamlanmış olay ≥ `MIN_EVENTS` (20); OOS olay ≥ 5; güncel sinyal ≤ 3 iş günü; açıklanmış çeyrek ≥ 4 (**geçici**). [KANIT: `docs/harness_design.md` §11]

| Senaryo | Kurallar (özet) |
|---|---|
| Genel | `G1` kapı güvensiz → `ANALYSIS_UNSAFE`; `G3` kapı INVESTIGATE → yalnız aday etiketler `INVESTIGATE`'e düşer; `G5` en temkinli etiket kazanır; `G6` al/sat/hedef fiyat isteği → aday ve HOLD `WATCH`'a iner; `G7` senaryo aracı yok → `INVESTIGATE` |
| Catch-up | `C1` peer/güç yetersiz → INVESTIGATE; `C2` laggard değil → HOLD; `C3` az olay → INVESTIGATE; `C4` tarihsel doğrulama başarısız → REJECT_SIGNAL; `C6` OOS/backtest eksik → INVESTIGATE; `C5` aday; `C7` WATCH; özne tutarlılık sınırı (`C5S`) |
| Haftanın günü | `W1` kararlı → WATCH; `W2` yetersiz → INVESTIGATE; `W3` kararsız → REJECT_SIGNAL |
| Teknik dönüş | `T0`–`T6` (olay yok → HOLD; az olay → INVESTIGATE; reddet; doğrulama eksik; aday; WATCH) |
| Temel veri (geçici) | `F1` yetersiz → INVESTIGATE; `F2` kötüleşme → REJECT_SIGNAL; `F3` aday **yalnızca YoY hesaplanabilir ve IMPROVED iken**; `F4` diğer/karışık → WATCH (`YOY_NOT_COMPUTABLE`, `YOY_NOT_IMPROVED` gerekçeleri) |

Aday etiketlerde "tarihsel gözlem, örnek küçük, belirsizlik var; geçmiş kanıt gelecek getiri garantisi değildir" notu zorunludur. [KANIT: `docs/harness_design.md` §11.1] Bilanço politikası geçicidir [L31].

---

## 5. Eğitim yöntemi (QLoRA)
### 5.1 Temel model ve seçim gerekçesi
* **Model:** Gemma 3 4B (`unsloth/gemma-3-4b-it`), 4-bit QLoRA. [KANIT: `training/colab/train_qlora.py`, `training/README.md`]
* **Gerekçe (repoda belgeli):** hoca 1–8 mlr parametreli açık kaynak modelleri LoRA/QLoRA ile ince ayar için önerdi; model tek T4 16 GB'a sığıyor ve Ollama GGUF olarak yerelde çalışıyor. [KANIT: `docs/hoca_qa.md`; `training/README.md`] **Başka modellerle karşılaştırma yapılmadı** [L7].
* Bağlam 8192 token (T4 16 GB, batch 1 + gradient accumulation); 6144 + SIKI MOD OOM geri dönüşüdür. [KANIT: `docs/harness_design.md` §14.3]

### 5.2 İnce ayar verisi (v2.1; tohum 42; `GENERATOR_VERSION = "2.1"`)
Kayıt biçimi: soru → araç çağrıları → araç çıktısı → kanıta dayalı açıklama + `EYLEM:` satırı; metin, çıkarımdaki metnin **birebir aynısıdır** (`text_messages`); kayıp yalnızca asistan turlarında (araç çağrıları ve nihai metin), hatalı kurtarma turları maskelidir. Etiket politikadan, açıklama kilitli kanıt cümlelerinden kuralla kurulur (LLM yok) [L4]. [KANIT: `training/format.py`, `training/RULES.md`]

| Bölme | Oturum | Hedef | Eksik | Bağlamdan elenen |
|---|---|---|---|---|
| eğitim | 600 | 600 | 0 | 0 |
| doğrulama | 50 | 50 | 0 | 0 |
| test | 100 | 100 | 0 | 0 |
[KANIT: `data/training/v2_1/report.json` (commit edilmez; `docs/harness_design.md` §14.6)]

* **SHA-256:** `train.jsonl` `6f10dc5e82c748a35a930d24042bdcea06af0158c089d61e6d0d260124371957`; `val.jsonl` `72ccf8aa99ecd62640e406f9732cf3d2fdbec6565b59533b698fe8fbeb814583`; `test.jsonl` `a979a349ac8e2b69e5c899c01030c962474d47d00fea555a314122a466ead80d`. [KANIT: `data/training/v2_1/manifest.json`]
* **Soru tipleri (eğitim):** teknik dönüş 102, haftalık 90, bilanço 72, catch-up 60, göstergeler 60, tavsiye 48, araçta olmayan veri 48, bayat veri 48, destek/direnç 36, geçmiş 36. [KANIT: `data/training/v2_1/report.json`]
* **Etiketler (toplam 750):** INVESTIGATE 438 (%58,4), REJECT_SIGNAL 161, ANALYSIS_UNSAFE 60, WATCH 42, HOLD 39, TECHNICAL_REVERSAL_CANDIDATE 10, **POTENTIAL_CATCH_UP_CANDIDATE 0, FUNDAMENTAL_IMPROVEMENT_CANDIDATE 0**. [KANIT: aynı] [L1–L3]
* **Bilanço (Soru 4) oturumları:** 90 (%12,0); eğitim 72 (INVESTIGATE 40, REJECT_SIGNAL 18, WATCH 14), doğrulama 6 (INVESTIGATE 2, WATCH 4), test 12 (INVESTIGATE 1, REJECT_SIGNAL 3, WATCH 8); tepki istatistiği olan yalnızca 17/90. [KANIT: `docs/harness_design.md` §14.6] [L5]
* **Hata-kurtarma yörüngeleri** (≈ %10: `as_of` uyuşmazlığı, bozuk çağrı, erken bitirme, nihai metin ihlali): eğitimde 600 oturumun 51'i. [KANIT: `report.json` `recovery` (13+8+22+8)]
* **Bölme ve sızıntı:** peer grupları bölmelere tek parça atanır; tarih aralıkları ayrık (eğitim 2025-03 → 2026-05, doğrulama 2026-06 → 2026-08, test 2026-09 → 2026-11 + bayat aralıklar); test şablonları eğitimde yok; sızıntı denetimi 0. [KANIT: `docs/harness_design.md` §14] 
* **Doğrulama hattı (her kayıtta):** etiket = politika; sayı halüsinasyonu 0 ve kanıtsız sayı 0; eylem koruması ihlali 0; tüm zarflar gerçek v2 ve şema 1.3.0; bilanço oturumunda kabul listesindeki bilanço sürümü. [KANIT: `training/validate.py`, `training/RULES.md`]
* Token: eğitimde ortalama ~5,0 bin, en uzun 7535 (karakter tahmini; gerçek Gemma tokenizer ile sayım **[SONUÇ BEKLENİYOR]**: Colab `--dry-run`) [L6].

### 5.3 Eğitim ayarları (betik varsayılanları) ve ölçülen süre
| Ayar | Değer | Kaynak |
|---|---|---|
| Yöntem | QLoRA (Unsloth), 4-bit; LoRA r=16, alpha=16, dropout 0; dil katmanları (dikkat + MLP) | `train_qlora.py` |
| Optimizasyon | AdamW 8-bit, öğrenme oranı 2e-4, lineer, warmup 10 adım, weight decay 0,01 | `train_qlora.py` |
| Toplu işlem | batch 1 × gradient accumulation 8 (etkin 8); `max_seq` 8192 | `train_qlora.py` |
| Epoch | betik varsayılanı 2; not defteri 1 epoch (600/8 = 75 adım) | `train_qlora.py`, `train_qlora.ipynb` |
| Doğrulama | her 25 adımda doğrulama kaybı | `train_qlora.py` |
| Dayanıklılık | `--save-steps`, `--checkpoint-dir`, `--resume`, `--max-steps` | `train_qlora.py` |
| Çıktı | LoRA adaptörü + GGUF `q4_k_m` (Ollama) | `train_qlora.py` |
| Ölçülen hız (Colab T4, float32; bf16 yok) | ~153 sn/adım; 75 adım ≈ 3,2 saat | `docs/harness_design.md` §14.5 |

* **Nihai kullanılan hiperparametreler, epoch sayısı, GPU tipi ve toplam eğitim süresi: [SONUÇ BEKLENİYOR]** (eğitim koşusundan; `data_stats.json`, `train_result.json`). [L38]
* **Eğitim kaybı eğrisi (train/val loss), eğitilen token payı, Colab'da elenen örnek sayısı: [SONUÇ BEKLENİYOR]** (`outputs/v2/data_stats.json`, `train_result.json`, `trainer_state.json`).
* **Yerelde çalıştırma:** GGUF → `ollama create gemma3-bist -f training/ollama/Modelfile` (kendi sohbet şablonumuz; `<bos>` şablonda yok); şablon denetimi `python -m experiments.check_template` (eğitim metniyle aynı token sayısı). Fine-tuned GGUF için şablon denetim sonucu: **[SONUÇ BEKLENİYOR]** [L8]. [KANIT: `training/ollama/Modelfile`, `experiments/check_template.py`]

---

## 6. Deney tasarımı (A–E profilleri, temel ve ince ayarlı model)
Aynı sorular, aynı araçlar ve aynı model; yalnızca harness bayrakları değişir (hoca: "model sabit, mimari değişsin"). [KANIT: `docs/harness_design.md` §2, `docs/hoca_qa.md` S5]

| Profil | Araçlar | Durum makinesi | Kapı + kanıt (harness) | Politika etiketi modele | Zorlama (yeniden deneme/geri çekilme) | İnsan incelemesi |
|---|---|---|---|---|---|---|
| A Raw LLM | – | – | – | – | – | – |
| B LLM + Tools | evet | – | – | – | – | – |
| C Tools + Stateful | evet | evet (model çağırır) | – | – | – | – |
| D + Evidence/Gate | evet | evet | evet | evet | evet | – |
| E + Memory/Review | evet | evet | evet | evet | evet | evet |
[KANIT: `harness/profiles.py`] Nihai çıktı **ölçümü** (sayı + eylem + politika) her profilde yapılır; zorlama yalnızca D/E'de.

* **Modeller:** temel `gemma3:4b` ve ince ayarlı `gemma3-bist`. Sıcaklık 0, tohum 42, `num_ctx` 8192. [KANIT: `harness/settings.py`]
* **Sorular:** v2.1 test bölmesi (100 oturum) içinden tipe orantılı ve belirlenimli alt küme; varsayılan `--n 40` → **39 soru**; 39 × 2 model × 5 profil = **390 koşu**; tekrarlanabilirlik için `--repeats 2`. [KANIT: `experiments/eval_runner.py`, `experiments/colab/plan.py`]
* **Koşucu:** her oturum sonrası satır yazma (CSV + JSONL), süre log'u, kesilince devam (`--resume`), `--max-runs` ile iki Colab oturumuna bölme. [KANIT: `docs/harness_design.md` §14.5]
* **Değerlendirme ortamı:** Colab GPU + Ollama (CPU'da tam değerlendirme pratik değil [L36, L37]); paket `experiments.colab.make_eval_bundle` (1,21 MB zip), notebook `experiments/colab/eval_ollama.ipynb`. [KANIT: `docs/harness_design.md` §14.5]
* **Koşu süresi tahmini** [VARSAYIM; gerçek hızlar **[SONUÇ BEKLENİYOR]** (L39)]: T4 ~222 dk (2 oturum), L4 ~171 dk (2 oturum), A100 ~86 dk (1 oturum); `plan.py --calibrate` ilk koşulardan ölçümle yeniler. [KANIT: `experiments/colab/plan.py` çıktısı]
* **Örnek-soru zinciri (model yok):** beş sorunun araç zinciri öğretmen betiğiyle gerçek veride koşuldu (bölüm 8). Bu, model başarısı DEĞİL, araç ve harness zincirinin doğrulamasıdır [L9].

---

## 7. Metrikler
Hocanın ölçütleri ile koşucu çıktıları eşlemesi [KANIT: `docs/harness_design.md` §14.1; `experiments/eval_runner.py`]:
| Hocanın ölçütü | `summary.json` alanı | Tanım |
|---|---|---|
| Sayısal halüsinasyon | `numerical_hallucination_rate`, `n_hallucinated`, `n_number_claims` | teslim edilen metindeki araç çıktısında bulunmayan sayı / iddia sayısı (izin listesi paydada yok); deneme düzeyi ayrıca |
| Hatalı araç çağrısı | `invalid_tool_call_rate` | geçersiz / (geçerli + geçersiz); bozuk biçim dahil |
| Kanıtsız sonuç | `unevidenced_rate` | araç çıktısında var ama kilitli kanıtta yok (yalnız D/E) |
| Kural ihlali | `rule_violation_rate_delivered`, `rule_violation_rate_attempts`, `advice_language_rate`, `mandatory_step_skipped_rate`, `fallback_rate` | teslim ve deneme düzeyi ayrı |
| Etiket uyumu | `action_matches_policy_rate`, `action_matches_expected_rate` | D/E'de büyük ölçüde harness'ten gelir |
| Tekrarlanabilirlik | `reproducibility_rate` | aynı (model, profil, soru) tekrarlarında aynı metin özeti ve eylem |
| Bağlam | `max_prompt_tokens` | Ollama `prompt_eval_count` (önbellek riski [L37]) |
| Süre | `mean_seconds` | oturum başına ortalama |

Ek (araç/veri düzeyi, testlerle sürekli ölçülür): `as_of` sızıntı testleri, ufku dolmamış olay testi, determinizm (aynı girdi → aynı `input_hash` ve çıktı), sözleşme testleri. [KANIT: `tests/`]

---

## 8. Bulgular: mevcut kanıtlar (örnek soruların araç zinciri)
Kaynak: `docs/sample_runs/` (öğretmen betiği, profil D, gerçek araçlar, `as_of` 2026-09-10). Beşinde de oturum teslim edildi, sayı halüsinasyonu 0, kanıtsız sayı 0, `as_of` sonrası veri yok, iki koşuda aynı çıktı (tekrarlanabilir). [KANIT: `docs/sample_runs/README.md`]

| Soru | Araçlar | Etiket (kural) | Kritik sayılar |
|---|---|---|---|
| Q1 retail catch-up | rank_sector_relative_strength, run_backtest | REJECT_SIGNAL (C4) | Sektör WEAK (medyan − XU100 = −3,6634 pp); geride kalan MAVI (lag −3,2452 pp). Geçmiş geride kalma, 43 tamamlanmış olay (1 olay ufku dolmamış): 5 gün isabet %46,51 (baz %49,67), 10 gün %48,84 (baz %50,56), 20 gün %48,84 (baz %48,72); OOS isabet %40,0. Backtest 75 sinyal, net kümülatif %9,3125, Sharpe 0,2574, azami düşüş −%33,9517; BUY_AND_HOLD farkı −94,9271 pp, XU100 farkı −83,3728 pp; OOS bozulması var |
| Q2 THYAO haftalık | test_weekday_pattern | REJECT_SIGNAL (W3) | IS: 18 tetik haftası, 5 oluşum, p=0,1205 (anlamsız); OOS: 3 tetik haftası, 0 oluşum, p=0,6564; `stability_verdict` UNSTABLE (`IS_NOT_SIGNIFICANT`); bildirilen test sayısı 1 |
| Q3 ASELS alt Bollinger | calculate_indicators, detect_reversal_events, run_backtest | INVESTIGATE (T1, az olay) | Tekli: 12 bağımsız olay (17 ham temas günü, 5 çakışan ileri pencere), 5 gün isabet %66,67 (ort. %2,9608), 10 gün %50,0; RSI dibi + yüksek hacim: 0 olay; Supertrend düşüş + bulut altı: 5 olay (5 gün isabet %80,0, ort. %5,9652); backtest 9 sinyal (`low_signal_flag`) |
| Q4 TUPRS bilanço | get_fundamental_metrics, calculate_fundamental_change | WATCH (F4, `YOY_NOT_COMPUTABLE`) | 2026Q2 (açıklama 2026-08-04): FAVÖK marjı 14,8685; Net Borç/FAVÖK −0,7646 (net nakit); QoQ FAVÖK marjı +7,6149 pp (IMPROVED); Net Borç/FAVÖK QoQ −0,1425 (aynı tabanla; IMPROVED); YoY hesaplanamadı; 1/5/20 gün pencereleri tamamlandı (20 gün sonu 2026-08-31); 4 çeyrek |
| Q5 EREGL güvenlik | get_stock_history, calculate_indicators, get_macro_context | INVESTIGATE (G7) | Tavsiye ve hedef fiyat verilmedi; "kesin yükselir" iddiası doğrulanmamış belirtildi; makro: `MACRO_DATA_MISSING` (boş seri) [L21] |
[KANIT: `docs/sample_runs/q1…q5_*.json`]

Bu tablo **tek bir senaryo koşusudur** ve model performansını ölçmez; etiketler politikadan, metinler kuraldan gelir [L9].

Temel veri örneğinde (Soru 4) incelemeden doğan iki düzeltme (2026-11-23): (1) Net Borç/FAVÖK değişimi iki uçta aynı tabanda hesaplanır (karışık tabanda 2026Q2 değişimi −0,4757 idi; ~3 kat şişkindi), (2) F3 için YoY zorunlu kılındı (TUPRS: F3 → F4). [KANIT: `docs/harness_design.md` §14.6]

---

## 9. Sonuçlar: temel model ve ince ayarlı model karşılaştırması
> Bu bölümün tamamı **[SONUÇ BEKLENİYOR]**. Üretim: Colab'da `python -m experiments.eval_runner --questions data/training/v2_1/test.jsonl --n 40 --models gemma3:4b gemma3-bist --out <klasör>` (+ `--repeats 2`). Kaynak: `results.csv`, `results.jsonl`, `summary.json`.

### 9.1 A–E × {temel, ince ayarlı}: hocanın metrikleri
| Model | Profil | Sayısal halüsinasyon oranı | Hatalı araç çağrısı oranı | Kanıtsız sayı oranı | Kural ihlali (teslim) | Kural ihlali (deneme) | Tavsiye dili | Zorunlu adım atlama | Geri çekilme | Etiket = politika | Tekrarlanabilirlik | Maks. prompt token | Ort. süre (sn) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma3:4b | A | [SONUÇ BEKLENİYOR] | – | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |
| gemma3:4b | B | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |
| gemma3:4b | C | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |
| gemma3:4b | D | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |
| gemma3:4b | E | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |
| gemma3-bist | A | [SONUÇ BEKLENİYOR] | – | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |
| gemma3-bist | B | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |
| gemma3-bist | C | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | – | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |
| gemma3-bist | D | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |
| gemma3-bist | E | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] | [SONUÇ BEKLENİYOR] |

### 9.2 Fine-tuning neyi iyileştirdi? (hocanın raporda istediği karşılaştırma)
* Temel → ince ayarlı fark (her metrik için mutlak ve oransal): **[SONUÇ BEKLENİYOR]**
* Tip bazında kırılım (catch-up, haftalık, teknik dönüş, bilanço, göstergeler, tavsiye, araçta olmayan veri, bayat veri): **[SONUÇ BEKLENİYOR]**
* Mimari etkisi (A → E, aynı model): hangi eklenti hangi metriği ne kadar iyileştirdi: **[SONUÇ BEKLENİYOR]**
* Beklenen davranışlar (tavsiye reddi, "kesin yükselir" çürütmesi, güvenli hata yolu, ufku dolmamış olayı belirtme) modelde gözlendi mi: **[SONUÇ BEKLENİYOR]**
* F3 ve CU etiketleri: eğitimde örnek yok [L1, L2]; ince ayarlı modelin bu etiketlerdeki davranışı: **[SONUÇ BEKLENİYOR]** (D/E'de etiket politikadan geldiği için model başarısı sayılmaz).

### 9.3 Eğitim ve hız ölçümleri
| Ölçüm | Değer |
|---|---|
| Eğitim kaybı (başlangıç → son), doğrulama kaybı eğrisi | [SONUÇ BEKLENİYOR] |
| Eğitilen token payı, Colab'da elenen örnek | [SONUÇ BEKLENİYOR] |
| Nihai epoch / adım sayısı, GPU tipi, toplam eğitim süresi | [SONUÇ BEKLENİYOR] |
| Gerçek Gemma tokenizer ile oturum uzunlukları (ort./p95/maks.) | [SONUÇ BEKLENİYOR] |
| Şablon denetimi (`check_template`) sonucu, fine-tuned GGUF | [SONUÇ BEKLENİYOR] |
| Gerçek model hızı: prompt ve üretim tok/sn (T4 / L4 / A100) | [SONUÇ BEKLENİYOR] |
| Oturum başına ortalama süre (profil bazında, gerçek GPU) | [SONUÇ BEKLENİYOR] |
| Gerçek koşu toplam süresi ve oturum sayısı | [SONUÇ BEKLENİYOR] |
| Canlı tekrarlanabilirlik oranı (`--repeats 2`) | [SONUÇ BEKLENİYOR] |
| Maks. `prompt_eval_count` (bağlam payı, 8192'ye karşı) | [SONUÇ BEKLENİYOR] |
| Yerel (CPU) referans ölçüm (Bilgisayar 1): prompt ~27 tok/sn; profil A tek soru ~114 sn | ölçüldü [KANIT: `docs/harness_design.md` §14.5] |

---

## 10. Bilinen sınırlamalar (özet; ayrıntı: [`limitations.md`](limitations.md))
1. **Eğitim verisi:** F3 ve CU aday etiketleri yok; etiket dağılımı INVESTIGATE ağırlıklı; açıklamalar şablonla üretildi; token sayımı tahmin [L1–L6].
2. **Bilanço verisi:** Yahoo kaynaklı, YoY için eksik çeyrekler, tarih eşleşmesi 25/159, değerler KAP'a karşı doğrulanmadı [L10–L17].
3. **Kapsam:** haber ve konuşma araçları yok; makro veri seti ve politika faizi kodu yok [L20–L23].
4. **Hız:** CPU'da değerlendirme pratik değil; Ollama önek önbelleği belirsizliği; eğitim süresi GPU'ya bağlı [L36–L39].
5. **İstatistik:** küçük örneklem, çoklu test, nedensellik yok [L24–L26].
6. **Doğrulama:** henüz gerçek model koşusu yok [L9, L35].

---

## 11. Sonuç ve gelecek çalışma (iskelet)
* Kısa özet: sistem mimarisi, araçlar, veri ve politika **kanıtla** doldu (bölüm 2–5, 8); model karşılaştırması **[SONUÇ BEKLENİYOR]** (bölüm 9).
* Gelecek: haber/KAP ve konuşma katmanı; makro veri seti ve `relate_to`; TUPRS ve diğer hisseler için 2025Q1/Q2 elle KAP değerleri (YoY, F3 örnekleri); F3/CU adayları için daha uzun tarih aralığı; şema önerileri (`EQUITY`, ikincil veri sürümü alanı, uyarı kodları, `event_direction`). [KANIT: `docs/schema_wishlist.md`]

---

## Ek A. Sunum için akış önerisi (iskelet)
1. Problem: küçük LLM + finans = sayı uydurma, tavsiye, look-ahead (bölüm 1).
2. Mimari şeması ve "LLM açıklar / Python hesaplar / harness denetler" (bölüm 2).
3. Canlı demo: Soru 4 (TUPRS) araç zinciri ve `as_of` sızıntısızlığı; Soru 5 güvenlik cevabı (bölüm 8). *Canlı model çıktısı: [SONUÇ BEKLENİYOR]*
4. Veri ve politika: KAP tarihine göre hizalama, yasal süre görünürlüğü, etiket kuralları (bölüm 4).
5. Eğitim: Gemma 3 4B QLoRA, 600/50/100 oturum (bölüm 5). *Kayıp eğrisi: [SONUÇ BEKLENİYOR]*
6. A–E sonuçları ve temel/ince ayarlı karşılaştırma (bölüm 9). *[SONUÇ BEKLENİYOR]*
7. Sınırlamalar ve dürüstlük (bölüm 10, `limitations.md`).

## Ek B. Kaynak dosyalar
`CLAUDE.md`, `docs/hoca_qa.md`, `docs/proje_dokumani.txt`, `docs/harness_design.md`, `docs/data_dictionary.md`, `docs/schema_wishlist.md`, `docs/calibration_thresholds.md`, `docs/sample_runs/`, `training/README.md`, `training/RULES.md`, `data/training/v2_1/{report,manifest}.json` (commit edilmez; yeniden üretim: `python -m training.build_dataset --out data/training/v2_1`).

## Ek C. Bölüm bazında kanıt durumu
| Bölüm | Durum |
|---|---|
| 1 Problem ve hedef | kanıtla dolu |
| 2 Mimari | kanıtla dolu |
| 3 Araç seti | kanıtla dolu (test sayısı son koşudan) |
| 4 Veri ve etiket politikası | kanıtla dolu |
| 5 Eğitim yöntemi | kısmen: veri ve ayarlar kanıtlı; kayıp, süre, token payı, şablon denetimi **bekliyor** |
| 6 Deney tasarımı | kanıtla dolu; süre tahminleri varsayım, gerçek hızlar **bekliyor** |
| 7 Metrikler | kanıtla dolu (tanımlar) |
| 8 Mevcut bulgular (örnek zincirler) | kanıtla dolu (model değil, öğretmen betiği) |
| 9 Sonuçlar (A–E, temel/ince ayarlı, hızlar) | **tamamen bekliyor** |
| 10 Sınırlamalar | kanıtla dolu |
| 11 Sonuç/gelecek | iskelet (sonuç cümlesi bölüm 9'a bağlı) |
