# Harness tasarım notları (BİLGİSAYAR 2)

Bu belge `harness/` içindeki kararları ve **gerekçelerini** toplar. Kod yorumlarında "neden" kısa tutulur; ayrıntı burada.
Bölüm numaraları `docs/proje_dokumani.txt`'e atıf yapar. Çelişkide `docs/hoca_qa.md` geçerlidir.

## 1. Temel ilke ve katmanlar
LLM yorumlar, Python araçları hesaplar, **harness kontrol eder**, backtest doğrular.

```
model ──(MCP, ince adaptör: mcp_server.py)──▶ HarnessSession ──▶ StateMachine (saf Python)
                                                  │               routing.py = kural TABLOSU (veri)
                                                  ├──▶ araç (mock | tools/<ad>.run)  ──▶ validate_envelope
                                                  └──▶ EvidenceBundle (kanıt paketi, harness tarafı)
```
Çekirdek (`session`, `state_machine`, `evidence`) MCP SDK'sına bağımlı değildir; SDK değişirse yalnızca `mcp_server.py` değişir.

## 2. Deney aşamaları (A–E) — `profiles.py`
| Aşama | Araçlar | Durum makinesi | Kapılar + kanıt | İnsan incelemesi |
|---|---|---|---|---|
| A Raw LLM | yok | – | – | – |
| B LLM + Tools | açık | kapalı (yalnızca `as_of` ve şema doğrulaması) | – | – |
| C Tools + Stateful | açık | açık; kalite kontrolü ve (türetilen) backtest zorunlu, **modelin çağrısı** | kapalı | – |
| D + Evidence/Gate | açık (13 araç) | açık | **harness çalıştırır** | – |
| E + Memory/Review | açık | açık | harness çalıştırır | açık (deney iskeletinde bağlanır) |

Aşama `settings.EXPERIMENT_STAGE` (ya da `HARNESS_STAGE` ortam değişkeni) ile seçilir. Hoca: modeli sabit tutup yalnızca mimariyi
değiştirmek (Soru 5) — bu tablo tam olarak o karşılaştırmanın bayraklarıdır.

## 3. Durum makinesi (§23)
17 durum (START … LOG_AND_CLOSE). `PREVIEW_STRATEGIES` araçsızdır: strateji varyantları (A–E, §29) `RUN_BACKTEST` durumunda
`run_backtest`'in `strategy.variant` alanıyla önizlenir (aksi halde `run_backtest` iki durumda belirsiz kalırdı).

**Zorunlu durumlar soru sınıflandırmasından değil, modelin BAŞARIYLA çağırdığı araçlardan türetilir** (`routing.py`):
* her zaman: `CHECK_DATA_QUALITY`, `BUILD_EVIDENCE`, `RISK_GATE`
* `rank_sector_relative_strength` çağrıldıysa ek olarak `RUN_BACKTEST`. Diğer analiz araçları (`test_weekday_pattern`,
  `detect_reversal_events`, `calculate_fundamental_change`) kendi IS/OOS + baz getiri + maliyet çıktısını verir; onlar için
  backtest opsiyoneldir. **Hocadan teyit bekleniyor**; tablo değişince davranış değişir (testle doğrulandı).

**Sıra sertliği** (`settings.STATE_ORDER_MODE`): `strict` geçilmiş duruma dönüşü reddeder; `lenient` çalıştırır ama durum geri gitmez.
İki modda da `ORDER_VIOLATION` olayı yazılır ve `n_order_violations` artar (deneylerde "geçersiz çağrı" oranından ayrı raporlanır).
Zorunlu adım atlama, `as_of` ve şema hataları iki modda da **serttir**: hocanın "zorunlu adımı atlama = kural ihlali" ölçütü gevşetilmez.

## 4. Kapıları harness çalıştırır (D/E)
Model kalite kapısını ve kanıt paketini çağırmaz (MCP listesinde yoktur; çağırırsa `HARNESS_ONLY_TOOL` ile geçersiz sayılır).

| Olay | Harness ne yapar |
|---|---|
| Modelin **ilk analiz** çağrısı | önce `check_data_quality` (modelin bekleyen çağrısından türetilen parametrelerle), sonra modelin aracı |
| Modelin `run_backtest` çağrısı | önce **kanıt aşama 1**, sonra backtest |
| Model açıklama ister | (aşama 1 yapılmadıysa yap) → **kanıt aşama 2** → son kalite kapısı → paketi **kilitle** |
| Kapı `HARD_BLOCK`/`ANALYSIS_UNSAFE` | modelin aracı **çalıştırılmaz**; `SAFE_FAILURE` döner; doğrudan açıklama, eylem yalnızca `ANALYSIS_UNSAFE` (§26) |

Neden "tam zamanında"? Durum sırasında kalite kapısı analizden önce gelir, ama o anda hangi hisse analiz edileceği bilinmez.
Kapıyı modelin ilk analiz çağrısına bağlamak parametreleri o çağrıdan türetmemizi sağlar ve kapı yine de analizden **önce** çalışır.

### Kapı parametreleri (`gate_params.py`)
* `tickers`: çağrılardaki `ticker`/`tickers`/`universe` birleşimi; `sector` ise `config/universe.csv` peer grubu üyeleri.
  Hiçbiri yoksa **soru metnindeki** evren hisse kodları (SELECT_UNIVERSE). Yine belirsizse çağrı `TICKER_UNDETERMINED` ile geçersiz olur
  (harness tahmin etmez; modele "ticker/sector verin" denir).
* `end` = oturum `as_of`; `start` = `ANALYSIS_START_DEFAULT` ile modelin en erken başlangıcının küçüğü (pencere varsayılandan dar olmaz).
* `analysis_bundle` = oturumdaki başarılı çıktıların künyesi (kapı ve kanıt zarfları hariç).
* Bilinen boşluk: ilk kapı sonradan çıkan ticker'ları görmez; **son kapı tüm çağrıların ticker birleşimini** kontrol eder.

## 5. İki aşamalı kanıt paketi (§23 sırası ile §25 örneğini uzlaştırma)
**Sorun.** §23 durum sırasında `BUILD_EVIDENCE`, `RUN_BACKTEST`'ten *önce* gelir. §25'teki örnek kanıt kümesi ise E7 olarak backtest
sonucunu da içerir ("Backtest variant B outperformed benchmark after costs"). Tek aşamalı paket ya sırayı bozar ya backtest kanıtını dışarıda bırakırdı.

**Çözüm.** Paket iki aşamada, **aynı kimlikle** kurulur:
1. `BUILD_EVIDENCE` — gözlemsel analiz çıktılarından kanıt (E1…En). Paket sürümü 1.
2. `RISK_GATE` — backtest çıktısı aynı paketin **sonuna** eklenir (E(n+1)…); sürüm 2. Ardından son kalite kapısı çalışır ve paket **kilitlenir**.

Kurallar:
* `analysis_id` oturumdan **sabit** türetilir: `YYYY-MM-DD-` + sorunun sha256 önekinin 12 karakteri. İki aşamada değişmez; sürüm ayrı alandır.
* **Idempotent:** aynı params → aynı zarf. Yeni kaynak yoksa sürüm artmaz.
* **E-numaraları deterministik ve kararlı:** kaynak ilk işlendiğinde numara alır (üretim sırasına göre); aşama 2 aşama 1'i yeniden numaralamaz.
* Çıktı yalnızca **istenen kaynakların** kanıtını içerir; zarf, params ile tutarlı kalır. `run_backtest` dahil her araç zarfı kaynak olabilir.
* **Sayılar yalnızca araç çıktısından** (CLAUDE.md kural 6): kanıt cümlelerindeki ve değerlerindeki her sayı kaynak zarftan birebir alınır, harness
  yeni sayı türetmez (testle denetlenir). Sayı doğrulayıcı (madde 4) kilitli `committed_evidence_set`'i kullanacak.
* `committed_evidence_set`: sonucu gerekçelendiren birincil bulgular; ham veri yükleri ve bağlam (haber, rejim kırılımı, göstergeler) yalnızca `full_evidence_set`'te.
* **Kilit:** `lock_hash` = sha256(analysis_id, sürüm, committed kanıtlar, nihai kapı durumu). Kilitli pakete yazılamaz (`BUNDLE_LOCKED`).
* Kaynaklardan biri mock ise paketin `data_version`'ı mock sentineli taşır (eğitim verisine girmez).
* Neden harness'te: kanıt oturumdaki zarflardan kurulur (hash → zarf); `tools/` tek tek araç hesaplar, oturumu bilmez.

## 6. Analiz tarihi (`as_of`)
Oturum `as_of`'u **harness** belirler, model değil. Öncelik: sorudaki açık işaret ("Analiz tarihi: …", "as_of: …", "Bugün …")
> açık parametre (eval seti) > `DEFAULT_AS_OF` (varsayılan **None**; `HARNESS_DEFAULT_AS_OF` / `--default-as-of`) > hata.
Soru gövdesindeki dönem sınırları ("01.01.2024 – 10.09.2026") işaretsizdir ve asla analiz tarihi sayılmaz. Çelişkili işaretler hata verir.
Yedeğe düşülürse `AS_OF_ASSUMED` uyarısı **harness düzeyinde** üretilir (`session.warnings`, olay günlüğü); `schemas.WarningCode`'da yok,
şema değiştirilmedi. Model aynı tarihi parametreye yazar; farklıysa `AS_OF_MISMATCH` (geçersiz çağrı).

## 7. Gerçek araçlar
Giriş noktası: `tools/<araç_adı>.py → run(params: dict) -> dict`. Hatalar `status=ERROR` zarfıyla döner (model görür, durum ilerlemez,
geçersiz çağrı sayılmaz). Yalnızca `as_of` yok/bozuksa `tools.common.InvalidToolCall` fırlar; harness bunu `ToolRejected(AS_OF_INVALID)` olarak
yakalar, **geçersiz çağrı** olarak loglar. `build_evidence_bundle` `tools/`te değil harness'tedir (bölüm 5).
Mock/gerçek geçişi: `settings.TOOL_BACKEND_OVERRIDES = {ToolName.X: "real"}`.

## 8. Güvenlik bariyerleri (özet)
* Mock çıktılar eğitim verisine girmez: `data_version=snap_1900-01-01_v0` sentineli + `assert_not_mock()`.
* Canlı testte insan incelemesi `PENDING_HUMAN_REVIEW` kalır; `APPROVED` yalnızca isimli inceleyen + gerekçeyle açıkça kaydedilir.
* Geçersiz çağrılar (`UNKNOWN_TOOL`, `HARNESS_ONLY_TOOL`, `TOOL_NOT_EXPOSED`, `MANDATORY_STATE_SKIPPED`, `STATE_ALREADY_PASSED`,
  `PRECONDITION_FAILED`, `AS_OF_*`, `INVALID_PARAMS`, `TICKER_UNDETERMINED`, `AS_OF_INVALID`) sayılır ve olay günlüğüne yazılır.

## 9. Açık noktalar
* Hocadan teyit: `run_backtest` yalnızca catch-up'ta mı zorunlu (bölüm 3).
* `RISK_GATE` ve `BUILD_EVIDENCE` için `tools/check_data_quality.py` henüz yok; kapı şimdilik mock. Gerçek kapıyla `analysis_bundle` ve
  `hard_blocks` alanlarının davranışı yeniden test edilmeli.
