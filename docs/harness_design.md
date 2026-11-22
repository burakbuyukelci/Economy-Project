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
* `analysis_bundle` = oturumdaki başarılı çıktıların künyesi (kapı ve kanıt zarfları hariç). **Şema 1.2.0:** künye ayrıca `signal_lag_days_applied` (yalnızca `run_backtest`'in `results`'ından) ve `max_result_date`
  (`schemas.registry.max_result_date`) taşır; kopyalanmazsa kapının `SIGNAL_SHIFT` / `LOOKAHEAD_SIGNAL` / `BACKTEST_FUTURE_INFO` kontrolleri "çalışmadı" der (testle gerçek kapıya ulaştığı doğrulanır).
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
* `committed_evidence_set`: sonucu gerekçelendiren **başlık bölümleri**; ham veri yükleri ve bağlam (haber, rejim kırılımı, destek/direnç) yalnızca `full_evidence_set`'te.
  Hangi bölümün başlık olduğu **veri**dir: `harness/evidence_headlines.json` (araç → `headline` / `context` / `excluded`). Çıkarıcılar her kanıt adayına bir bölüm adı verir;
  bildirilmemiş bölüm bağlam sayılır. `calculate_indicators` için başlık = `latest` (as_of günü değerleri ve durumları); `recent_rows` kasıtlı olarak kanıta HİÇ girmez.
  `tests/harness/test_evidence_headlines.py` çıkarıcı ↔ dosya tutarlılığını (bildirilmemiş ve bayat bölüm adı) denetler.
* **Şema 1.2.0 (rank):** committed kanıta iki bölüm eklendi (`evidence_headlines.json` version 3): `pooling` (ham geride kalan hisse-günü, `cooldown_days`, sonuç ölçütü: peer medyanı, hisse hariç) ve `per_ticker` (her hisse için ham/bağımsız/dışlanan olay sayısı + ufuk bazında tamamlanmış olay, isabet, taban isabet).
  Değer adları `ticker_*` önekli; hepsi `policy_values`'ta. Sayılar kaynak zarftan aynen kopyalanır (türetme yok). 1.1.0 zarfında ve tek hisseli grupta alanlar `None` olduğundan madde üretilmez.
  `check_data_quality` için kanıt çıkarıcısı **eklenmedi** (öneri: eklenmesin): kapı kanıt değil denetimdir; sonucu `lock_hash`'e ve politika bloğuna girer. `issue_counts` sayıları sayı doğrulayıcı havuzunda tipli yolla (`issue_counts.FEW_EVENTS`) bulunur,
  kilitli kanıtta olmadığından D/E'de `UNEVIDENCED` (not) çıkar; `gate_reason` metninden ayrıştırma bağımlılığı bu yüzden gereksizdir ama geçiş döneminde havuzda kalır.
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
* **Eğitim verisine uygunluk** (CLAUDE.md kural 12): eğitim kaydına yalnızca `data_version = snap_<tarih>_v<N>` ve **N ≥ 2** olan zarflar girer
  (`settings.MIN_TRAINING_SNAPSHOT_VERSION`). Mock (`snap_1900-01-01_v0`), v1 (ham kaynak) ve bozuk/eksik `data_version` reddedilir; sürüm
  numarası sayısal karşılaştırılır (v10 > v2). Eğitim verisi üreten kod her zarf için `harness.mock_tools.assert_training_eligible(env)`
  çağırır (`is_training_eligible` bool döndürür). `assert_not_mock()` yalnızca mock'u eler; eğitim için yetersizdir.
* Canlı testte insan incelemesi `PENDING_HUMAN_REVIEW` kalır; `APPROVED` yalnızca isimli inceleyen + gerekçeyle açıkça kaydedilir.
* Geçersiz çağrılar (`UNKNOWN_TOOL`, `HARNESS_ONLY_TOOL`, `TOOL_NOT_EXPOSED`, `MANDATORY_STATE_SKIPPED`, `STATE_ALREADY_PASSED`,
  `PRECONDITION_FAILED`, `AS_OF_*`, `INVALID_PARAMS`, `TICKER_UNDETERMINED`, `AS_OF_INVALID`) sayılır ve olay günlüğüne yazılır.

## 9. Sayı doğrulayıcı (`harness/number_verifier.py`) ve eylem koruması (`harness/action_guard.py`)
İkisi de **saf fonksiyon**dur (oturum/MCP bağımlılığı yok); oturuma bağlama bölüm 12'dedir (`HarnessSession.submit_final`).
`verify_session(session, metin)` yalnızca ince bir yardımcıdır.

### 9.1 Sayı doğrulayıcı
Akış: metin → **maskele** → **çıkar** → **sınıflandır** → rapor.
* **Sayı sayılmayanlar** (maskelenir): tanımlayıcılar (`XU100`, `2025Q1`, `BB_LOWER_20_2.0`, `RSI_14`, `E7`, `snap_..._v2`, `kap-0001`), URL, saat,
  `[1]` dipnotu, satır başı liste numarası (`1)`, `2.`), `2. çeyrek` gibi sıra sayısı, hash.
* **Biçimler:** `1.234,56`, `8,5`, `8.5`, `1,234.56`, `%8,5`, `8,5%`, `yüzde 8,5`, `8,5 puan/pp`, `38,4 milyon` (ölçek: bin/milyon/milyar/trilyon),
  tarihler (`10.09.2026`, `2026-09-10`, `10 Eylül 2026`; geçersiz tarih halüsinasyondur). `1.234` belirsizdir (1234 ya da 1,234): **iki aday**, biri eşleşirse yeter.
* **Sınıflar:** `ALLOWLISTED` (soruda ya da herhangi bir araç çağrısı parametresinde AYNEN var; iddia sayılmaz, paydaya girmez) →
  `HALLUCINATION` (hiçbir araç çıktısında yok; hocanın metriği) → `UNEVIDENCED` (araç çıktısında var, kilitli `committed_evidence_set`'te yok; yumuşak uyarı) → `SUPPORTED`.
  Kanıt kümesi verilmezse (`None`; A–C aşamaları, kilit yok) ikinci seviye kapalıdır.
* **Havuz kaynağı:** zarfın `results` ağacı **ve** zarf düzeyi `n_events`, `n_excluded_incomplete_horizon`, `warnings` metinleri (yol örn. `warnings[3]`). Gerçek retail zarfında
  `HISTORICAL_ONLY` uyarısındaki ham sayılar ("BIMAS 43, MAVI 227 ... toplam 398") bu yüzden alıntılanabilir. Bu alanlar kanıt paketine girmediğinden, kilitli pakette (D/E) böyle bir sayı `UNEVIDENCED` çıkar.
* **`ALLOWLISTED_POLICY`:** D/E'de model politika bloğunu görür (bölüm 12); bloktaki sayılar (örn. `MIN_EVENTS (20)`, `< 4` çeyrek) araç çıktısında yoksa `HALLUCINATION` değil `ALLOWLISTED_POLICY` olur.
  Ayrı sayılır (`n_allowlisted_policy`), paydaya girmez; araç kanıtı her zaman önce gelir (aynı sayı araçta da varsa `SUPPORTED`). `policy_text` boşsa (A–C, D′) özellik kapalıdır.
* **Metrikler:** `numerical_hallucination_rate = n_hallucinated / n_claims`; `unevidenced_rate` ayrı. `n_claims` izin listesindekileri içermez.
  Eşleşme sayaçları: `n_exact`, `n_rounded` (d≥1), `n_rounded_coarse` (d=0), **`n_rounded_total`** (ikisinin toplamı), `n_sign_relaxed`.
* **Yuvarlama kuralı:** yazılan sayı d ondalıklıysa havuz değeri d basamağa **yarıdan yukarı** (`Decimal`) yuvarlanınca eşitse doğru. Tam sayı (d=0) yalnızca
  havuzdaki **aynı tam sayıyla** `EXACT` eşleşir; havuzda 8,46 varken yazılan "8" `ROUNDED_COARSE` etiketini alır (desteklenmiş ama ayrı sayılır). Kesme kabul edilmez.
  İşaret yalnızca tutmuyorsa (`-8,5` ↔ 8.5) `SIGN_RELAXED`; yön hatası sayı halüsinasyonu sayılmaz, ayrı etiketle raporlanır.
* **Türetilmiş sayı (14/22 → %64):** araç çıktısında yoksa **HALÜSİNASYON**. Rapor ayrıca `derivation_hint` yazar: aynı cevaptaki *diğer* (desteklenen/izinli)
  sayılardan `a/b·100`, `a/b`, `(a−b)/b·100`, `a−b`, `a+b`, `a·b` ile üretilebiliyorsa nasıl üretildiğini gösterir (örn. `(299.25-305)/305*100=-1.89`). İpucu sayıyı **aklamaz**;
  eğitim geri bildirimi için "model kendi hesapladı" bilgisidir.
* **Bilinen sınırlar:** küçük tam sayılar (1, 2, 3 …) havuzda tesadüfen bulunabilir (halüsinasyon oranı *alt sınırdır*); kelimeyle yazılan sayılar çıkarılmaz;
  yön denetlenmez; sorudaki sayı aynı zamanda araç değeriyse izin listesinde sayılır; büyük bir tarih sonrası (look-ahead) denetimi bu modülün işi değildir.
* **Gerçek örnek (THYAO 10.09.2026, `get_stock_history` + `calculate_indicators` zarfları):** `299,25` → `EXACT` (`rows[2].close`); `44,83` → `ROUNDED`
  (`latest.values.RSI_14 = 44.8273`); `38,4 milyon` → `ROUNDED` (`rows[2].volume = 38386110.0`); `10.09.2026` ve `08.09.2026` → `ALLOWLISTED`
  (`as_of` ve çağrının `start` parametresi). Uydurma `RSI 31,2`, `310,50`, `61 milyon` → `HALLUCINATION` (oran 3/4).
* **Gerçek kanıt paketi (THYAO):** göstergelerin `latest` bölümü committed olduğundan as_of günü RSI/Bollinger/Supertrend sayıları `SUPPORTED`; `recent_rows`'taki bir önceki
  günün RSI'ı araç çıktısında var ama kanıta girmediği için `UNEVIDENCED` (yumuşak uyarı) çıkar. `find_support_resistance` bağlamda bırakıldı (karar sonraya).

### 9.2 Eylem koruması
* **Etiket:** nihai çıktıda `EYLEM: <ETİKET>` (ya da `ACTION:`) satırı **zorunlu**; etiket tam olarak `AllowedAction` değeri olmalı. Kodlar: `NO_ACTION`, `MULTIPLE_ACTIONS`,
  `ACTION_NOT_IN_ENUM` (küçük harf/`BUY`/`WATCH (izle)` dahil), `ACTION_MISMATCH_REQUIRED` (`required_action`, güvenli hata yolu: `ANALYSIS_UNSAFE`). Metin içinde geçen enum adı etiket sayılmaz.
* **Tavsiye dili:** kalıplar `harness/lexicons/advice_phrases.json` (veri; kural başına positive/negative örnek, testler çalıştırır). Kategoriler: `BUY_SELL`, `PRICE_TARGET`, `CERTAINTY`.
  `alt`, `talep`, `satış`, `alınan`, `satın alma gücü`, `BUY_AND_HOLD`, `buyback`, `Garanti Bankası` gibi masum ifadeler testle korunur.
* **Alıntılanan çürütme muafiyeti** (Soru 5 modelin "kesin yükselir iddiası doğrulanmamıştır" demesini bekler). Cümledeki kalıplar yalnızca **tümü** uygunsa muaf (`QUOTED_REFUTATION` notu):
  cümlede olumsuzlanmamış, tırnak dışı bir çürütme/reddetme işareti var **ve** her kalıp şunlardan birini sağlıyor: tırnak içinde; ardından "iddia/ifade/söylem"; ≤4 sözcük yakınında *reddetme* işareti
  ("hedef fiyat veremem", "garanti değildir"). AL/SAT kalıpları yalnızca tırnak içindeyse muaf. Aynı cümlede tırnaksız ikinci bir tavsiye varsa cümlenin tamamı ihlaldir.
  `doğrulanmamış değil` (olumsuzlanmış çürütme), tırnak içine gizlenmiş çürütme, başka cümledeki çürütme, `Alın, doğrulanmamış iddialara bakmayın` gibi saldırılar testlidir.
* **Çürütme sözcükleri ve iddia/ifade/söylem varyantları** da veridir (`advice_phrases.json`: `refutation_markers`, `claim_nouns`, her girişte `examples`): `doğrulanmamıştır/-maktadır/doğrulanamamıştır/doğrulanmadı`,
  `kanıtlanmamıştır/…`, `desteklenmemektedir/desteklenmiyor`, `asılsızdır/dayanaksızdır`, `kanıt yoktur`; `iddiası/iddiaları/iddiasının`, `ifadesi/ifadesinin`, `söylemi/söyleminin` …
  Her varyant × her sözcük için muafiyet, olumsuzlama, onaylayan sözcük, uzak sözcük, ikinci tavsiye ve başka cümle saldırıları testlidir.
* **ASCII/büyük harf katlama:** Türkçe kalıplar ve metin aynı katlamadan geçer (`tr_fold`: küçük harf + ç→c, ğ→g, ı→i, ö→o, ş→s, ü→u). `KESIN YUKSELIR`, `KESİN YÜKSELİR`, `IDDIASI`
  aynı eşleşir; model ASCII/büyük harfle yazarak kalıbı atlatamaz. Bedel: `alin`/`satin` gibi ASCII yazımlar da yakalanır (masum ifadeler ASCII biçimleriyle de testlidir).
* **Sınırlar:** çürütme sözcüğü tek başına (`kesin yükselir, doğrulanmamıştır`) muafiyet vermez; ironi/dolaylı tavsiye ("bence düşünmeye değer") yakalanmaz; nedensellik iddiası
  ("iyi bilanço = fiyat artar", kural 10) bu modülün kapsamında değildir.

## 10. Açık noktalar
* Hocadan teyit: `run_backtest` yalnızca catch-up'ta mı zorunlu (bölüm 3).
* `RISK_GATE` ve `BUILD_EVIDENCE` için `tools/check_data_quality.py` henüz yok; kapı şimdilik mock. Gerçek kapıyla `analysis_bundle` ve
  `hard_blocks` alanlarının davranışı yeniden test edilmeli.
* **Karar (2026-11-21, kodlanmadı):** `find_support_resistance` gerçek araç olunca seviye alanları (en yakın destek/direnç ve mesafeleri) `evidence_headlines.json`'da **başlık** (committed) olacak;
  kalan seviye listesi bağlamda kalır. O zamana dek araç mock olduğundan `levels` bağlamdadır.
* **Kapı `INVESTIGATE` tanımı:** `tools/check_data_quality.py` henüz yok ve `docs/data_dictionary.md`'de `INVESTIGATE` kapı sonucunun tanımı yok
  (`tools/price_quality.py::gate_from_issues` yalnızca PASS/PASS_WITH_WARNINGS/HARD_BLOCK üretir; "INVESTIGATE/ANALYSIS_UNSAFE ayrımını tam araç ekleyecek" notu var).
  Politika (G3) şu varsayımla yazıldı: kapı INVESTIGATE = **aday eylem yasak**. Bilgisayar 1 farklı tanımlarsa G3 yeniden gözden geçirilir.

## 11. Etiket politikası (`harness/label_policy.py`)
**İlke:** kural kodda, model açıklar. Harness, kilitli kanıt paketinin kaynak zarflarından ve kapı sonucundan izinli etiketi **deterministik** hesaplar (`decide_label`, oturum için `decide_session`);
eylem koruması modelin etiketini politikanınkiyle karşılaştırır (`check_final_output(metin, required_action=decision.label)` -> `ACTION_MISMATCH_REQUIRED`).
Eğitim verisi, değerlendirme ve canlı test AYNI politikayı kullanır. Politika model çağırmaz, ağ kullanmaz, girdiyi değiştirmez; aynı girdi aynı çıktıyı (sıra bağımsız) verir.
Çıktı (`PolicyDecision`): `label`, `rule_id`, senaryo kararları, `reasons[]` (kod + mesaj), `checks[]` (her kural kontrolünün gerçek değeri, eşiği, kaynak araç/hash/alan yolu) ve `trace`.
Eşikler `harness/settings.py` (`POLICY_*`) ve `config.settings` (`MIN_EVENTS`, `MIN_OOS_EVENTS`) içindedir; getiriye bakılmadan seçildi, sonradan sonuçlara bakılarak değiştirilmez.

| Eşik | Değer | Kaynak |
|---|---|---|
| İsabet oranı marjı (bazın üstü) | +5,0 pp | `POLICY_HIT_MARGIN_PP` |
| Geçen ufuk sayısı (aday için) | en az 2 | `POLICY_MIN_PASSING_HORIZONS` |
| Peer grubu | >= 3 | `POLICY_MIN_PEERS` |
| Tamamlanmış olay | >= `MIN_EVENTS` (20) | `config.settings` (çağrı anında okunur) |
| OOS olay sayısı | >= `MIN_OOS_EVENTS` (5) | `config.settings` |
| Güncel sinyal (teknik) | son olay <= 3 iş günü önce (hafta sonu hariç, resmi tatiller sayılmaz) | `POLICY_SIGNAL_RECENCY_TRADING_DAYS` |
| Açıklanmış çeyrek (temel) | >= 4, **GEÇİCİ** | `POLICY_MIN_QUARTERS` |

### 11.1 Genel öncelik
| Kural | Koşul | Etiket |
|---|---|---|
| `G1_GATE_UNSAFE` | kapı `HARD_BLOCK` / `ANALYSIS_UNSAFE` | `ANALYSIS_UNSAFE` |
| `G2_GATE_MISSING` | kapı sonucu yok / bilinmiyor | `INVESTIGATE` (güvenli varsayılan) |
| `G3_GATE_INVESTIGATE` | kapı `INVESTIGATE`: **yalnızca aday etiketler** (`POTENTIAL_CATCH_UP_CANDIDATE`, `TECHNICAL_REVERSAL_CANDIDATE`, `FUNDAMENTAL_IMPROVEMENT_CANDIDATE`) `INVESTIGATE`'e düşer; `HOLD`/`WATCH`/`REJECT_SIGNAL` aynen geçer. Senaryo bazında, birleştirmeden ÖNCE uygulanır | `INVESTIGATE` |
| `G5_COMBINE` | senaryo etiketlerinin birleşimi: **en temkinli kazanır** `ANALYSIS_UNSAFE > INVESTIGATE > REJECT_SIGNAL > WATCH > HOLD > aday etiketler` | en temkinli |
| `G5_CANDIDATE_VS_REJECT` | aynı (bilinen) özne için aday ile `REJECT_SIGNAL` çelişiyor | `INVESTIGATE` |
| `G5_DIFFERENT_CANDIDATES` | yalnızca aday etiketler kaldı ve birden çok FARKLI aday var | `WATCH` |
| `G6_ADVICE_CAP` | soruda al/sat/hedef fiyat isteği (tavsiye niyeti): aday etiketler ve `HOLD` -> `WATCH`. `ANALYSIS_UNSAFE`, `INVESTIGATE`, `REJECT_SIGNAL`, `WATCH` aynen geçer | `WATCH` |
| `G7_NO_SCENARIO` | senaryo aracı çıktısı yok (örn. yalnızca makro/veri) | `INVESTIGATE` |
| `G7_UNVERIFIED_CLAIM` | senaryo yok ve soruda doğrulanmamış kesinlik iddiası var ("kesin yükselir", garanti) | `INVESTIGATE` |

Senaryo, modelin BAŞARIYLA çağırdığı araçlardan türetilir (`routing.py` ile aynı ilke). Aynı araçtan birden çok zarf varsa her biri ayrı senaryodur.
**Aday etiketlerde** `reasons` içinde `CANDIDATE_CAVEAT` ("tarihsel gözlem, örnek küçük, belirsizlik var; gelecek getiri garantisi değil") **zorunludur**.
İsabet oranının standart hatası `100*sqrt(p(1-p)/n)` yalnızca **bilgi** olarak `checks`'e yazılır (`h<ufuk>.hit_rate_se_pp`), kural değildir.

### 11.2 Catch-up (`rank_sector_relative_strength` + `run_backtest`)
Özne: soruda TEK hisse varsa o, aksi halde sıralamadaki en çok geride kalan. Ufuk bazında "geçti": olay >= `MIN_EVENTS` **ve** isabet - baz >= +5 pp **ve** maliyet sonrası ortalama > 0
(tüm örneklem, IS ve OOS) **ve** IS/OOS dolu (OOS olay >= `MIN_OOS_EVENTS`) **ve** `oos_degradation_flag` True değil. Backtest: aynı sinyal türü (`CATCH_UP`) ve evrende özne; birden çok varsa EN TEMKİNLİ birleşim.
| Sıra | Kural | Koşul | Etiket |
|---|---|---|---|
| 1 | `C1_PEERS_OR_STRENGTH` | `insufficient_peers`, peer < 3, `sector_strength` None ya da özne sıralamada yok | `INVESTIGATE` |
| 2 | `C2_NOT_LAGGARD` | özne `is_laggard` değil (sinyal koşulu oluşmadı) | `HOLD` |
| 3 | `C3_FEW_EVENTS` | herhangi bir ufukta tamamlanmış olay < `MIN_EVENTS` (ya da ufuk bloğu yok) | `INVESTIGATE` |
| 4 | `C4_REJECT_HISTORY` | ufukların ÇOĞUNDA isabet bazın altında **ya da** herhangi bir `oos_degradation_flag` True **ya da** backtest `oos_degradation_flag` True | `REJECT_SIGNAL` |
| 5 | `C6_VALIDATION_MISSING` | OOS yok / OOS olay < `MIN_OOS_EVENTS` ("OOS doğrulaması yapılmadı") **ya da** uygun backtest yok / TEST dilimi yok / `low_signal_flag` | `INVESTIGATE` |
| 6 | `C5_CANDIDATE` | `STRONG` sektör, laggard, >= 2 ufuk geçti, backtest TEST dilimi net getiri - benchmark > 0, kapı `PASS`/`PASS_WITH_WARNINGS` | `POTENTIAL_CATCH_UP_CANDIDATE` |
| 7 | `C7_WATCH` | diğer (karışık kanıt, sektör `STRONG` değil, yetersiz geçen ufuk, backtest benchmark'ı geçmiyor) | `WATCH` |
| 6S | `C5S_SUBJECT_CAP` | `C5` aday oluştu **ve** G3'ten sonra hâlâ adaysa: özne bazlı tutarlılık denetimi başarısız (aşağıda) | `WATCH` |

**Özne sınırı (şema 1.2.0 `per_ticker`; karar):** havuzlu kanıt ANA kalır (`C3`/`C4`/`C5` havuzlu bloklardan); hisse bazlı veri yalnızca **tutarlılık denetimidir**. Aday etiket `WATCH`'a iner (`raw_label` aday kalır, G6 ile aynı desen) eğer:
* ufuk bazında **en küçük tamamlanmış olay sayısı** (`per_ticker[özne].per_horizon[*].block.full.n_events_complete`) < `MIN_OOS_EVENTS` (5; mevcut ortak sabit, yeni eşik yok) — `SUBJECT_FEW_EVENTS`. `n_independent_events` değil: isabet oranları tamamlanmış olaylardan hesaplanır;
* özne kendi isabeti kendi taban isabetinin altında olan ufuklar **çoğunlukta** (`below*2 > n`, `C4` ile aynı kural; eşit ya da isabet `None` "altında" sayılmaz) — `SUBJECT_BELOW_BASELINE`;
* `per_ticker` yok ya da özne içinde yok (1.1.0 zarfı) — `SUBJECT_BELOW_BASELINE` yerine `SUBJECT_BREAKDOWN_MISSING`: doğrulanamadı, aday verilmez.

**Sıra:** `C3` → `C4` → `C6` → `C5` → G3 → özne sınırı. Sınır yalnızca G3'ten sonra hâlâ aday olan etikete uygulanır; aksi halde kapı `INVESTIGATE` iken aday `WATCH`'a (daha az temkinli) inerdi. `C2`, `C3`, `C4`, `C6`, `C7` ve G3 sonuçları DEĞİŞMEZ.
`SUBJECT_EVENT_COUNT` (bağımsız olay, ham hisse-günü, en küçük tamamlanmış olay) kırılımı olan her özne için reasons'ta yazılır; checks: `subject_independent_events` (bilgi), `subject_min_events_complete`, `subject_horizons_below_baseline`.
Hisse bazlı bloklarda IS/OOS yoktur (9–21 olay bölünemez): bu denetim yalnızca tüm örneklemdir; IS/OOS doğrulaması havuzlu blokta kalır. **Alternatif reddedildi:** özne sayısını ana kanıt yapmak (`MIN_EVENTS`=20) gerçek MAVI'de havuzlu OOS bozulmasından gelen `REJECT_SIGNAL`'i `INVESTIGATE`'e çevirirdi.

**Gerçek retail (as_of 2026-09-10, `split_date=2026-01-01`, kapı `PASS_WITH_WARNINGS`):** etiketler değişmez: BIMAS `HOLD` (C2), MGROS `HOLD` (C2), MAVI `REJECT_SIGNAL` (C4). Özne sayıları (zarftan): BIMAS bağımsız 9 / ham 43, MAVI 21 / 227 (ufuk bazında tamamlanmış 20), MGROS 14 / 128.
VARSAYIMSAL test (özne geride, havuz doğrulaması ve backtest geçmiş, sektör STRONG; özne sayıları gerçek): BIMAS aday kalır (0/3 ufukta bazın altında), MAVI aday kalır (1/3), MGROS `WATCH` (2/3: 10g ve 20g).

### 11.3 Haftanın günü (`test_weekday_pattern`)
`AllowedAction`'da haftalık örüntü için aday etiketi yoktur; en olumlusu `WATCH`.
| Kural | `stability_verdict` | Etiket |
|---|---|---|
| `W1_STABLE` | `STABLE` | `WATCH` |
| `W2_INSUFFICIENT` | `INSUFFICIENT_DATA` | `INVESTIGATE` |
| `W3_UNSTABLE` | `UNSTABLE` (IS anlamsız, OOS işaret dönüşü, maliyet sonrası <= 0, isabet düşük, etki küçük) | `REJECT_SIGNAL` |

### 11.4 Teknik dönüş (`detect_reversal_events` + `run_backtest`)
Birincil grup koşulsuz `single_indicator`; birleşik gruplar yalnızca betimseldir (çoklu test riski), etiketi belirlemez. Ufuk/backtest koşulları catch-up ile aynı (`REVERSAL` sinyal türü).
| Sıra | Kural | Koşul | Etiket |
|---|---|---|---|
| 1 | `T0_NO_PRIMARY_GROUP` | koşulsuz grup yok | `INVESTIGATE` |
| 2 | `T6_NO_EVENTS` | geçerli taramada hiç olay yok (`n_events_detected = 0`); `T1`'in ÖNÜNDE (olay yoksa "az olay" değil "sinyal yok") | `HOLD` |
| 3 | `T1_FEW_EVENTS` | herhangi bir ufukta tamamlanmış olay < `MIN_EVENTS` | `INVESTIGATE` |
| 4 | `T2_REJECT_HISTORY` | ufukların çoğunda isabet bazın altında ya da OOS bozulması (tarama ya da backtest) | `REJECT_SIGNAL` |
| 5 | `T4_VALIDATION_MISSING` | OOS / backtest eksik (C6 ile aynı) | `INVESTIGATE` |
| 6 | `T3_CANDIDATE` | güncel sinyal (son olay <= 3 iş günü) **ve** >= 2 ufuk geçti **ve** backtest TEST farkı > 0 | `TECHNICAL_REVERSAL_CANDIDATE` |
| 7 | `T5_WATCH` | diğer (güncel sinyal yok / karışık) | `WATCH` |

### 11.5 Temel veri (`calculate_fundamental_change`) — GEÇİCİ eşikler
> **F1–F4 ve `POLICY_MIN_QUARTERS` geçicidir.** Çeyreklik veri azdır (2025 sonrası ~6 çeyrek; `MIN_EVENTS=20` ulaşılamaz). Gerçek bilanço verisi gelince eşikler gözden geçirilecek;
> kararlar `ScenarioDecision.provisional=True` ve `THRESHOLDS_PROVISIONAL` gerekçesiyle işaretlenir.

İyileşme metriği ve baz (`YOY`/`QOQ`) araç çıktısından gelir; ikinci ana metrik `NET_DEBT_EBITDA` (varsa). Fiyat tepkisi (`reaction_summary`) yalnızca bilgidir, kural DEĞİLDİR (nedensellik iddiasından kaçınmak için; dok. §14).
| Kural | Koşul | Etiket |
|---|---|---|
| `F1_INSUFFICIENT` | açıklanmış çeyrek < 4, son çeyrek TMS 29 karşılaştırılabilir değil, iyileşme metriği son çeyrekte yok | `INVESTIGATE` |
| `F2_REJECT` | iyileşme metriği `DETERIORATED` ve ikinci metrik yok ya da `DETERIORATED` | `REJECT_SIGNAL` |
| `F3_CANDIDATE` | iyileşme metriği `IMPROVED` ve ikinci metrik `DETERIORATED` değil, kapı geçer | `FUNDAMENTAL_IMPROVEMENT_CANDIDATE` |
| `F4_WATCH` | diğer (düz/belirsiz yön, metrikler çelişiyor) | `WATCH` |

### 11.6 `split_date` kuralı (araç kullanımı ve eğitim verisi)
Aday etiket IS+OOS doğrulaması ister. Model çağrılarında OOS başlangıcı HER ZAMAN **as_of yılının 1 Ocak'ı** ya da **sorudaki OOS başlangıcı**dır (`split_date`; haftalık örüntüde `out_of_sample_start`; backtest'te
`strategy.train_end` = OOS başlangıcından bir gün önce). Eksikse politika `INVESTIGATE` verir ve gerekçe "OOS doğrulaması yapılmadı"dır. Kural MCP araç açıklamalarına, `docs/tool_usage_guide.md`'ye ve
`training/RULES.md`'ye yazıldı.

### 11.7 Gerçek örnek: retail, as_of 2026-09-10 (kapı `PASS_WITH_WARNINGS` varsayımı)
Gerçek `tools.rank_sector_relative_strength` çıktısı. MAVI geride kalan (`lag_score_pp` -3,2452 <= -3,0), peer 3, sektör -1,81% vs XU100 +1,85% = -3,66 pp -> `WEAK`; tamamlanmış olay 43.
| Ufuk | isabet | baz | fark | maliyet sonrası ort. (tümü) |
|---|---|---|---|---|
| 5g | 46,51 | 49,67 | **-3,16** | -0,68 |
| 10g | 48,84 | 50,56 | **-1,72** | -0,89 |
| 20g | 48,84 | 48,72 | **+0,12** (marj +5 pp değil) | +0,66 |

* `split_date` YOK: IS/OOS ve `oos_degradation_flag` None. Etiket **`REJECT_SIGNAL`** (`C4_REJECT_HISTORY`): 3 ufkun 2'sinde isabet bazın altında. `C4`, `C6`'dan ÖNCE geldiği için OOS eksikliği reddi engellemez.
* `split_date=2026-01-01`: OOS isabet %40,0 (5/10/20g), OOS maliyet sonrası ort. -1,34 / -2,09 / -0,88, 20g'de `oos_degradation_flag=True`. Etiket yine **`REJECT_SIGNAL`**, iki bağımsız gerekçeyle.
* Gerçek kapı aracı (`tools/check_data_quality.py`, Bilgisayar 1) gelince bu örnek yeniden koşulmalı: `tests/harness/test_label_policy.py::test_real_retail_with_the_real_gate_tool` şimdilik atlanır (dosya yok), araç gelince otomatik çalışır.

### 11.8 Bilinen sınırlar
* Catch-up istatistikleri peer havuzludur (hisse bazlı kırılım `docs/schema_wishlist.md` §1.1); politika havuzlu `n_events_complete`/isabet ile karar verir, özne hissenin kendi olayı daha azdır.
* Özne `decide_session`'da yalnızca soruda tek evren hissesi varsa belirlenir; kanıt paketi yalnızca en çok geride kalan hisseyi (`laggard`) taşır, özne açıkça başka bir hisseyse onun `is_laggard`/lag değeri committed kanıtta bulunmaz (politika zarftan okur).
* Güncel sinyal için resmi tatiller sayılmaz (iş günü = hafta içi).
* Birden çok backtest uygulanabilirse en temkinli birleşim kullanılır (TEST farkı en küçük, bayraklardan herhangi biri).
* `proposed_action` (kanıt paketi): kapı `INVESTIGATE` iken artık eylem ZORLANMAZ (`None`); yalnızca `HARD_BLOCK`/`ANALYSIS_UNSAFE` -> `ANALYSIS_UNSAFE`. Asıl etiket politikadandır.

## 12. Nihai çıktı denetimi ve oturuma bağlama (`final_check.py`, `HarnessSession.submit_final`)
**Akış.** Model açıklama ister (`request_explanation`) -> nihai metni `submit_final(metin)` ile verir -> `check_final` sayı doğrulayıcı (`verify_session`), eylem koruması
(`check_final_output`) ve politika etiketini (`decide_session`) tek raporda toplar. Metin yalnızca geçerse `complete_explanation` çağrılır.

**Ölçüm ve zorlama ayrı.** Ölçüm her profilde (A–E) aynı değerlendiriciyle yapılır; zorlama (yeniden deneme, güvenli geri çekilme, `required_action`) yalnızca profilde `enforce_final_check` açıksa.
Bayraklar `profiles.py`'de veridir; A–E'yi aynı ölçüyle karşılaştırabilmek için böyle yapıldı.

| Bileşen | A | B | C | D | E | (D′) |
|---|---|---|---|---|---|---|
| Araçlar modele açık | – | ✓ | ✓ | ✓ (13) | ✓ (13) | ✓ (13) |
| `as_of` ve şema doğrulaması | – | ✓ | ✓ | ✓ | ✓ | ✓ |
| Durum sırası + zorunlu adım (model çağırır) | – | – | ✓ | ✓ | ✓ | ✓ |
| Kapı ve kanıt paketini harness çalıştırır | – | – | – | ✓ | ✓ | ✓ |
| Kanıt kilidi + güvenli hata yolu | – | – | – | ✓ | ✓ | ✓ |
| İnsan incelemesi | – | – | – | – | ✓ | – |
| Nihai çıktı **ölçümü** (sayı + eylem + politika uyumu, rapor) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Nihai çıktı **zorlaması** (yeniden deneme, geri çekilme, `required_action`) | – | – | – | ✓ | ✓ | ✓ |
| Sayı doğrulayıcı 2. seviye (kilitli kanıt) | – | – | – | ✓ | ✓ | ✓ |
| Politika etiketi + gerekçe modele **gösterilir** | – | – | – | ✓ | ✓ | – |

D′ = D, ama etiket/gerekçe gösterilmez (yalnızca denetlenir + yeniden deneme). `EXTRA_PROFILES`'te durur, A–E'ye girmez; **deney şimdilik koşulmaz**, yalnızca bayrak hazırdır.
A'da kapı yok, B'de modelin kapıyı çağırması şart değil: politika kapı sonucu olmadığında `INVESTIGATE` (G2) üretir; A–B'de "politika uyumu" bu temkinli etikete karşı ölçülür.

> **Raporlama notu (karar):** D/E'de etiket doğruluğu büyük ölçüde **harness'ten** gelir (politika etiketi modele verilir, `required_action` ile zorlanır, geçmezse harness'in kendi etiketi yazılır). Bu doğruluk **model başarısı diye raporlanmaz**;
> modelin payı açıklamanın kanıta sadakati (sayı halüsinasyonu, tavsiye dili, gerekçenin etikete uyumu) ve A–C'deki kendi etiketidir.

**Politika bloğu** (`render_policy_block`): izinli etiket, kural kimliği, kapı sonucu, gerekçe kodları ve metinleri. Gerekçe metinlerinde geçen eşik sayıları (`MIN_EVENTS (20)`, `< 4` çeyrek) araç çıktısında olmadığından
modelin alıntısı `HALLUCINATION` sayılmasın diye sayı doğrulayıcıda **`ALLOWLISTED_POLICY`** olur (ayrı sayılır, paydaya girmez; araç kanıtı önce gelir). D′ ve A–C'de blok yoktur, özellik kapalıdır.

**Deneme.** `settings.FINAL_MAX_RETRIES = 2` (`HARNESS_FINAL_RETRIES` ile ezilir) => en çok 3 deneme. İhlalli denemede modele Türkçe geri besleme gider (uydurma sayı + `derivation_hint`, tavsiye ifadesi ve cümlesi, eylem sorunu, gerekli son satır).
Hak bitince **güvenli geri çekilme**: sayı ve tavsiye dili içermeyen sabit metin (`fallback_text`, kendisi denetimden geçer), etiket = politika etiketi (güvenli hata yolunda `ANALYSIS_UNSAFE`). A–C'de zorlama olmadığı için geri çekilme yoktur;
metinde çözümlenebilir etiket yoksa makineyi kapatmak için `INVESTIGATE` yazılır ve `ACTION_DEFAULTED` olayıyla `action_source="defaulted"` işaretlenir (ihlal `NO_ACTION` olarak yine sayılır).

**İhlal sayımı iki düzeyde** (`session.final_metrics()`, `FINAL_DELIVERED` olayı):
* *deneme düzeyi:* her denemedeki ihlaller (`by_code`, `by_source`, `n_hallucinated`) — yeniden denemeyle düzelse de sayılır; modelin kural ihlali eğilimidir. Olay: `RULE_VIOLATION level=attempt`.
* *teslim düzeyi:* teslim edilen metindeki ihlaller. D/E'de zorlama sonrası 0 olmalıdır (geri çekilme metni de denetlenir); A–C'de modelin ham çıktısının ihlalleridir. `fallback`, `action_source`, `policy_match` ile birlikte.

**Bilinen sınırlar.** `UNEVIDENCED` yalnızca not (ihlal değil). Politika bloğu kanıt eşiklerini (`+5 pp` marjı vb.) göstermez; model bunları alıntılarsa `HALLUCINATION` sayılır (gerekçe metinlerinde geçmiyorsa).
Aday etiketlerde `CANDIDATE_CAVEAT` notunun metinde bulunması bu aşamada zorlanmaz (eğitim verisi kuralı 7, `training/RULES.md`).

## 13. Model arayüzü (`llm_backend.py`) ve orkestratör (`agent_loop.py`)
**`LLMBackend.chat(messages, tools) -> ModelReply`** (metin ve/veya araç çağrıları). `ScriptedBackend` testler için betikli sahte modeldir (adım: metin, `ModelReply` ya da
`(mesajlar, araçlar) -> yanıt` fonksiyonu; betik bitince `ScriptExhausted`). `OllamaBackend` yerel Ollama'ya `/api/chat` ile konuşur (akış yok, `urllib`).
* **Yalnızca localhost:** adres `localhost`, `127.0.0.1`, `::1` ya da loopback IP olmalı (kimlik bilgisi, yol, dış ana makine, `localhost.evil.com`, `127.0.0.1@evil.com` reddedilir);
  yönlendirme izlenmez, `HTTP_PROXY` gibi ortam proxy'leri yok sayılır. `urllib` yalnızca bu dosyada geçer, hiçbir yerde bulut AI SDK'sı yok (ikisi de testli; CLAUDE.md kural 3-4).
* **Ayarlar** `harness/settings.py` (`config/` ortak olduğu için): model adı (`HARNESS_MODEL`; adı YER TUTUCUDUR, temel model kararı ekibindir), sıcaklık 0 (`HARNESS_TEMPERATURE`),
  bağlam sınırı (`HARNESS_NUM_CTX`), seed = `config.settings.RANDOM_SEED`, adres (`HARNESS_OLLAMA_HOST`).
* **Bağlam sınırı sessizce kırpılmaz:** Ollama sınırı aşan istemi kırpar (sistem istemi kaybolabilir). `prompt_eval_count >= num_ctx` ise `ContextLimitExceeded` fırlatılır.
  **Ölçüm:** 13 araç şeması ~23 bin karakter, Q1/Q3 oturumunun mesajları 10-12 bin karakter => ~11-12 bin token (3 karakter/token yaklaşığı, gerçek tokenizer değil); varsayılan bu yüzden 16384.

**Orkestratör protokolü** (`run_session`; `session.py` model bilmez): model araç çağırır; araç çağrısız metin "hazırım" sayılır. `request_explanation` reddedilirse eksik adım modele bildirilir ve döngü sürer.
* **D/E:** harness politika bloğunu + nihai biçim istemini verir; model nihai metni (araçsız) yazar. İlk metin taslaktır ve kullanılmaz.
* **A–C ve D′:** araç çağrısız ilk metin doğrudan nihai metindir (blok yok).
* `submit_final` RETRY ise geri besleme modele gider; ACCEPTED/FALLBACK/RECORDED ise oturum kapanır (insan incelemesi `PENDING_HUMAN_REVIEW` kalır).
* **Durdurma:** tur sınırı (`AGENT_MAX_TURNS = 40`) ya da model hatası => `LOOP_ABORTED`; zorlama açık profilde ve açıklama aşaması mümkünse (yan etkisiz `peek_explanation` ile bakılır, geçersiz çağrı sayacı şişmez)
  güvenli geri çekilme teslim edilir; mümkün değilse (zorunlu adım eksik) ya da A–C'de teslim edilen metin yoktur.
* İstem biçimi `SYSTEM_PROMPT_VERSION` ile sürümlenir: **fine-tune eğitim kayıtları çıkarımdaki istemle (sistem istemi, `HAZIR` sinyali, politika bloğu, nihai biçim istemi) aynı biçimde olmak zorundadır.**

**Uçtan uca testler** (`tests/harness/test_e2e_sessions.py`): 5 örnek soru, gerçek v2 araçlar (`get_stock_history`, `get_index_history`, `calculate_indicators`, `rank_sector_relative_strength`, `check_data_quality`) + mock'lar.
Karma oturumda **gerçek kapı mock zarfı `DATA_VERSION_MISMATCH` ile işaretler**: ilk kapı (yalnızca gerçek veri) `PASS_WITH_WARNINGS`, son kapı `INVESTIGATE` olur; paket mock damgası taşır ve eğitime girmez.
Q1'de etiket yine `REJECT_SIGNAL` (G3 yalnızca aday etiketleri düşürür). Karma oturumda aday etiket üretilemez; aday yolu mock-only birim testlerinde (`test_label_policy.py`) sınanır.

### 13.1 Eğitimden ÖNCE dondurulacak biçimler (`SYSTEM_PROMPT_VERSION = "2"`, henüz DONDURULMADI)
Fine-tune kayıtları çıkarımdaki istemle birebir aynı olmak zorundadır. Aşağıdaki biçimler **eğitim verisi üretilmeden önce dondurulacaktır**; dondurulana kadar değişebilir ve her değişiklikte
`SYSTEM_PROMPT_VERSION` artırılır (eğitim kaydı hangi sürümle üretildiğini taşır). Kaynak: `agent_loop.py` (`build_system_prompt`, `FINAL_INSTRUCTION`, `TOOLS_CLOSED`), `final_check.py` (`render_policy_block`, `build_feedback`).

| Aşama | Mesaj dizisi (rol: içerik) |
|---|---|
| **1. Araç aşaması** | `system`: `build_system_prompt` (rol, 4 kural, nihai çıktı biçimi + izinli etiketler, profilde araç varsa `ARAÇ KULLANIMI` paragrafı: as_of, varsayılanlar, OOS kuralı; D/E'de `HAZIR` sinyali cümlesi) → `user`: soru (aynen) → `assistant`: `tool_calls` → `tool`: zarf JSON'u (`sort_keys`, `ensure_ascii=False`) ya da hata nesnesi (`INVALID_TOOL_CALL` / `HARNESS_ERROR` / `SAFE_FAILURE`) → … Araç tanımları (13 araç; D/E'de kapı ve kanıt paketi yok): `harness/tool_view.py` görünümü (kısa description, sadeleştirilmiş şema, gizli gelişmiş parametreler; bkz. 13.2). **Gemma 3 için araçlar ayrı bir alanda DEĞİL, sistem mesajının sonunda METİN olarak verilir ve çağrılar/sonuçlar metin etiketleriyle taşınır (13.4); eğitim kaydı `harness.text_protocol.encode_messages` çıktısıdır.** |
| **Geçiş** | Model araç çağırmadan metin yazar (D/E'de `HAZIR`). Harness `request_explanation` der; reddedilirse `user`: `Açıklama aşamasına geçilemedi (<kod>): <mesaj>. Eksik adımları araç çağrılarıyla tamamlayın.` |
| **2. Nihai aşama (D/E)** | `user`: `POLİTİKA KARARI (harness hesapladı; eylem etiketi bu olmalıdır):` + `EYLEM: <ETİKET>` + `Kural:` + `Kalite kapısı:` + `Gerekçeler:` (`- KOD: mesaj`) + boş satır + `FINAL_INSTRUCTION` → `assistant`: nihai metin (araç yok, `tools` alanı boş). Son satır `EYLEM: <ETİKET>`. |
| **2. Nihai aşama (A–C, D′)** | Blok ve ek istem yok: araç çağrısız ilk `assistant` metni nihai metindir. |
| **Yeniden deneme** | `assistant`: başarısız metin → `user`: `build_feedback` çıktısı (`Nihai cevabınız kurallara uymadı (deneme n/N)…`, ihlal başına bir satır, son satır `Son satır tam olarak şu olmalı: EYLEM: <ETİKET>`). Nihai aşamada araç çağrısı `TOOLS_CLOSED` ile reddedilir (deneme harcanmaz). |

Eğitim kayıtları için kural (karar): **`training/RULES.md` madde 5 aynen geçerlidir.** Eğitim veri üreticisi açıklamalarda **yalnızca kilitli committed kanıttaki sayıları** kullanır
(`UNEVIDENCED` sayı yok); `warnings` metnindeki ya da kanıta girmeyen sayılar alıntılanmaz. Politika bloğundaki eşik sayıları (`ALLOWLISTED_POLICY`) yalnızca D/E çıkarımında tolere edilir, eğitim açıklamasında kullanılmaz.

### 13.2 Araç tanımlarını kısaltma (yapıldı; `SYSTEM_PROMPT_VERSION = "2"`) ve bağlam bütçesi
`harness/tool_view.py` modele görünen tanımı üretir; MCP sunucusu ve orkestratör AYNI görünümü kullanır, doğrulama tam pydantic şemasıyla kalır (`schemas/` değişmedi).
* **description:** araç başına ≤ 100 karakter (tekrarlanan `as_of` ve OOS paragrafları kalktı; kural system prompt'ta tek kez ve ilgili parametrenin kısa notunda).
* **input_schema:** `$ref` açık, başlık/uzun açıklama/desen/min-maks atılmış, `null` dalı yok. **Gelişmiş parametreler gizli** (`HIDDEN_PARAMS`): maliyet/kayma, gösterge `config`, `price_adjustment`, `include_columns_meta`,
  `forward_horizons`, `analysis_start`, `touch_mode`, `alpha`, `conditioning`, `strategy.{maliyet, signal_params, signal_lag_days, benchmarks, validation_end, walk_forward}`, kapıdaki `checks`/`analysis_bundle` vb.
  Hepsi isteğe bağlıdır ve varsayılanları örneklerle aynıdır (testle denetlenir); gizli alanı model yine de gönderirse tam şema doğrular. Görünen kalanlar: `as_of`, hisse/sektör, tarih aralığı, `split_date` / `out_of_sample_start` /
  `strategy.train_end` (OOS notuyla), `n_tests_declared`, `last_n_rows`, `value_columns`, `event_family`, `condition_sets`, `pattern`.
* **Ölçüm (13 araç, karakter):** 23 739 → **8 334** (~2,8 bin token tahmini; önceki ~7,9 bin). Tahmin karakter/3; **Ollama kurulunca `MODEL_TURN` olayındaki `prompt_tokens` (gerçek `prompt_eval_count`) ile `estimated_prompt_tokens` yan yana okunup `CHARS_PER_TOKEN` düzeltilecek.**
* **Bütçe (hedef ≤ 8192 token, her model turunda, karakter/3):** Q2, Q3, Q4, Q5 uyuyor (tepe ~6,6 bin). **Q1 uymuyor (tepe ~9,5 bin):** gerçek rank zarfı ~13 bin karakter, bunun ~6,5 bini `per_ticker`, ~4 bini `historical_catch_up`.
  Kalan yük artık araç ÇIKTISIDIR, tanımı değil. Bu açık karar `test_each_sample_question_stays_within_the_8192_token_context_target[Q1]` (strict xfail) ile kayıtlıdır; çözülünce test kendiliğinden uyarır.
  Seçenekler (karar bekliyor): (A) modele giden zarf görünümünü kırp (`null` alanlar, `per_ticker` bloklarında yalnızca sayaç/isabet/taban/maliyet sonrası; kanıt ve doğrulayıcı TAM zarfla çalışmaya devam eder);
  (B) bağlamı 12–16 bin tutup yalnızca Q1 tipi sorularda kabul etmek; (C) `per_ticker`'ı rank'te isteğe bağlı parametreyle açmak (şema değişikliği, `schemas/` sahibi onayı).

### 13.3 Şema 1.3.0 uyarlaması ve modele giden zarf görünümü (`SYSTEM_PROMPT_VERSION = "3"`)
* **Kanıt (`evidence_headlines.json` version 4):** SR `levels` artık BAŞLIK (en yakın destek/direnç + yüzde uzaklıkları; §10 kararı); reversal `group_count` ham olay günü ve çakışan ileri pencereyi; backtest yeni `trades`
  bölümünü (kazanan/kaybeden işlem, sinyal gecikmesi, `last_exit_date`) taşır. 1.2.0 zarflarında alanlar `None` olduğundan madde metne eklenmez.
* **Politika T/C kuralları gerçek zarflarla** (`test_policy_real_130.py`): haftalık tarama (2025-09-05 → 2026-11-13, tüm evren): TR: `T2` REJECT 1251, `T5` WATCH 355, `T4` INVESTIGATE 237, **`T3` TECHNICAL_REVERSAL_CANDIDATE 47**;
  retail catch-up: `C2` HOLD 30, `C4` REJECT 28, `C6` INVESTIGATE 5, **`C5` aday 0**. Yani gerçek araçlarla CU adayı hiç oluşmadı (yalnızca sentetik testle sınanır); eğitim verisinde CU adayı örneği olmayacak.
* **Çapraz doğrulayıcı önerisi (Bilgisayar 1'e):** reversal grubunda `n_raw_event_days >= n_events_detected` ve `n_overlapping_forward_windows <= max(n_events_detected - 1, 0)` kuralı şemaya geri eklenebilir:
  harness kurucuları artık tutarlı (`test_builder_invariants.py`) ve GERÇEK zarflarda (3 hisse × 2 aile) kural geçiyor; referans uygulama `reversal_group_problems`.
* **Model görünümü (`harness/model_view.py`):** kanıt, politika ve doğrulayıcı TAM zarfla çalışır; yalnızca `tool` mesajı görünümdür. Null alanlar atılır; modelin kendi çağrısının yankısı (`params`, `input_hash`, `schema_version`, `as_of`, `tool`) atılır;
  rank'te `per_ticker` yalnızca ÖZNE satırı tam (diğerleri özet sayı), `ranking` sıkıştırılır, `view_trimmed` işareti konur. Gerçek retail zarfı ~13,3 bin → ~yarı.
* **Bağlam (hedef ≤ 6000 token, karakter/3):** Q3, Q4, Q5 uyuyor; **Q1 tepe ~7,4 bin, Q2 ~6,3 bin** (strict xfail). Kalan yük araç tanımları (~2,8 bin token) + havuzlu bloklar (rank) ve `per_day` blokları (weekday). Daha fazla kırpmak modelin gördüğü
  sonuçları azaltır (sahibin kararı); bunun yerine **eğitim üreticisi her oturumun gerçek token sayısını (Gemma tokenizer) ölçüp seq len 6144'ü aşanları eler**, canlıda bağlam `num_ctx` ile açılır.

### 13.4 Metin tabanlı araç protokolü (`harness/text_protocol.py`, `TEXT_PROTOCOL_VERSION = "1"`)
Gemma 3'ün Ollama şablonunda yerel araç çağırma yoktur/güvenilmezdir; bu yüzden `OllamaBackend` varsayılan olarak `tool_mode="text"` çalışır (`HARNESS_TOOL_MODE=native` Qwen/Llama gibi destekleyen modeller için):
* **İstem:** `render_tools_block` araç listesini (ad, kısa açıklama, sıkıştırılmış şema) sistem mesajının SONUNA ekler; istek gövdesinde `tools` alanı YOKTUR.
* **Çağrı:** model `<tool_call>{"name": "...", "arguments": {...}}</tool_call>` yazar (bir yanıtta birden çok blok olabilir). **Sonuç:** `user` rolünde `<tool_response name="...">
{görünüm JSON}
</tool_response>`.
  Yalnızca system/user/assistant rolleri vardır; ardışık aynı roller birleştirilir (Gemma şablonu user/assistant alternasyonu ister). Üretim `<tool_response name=` dizesinde durdurulur (`options.stop`): model uydurma araç sonucu yazamaz.
* **Bozuk çağrı** (geçersiz JSON, kapanmamış etiket, `arguments` nesne değil; bir blok bozuksa HİÇBİRİ çalıştırılmaz): istemci `ModelReply.format_error` döner; orkestratör bunu **`MALFORMED_TOOL_CALL` geçersiz araç çağrısı** olarak sayar/loglar ve modele düzeltme mesajı verir
  (nihai aşamada diğer araç çağrıları gibi reddedilir, hak harcanmaz). Markdown çit (```json) etiket içinde tolere edilir.
* **Eğitim = çıkarım:** eğitim verisi biçimlendirmesi `encode_messages(messages, tools)` çıktısını kullanır (tek kod yolu); `chat_template` Gemma'nın kendisidir (Modelfile `TEMPLATE`, training/README.md).
* Gerçek model testi (Bilgisayar 1, Ollama): bu bilgisayarda Ollama yok; istemci yerel bir HTTP sahte sunucusuna karşı sınanır (`tests/harness/test_llm_backend.py`). Model adı varsayılanı `gemma3:4b`; fine-tune sonrası kendi ad.


## 14. v1 eğitim verisi ve değerlendirme hattı (`training/`, `experiments/`)
**Kapsam (karar):** yalnızca GERÇEK araçlar (hisse/endeks geçmişi, göstergeler, destek/direnç, rank, backtest, reversal, weekday) ve şema 1.3.0; kapı ve kanıt paketi harness'te. Modele yalnızca bu 8 araç gösterilir
(`harness/settings.EXPOSED_TOOLS`, oturumda `exposed_tools`). Bilanço/makro/haber/konuşma araçları gerçek olunca eklenir; üreteç artımlıdır (`training/spec.py`, `questions.BUILDERS`, `teacher.plan_calls`, `composer._pick`).

**Soru tipleri (9):** haftanın günü, teknik dönüş (BB alt dokunuş / RSI dibi; ~%30 birleşik koşullu, ~%70 backtest'li, ~%50 taze sinyal gününe kurulu), catch-up (retail), göstergeler, destek/direnç, fiyat geçmişi,
tavsiye/kesinlik (hedef fiyat isteği, "kesin yükselir" iddiası; bir kısmı reversal+backtest'li, G6 ile WATCH), araçta olmayan veri/gelecek (F/K, makro, haber, gelecek fiyat), bayat veri (as_of >= 2027-01-18: gerçek kapı `ANALYSIS_UNSAFE`).
Etiketler her zaman `label_policy`'den; açıklama kilitli kanıt cümlelerinden belirlenimli kurulur (`composer.py`, LLM yok); eşik sayıları ve türetilmiş sayı yazılmaz.

**Bölme (üretimden ÖNCE):** peer grupları bölmelere tek parça (hash sırası): test = telekom, kimya-dışı grupların ~%25'i vb.; tarih aralıkları ayrık (eğitim 2025-03 → 2026-05, doğrulama 2026-06 → 2026-08, test 2026-09 → 2026-11 + bayat aralıklar);
test şablonları (sıra % 4 == 3) eğitimde yok. Retail tek ≥3 üyeli grup: catch-up soruları grup bazında tutulamaz (yalnızca tarih ve şablon). `leakage_problems` hisse, tarih, şablon, metin sızıntısını denetler.

**Hata-kurtarma (%10, deterministik):** `as_of` uyuşmazlığı, bozuk araç çağrısı biçimi, erken bitirme, nihai metin ihlali + geri besleme. Hatalı asistan turu `train_mask`'te False (bağlamda kalır, kayıpta değil).

**Bağlam:** gerçek Gemma tokenizer ile ölçüldü (karakter/3 tahmini JSON ağırlıklı içerikte ~%12 eksik sayıyordu: ~2,7 karakter/token). Model görünümü (`model_view.py`) kanıtın alıntılamadığı uzun listeleri/alanları kırpar;
araç tanımları (`tool_view.py`) 8 araç için ~1,7 bin token. Süzgeç: oturum > 8192 token ise elenir (rapor `dropped`, `too_long_rate_by_type`, `shortfall`).

**Doğrulama hattı (`training/validate.py`) her kayıtta:** etiket = politika; sayı halüsinasyonu 0 ve kanıtsız sayı 0; eylem koruması ihlali 0; tüm zarflar `snap_*_v2` ve şema 1.3.0 (mock yok); geri çekilme yok;
beklenmeyen hata zarfı yok; aday etiketlerde not; nihai metin ilk denemede kabul (kurtarma yörüngelerinde 2.). Veri kümesi: sızıntı 0, tek etiket payı <= %80, yinelenen kimlik yok.

### 14.1 Değerlendirme koşucusu ve hocanın metrikleri (`experiments/eval_runner.py`)
Aynı sorular, profil (A–E) x model (temel/ince ayarlı); her koşu gerçek oturum ve `final_metrics()` ile sayılır. Çıktı: `results.csv` (satır = soru x profil x model x tekrar) + `summary.json`.
| Hocanın ölçütü (CLAUDE.md) | `summary.json` alanı | Not |
|---|---|---|
| Sayısal halüsinasyon | `numerical_hallucination_rate`, `n_hallucinated`, `n_number_claims` | teslim edilen metin; deneme düzeyi `n_hallucinated_attempts` (csv) |
| Hatalı araç çağrısı | `invalid_tool_call_rate` | geçersiz / (geçerli + geçersiz); `MALFORMED_TOOL_CALL` dahil |
| Kanıtsız sonuç | `unevidenced_rate` | araç çıktısında var, kilitli kanıtta yok (yalnızca D/E'de anlamlı) |
| Kural ihlali (tavsiye, zorunlu adım atlama) | `rule_violation_rate_delivered`, `rule_violation_rate_attempts`, `advice_language_rate`, `mandatory_step_skipped_rate`, `fallback_rate` | iki düzey ayrı |
| Etiket uyumu | `action_matches_policy_rate`, `action_matches_expected_rate` | D/E'de büyük ölçüde harness'ten gelir (bölüm 12 notu) |
| Tekrarlanabilirlik | `reproducibility_rate` | `--repeats 2` ile |
| Bağlam | `max_prompt_tokens` | Ollama `prompt_eval_count` |

### 14.2 v1 üretim sonucu (tohum 42; `data/training/v1/report.json`, commit edilmez)
| Bölme | Oturum (hedef) | Etiketler | Hata-kurtarma | Token ort./p95/max |
|---|---|---|---|---|
| eğitim | 600 (600) | INVESTIGATE 372, REJECT_SIGNAL 114, ANALYSIS_UNSAFE 48, HOLD 47, WATCH 12, TECHNICAL_REVERSAL_CANDIDATE 7 | 45 (%7,5) | 4336 / 6106 / 6143 |
| doğrulama | 49 (50) | INVESTIGATE 32, REJECT_SIGNAL 9, ANALYSIS_UNSAFE 4, HOLD 4 | 3 | 4334 / 6107 / 6127 |
| test | 92 (100) | INVESTIGATE 54, REJECT_SIGNAL 23, ANALYSIS_UNSAFE 8, TECHNICAL_REVERSAL_CANDIDATE 4, HOLD 2, WATCH 1 | 8 | 4133 / 5835 / 6096 |
Genel: tek etiket payı **%61,8** (INVESTIGATE) < %80 eşiği, devam edildi. **Eksikler:** test 8 ve doğrulama 1 catch-up oturumu (retail oturumları bağlamı aşıyor: eğitimde 148 catch-up ve 175 reversal adayı `too_long` ile elendi);
`POTENTIAL_CATCH_UP_CANDIDATE` ve `FUNDAMENTAL_IMPROVEMENT_CANDIDATE` verisi YOK (gerçek araçlarla CU adayı hiç oluşmadı; bilanço aracı yok): model bu iki etiketi bu veriden öğrenemez.
`TECHNICAL_REVERSAL_CANDIDATE` yalnızca 7 eğitim örneği (taze sinyal günü hedeflemesine rağmen nadir); `WATCH` 12. Colab hattı doğrulaması (gerçek tokenizer): 0 elenen, eğitilen token payı ~%10.
Eğitim hedefi büyük ölçüde protokol/biçim/ret davranışı (araç çağırma, sayı disiplini, tavsiye reddi, güvenli hata yolu); etiket dağılımı INVESTIGATE/REJECT ağırlıklıdır (negatifler güçlü, adaylar zayıf).

### 14.3 Bağlam 8192 kararı, model görünümü ilkesi ve sınırlamalar
* **Karar:** eğitim `max_seq` 8192, Modelfile `num_ctx` 8192, `LLM_NUM_CTX` 8192, `CONTEXT_TARGET_TOKENS` 8192 (T4 16 GB: batch 1 + gradient accumulation 8). 6144'te catch-up (Soru 1) ve reversal (Soru 3) oturumlarının büyük kısmı eleniyordu
  (ölçüm: catch-up 69/100 ve reversal 46/200 oturum > 6144, hiçbiri > 8192). **OOM geri dönüşü:** 6144 + SIKI MOD (`--max-tokens 6144 --tight`, canlıda `HARNESS_VIEW_TIGHT=1`; training/README.md).
* **Model görünümü ilkesi:** model yalnızca kanıtın ALINTILAYABİLDİĞİ (committed) alanları ve politikanın metinde anlattığı bayrakları görür; tam zarf doğrulayıcıda ve politikada kalır. Ek kırpmalar: haftalık örüntü pencereleri (yalnızca alıntılanan alanlar),
  reversal olayları yalnızca son olay tarihi, geçmiş serilerinde ilk 2 + son 3 satır + en yüksek/en düşük kapanış satırları. **Sınama:** `tests/training/test_view_visibility.py` her tipte nihai metindeki her sayının modelin gördüğü görünümde bulunduğunu doğrular
  (bu test, geçmiş satırı kırpmasının zirve/dip kapanışları gizlediği hatasını yakaladı: "doğru" etiketli ama modele sayı uydurtan örnek).
* **SINIRLAMA — `POTENTIAL_CATCH_UP_CANDIDATE` eğitim verisinde YOKTUR:** gerçek `rank_sector_relative_strength` + `run_backtest` ile taramada (retail, 2025-09 → 2026-11 haftalık) C5 hiç oluşmadı (yalnızca C2 HOLD, C4 REJECT, C6 INVESTIGATE); `FUNDAMENTAL_IMPROVEMENT_CANDIDATE` için bilanço aracı yok.
  Bu etiketler yalnızca sentetik politika testlerinde sınanır. Model bu etiketleri bu veriden öğrenemez; D/E'de etiket harness'ten (politika bloğu) VERİLDİĞİ için canlı sistem bunları yine doğru etiketleyebilir,
  ama bu **model başarısı sayılmaz** (bölüm 12 notu). `TECHNICAL_REVERSAL_CANDIDATE` ve `WATCH` az örnekle temsil edilir. Etiket politikasının kararlarını modelin kendisinin öğrenmesi (A–C) bu veriyle ölçülemez.
* **Artımlı v2:** bilanço/makro/haber araçları gerçek olunca `training/spec.REAL_TOOLS` + `TYPE_SHARES` + `questions.BUILDERS` + `teacher.plan_calls` + `composer._pick` + (varsa) `LABEL_QUOTAS` eklenir; mevcut tiplerin soruları ve tohumları değişmez,
  `GENERATOR_VERSION` artırılıp veri yeniden üretilir (`python -m training.build_dataset`); görünürlük testi yeni araçları da kapsayacak şekilde tip listesine eklenir.
* **v1 yeniden üretim (8192; tohum 42):** 600 / 50 / 100 oturum, **bağlam nedeniyle elenen 0** (tüm tiplerde %0; en uzun 7053 token, p95 ~6,3 bin; Colab hattıyla doğrulandı). Etiketler (toplam 750): INVESTIGATE 460 (%61,3), REJECT_SIGNAL 159, ANALYSIS_UNSAFE 60, HOLD 39, WATCH 19, TECHNICAL_REVERSAL_CANDIDATE 13.
  Eğitimde tip sayıları: Soru 1 tipi (catch-up) **60** (HOLD 31, REJECT_SIGNAL 21, INVESTIGATE 8), Soru 2 tipi (haftanın günü) **108** (REJECT_SIGNAL 59, INVESTIGATE 49), Soru 3 tipi (teknik dönüş) **120**
  (INVESTIGATE 52, REJECT_SIGNAL 42, WATCH 17, TECHNICAL_REVERSAL_CANDIDATE **9**); ayrıca tavsiye 60, gösterge 72, destek/direnç 42, geçmiş 42, araçta olmayan veri 48, bayat veri 48. Doğrulama 50, test 100 (test: catch-up 10, haftanın günü 18, teknik dönüş 20; TR adayı 4).
  Hata-kurtarma: eğitimde 49 oturum (%8,2), maskeli.

### 14.4 v2: bilanço oturumları (Soru 4), veri seti sürümü uygunluğu ve kapsam sınırı (`GENERATOR_VERSION = "2"`)
**Eklenenler.** `spec.REAL_TOOLS` + `get_fundamental_metrics`, `calculate_fundamental_change` (modele gösterilen araç sayısı 8 -> 10; makro YOK). Yeni tip `fundamental` (pay 0,12; diğer tiplerin payları yeniden dağıtıldı: haftalık 0,15, teknik dönüş 0,17, göstergeler 0,10,
destek/direnç 0,06, geçmiş 0,06, tavsiye 0,08; catch-up/araçta olmayan/bayat değişmedi). Soru şablonları Soru 4 biçiminde ("... tüm çeyreklik bilançolarında FAVÖK marjı ve Net Borç/FAVÖK nasıl değişti? Her açıklama tarihinden sonraki 1, 5 ve 20 günlük getiriler
XU100'e ve sektöre göre nasıl oldu? İyileşen çeyrekler daha iyi fiyat tepkisi almış mı?"; ~%38'i "son çeyrek" sorusu; banka hissesi (AKBNK) için ayrı şablon: net faiz geliri + net kâr). Test şablonları (sıra % 4 == 3) yalnızca testte; hisseler peer grubu bazında bölünür (bölme kuralları değişmedi).
`unsupported` tipindeki iki "fundamental" şablon, aracın artık yanıtladığı soruları (FAVÖK/net borç, net kâr/ROE) sormasın diye aracın KAPSAMADIĞI oranlarla (PD/DD, FD/FAVÖK, cari/likidite oranı) değiştirildi.
**İki aşamalı protokol (değişmedi).** Araç aşaması (`LOAD_FUNDAMENTALS`: metrik + değişim çağrıları; kapı ve kanıt paketi harness'in) -> açıklama aşaması (`HAZIR` -> politika bloğu -> nihai metin). Etiket her zaman `label_policy` F1–F4'ten (GEÇİCİ eşikler); öğretmen etiket yazmaz.
**Öğretmen planı.** `get_fundamental_metrics(ticker, as_of)` + `calculate_fundamental_change(ticker, as_of, improvement_metric, improvement_basis)`. Soruda temel belirtilmemişse `QOQ` (YoY için 2024 verisi yok: TMS 29 öncesi alınmaz); sanayide EBITDA_MARGIN/NET_PROFIT_MARGIN, bankada NET_PROFIT.
Soru tarihi, hissenin bilançosunun GÖRÜNÜR olduğu ilk günden (en erken `disclosure_date`) önce olamaz; soruların %70'i mümkünse 4. çeyreğin görünür olduğu tarihten sonraya kurulur (`POLICY_MIN_QUARTERS = 4` öncesi etiket hep F1/INVESTIGATE).
**Model görünümü ilkesi (bilanço).** Model yalnızca kanıtın alıntılayabildiği alanları görür: SON açıklanmış çeyrek (değer, QoQ/YoY değişim, birim, yön, TMS 29 bayrağı), çeyrek sayıları, tepki özeti (ufuk, grup, n, ortalama anormal getiri, isabet, ufku dolmamış dışlanan).
Çeyrek bazlı tepkiler, medyanlar, sektör anormal getirisi, ölçüt tanımı ve veri seti sürüm uyarısı atılır (`view_trimmed: fundamental_view`); açıklama tarihi belirsizliği uyarıları (`YAHOO_APPROX`, `STATUTORY_DEADLINE`: "açıklama tarihi bilinmiyor, yasal süre sonu varsayıldı") modele GİDER.
Sınama: `tests/training/test_view_visibility.py` (tüm tiplerde, bilanço dahil, nihai metindeki her sayı/tarih görünümde) ve `tests/training/test_fundamental_sessions.py`.
**Açıklama.** Kanıt cümleleri (iyileşme metriği, Net Borç/FAVÖK, çeyrek sayıları, 1/5/20 gün tepki özeti: IMPROVED ve NOT_IMPROVED, ikisi de boşsa ALL) + F1–F4 gerekçe cümlesi + sayısız notlar (yasal süre/yaklaşık tarih, dışlanan açıklanmamış bilanço,
ufku dolmamış pencere, TMS 29, yıllıklandırılmış FAVÖK, az çeyrek, banka kümesi) + "nedensellik iddia edilmez" + (aday etikette) tarihsel gözlem notu. Türetilmiş sayı yazılmaz; notlarda rakam yoktur.
**Veri seti sürümü uygunluğu (kural 12'nin bilanço karşılığı).** Zarftaki `data_version` fiyat sürümüdür; bilanço sürümü `HISTORICAL_ONLY: bilanço veri seti fundamentals_YYYY-MM-DD_vN` uyarısında. `harness.mock_tools.assert_training_eligible` bunu regex ile çeker, TAM BİR sürüm ve
`harness.settings.ACCEPTED_FUNDAMENTALS_VERSIONS` (şu an yalnızca `fundamentals_2026-11-23_v1`) içinde olmasını ister; makro için aynı kural `ACCEPTED_MACRO_VERSIONS` (boş: makro zarflı kayıt reddedilir). Kayıtta `versions.fundamentals`; doğrulama hattı kabul dışı sürümü ve
sürümsüz bilanço oturumunu eler.
**Üretim sonucu (tohum 42; `data/training/v2/report.json`, commit edilmez; token sayımı karakter tahmini: gerçek Gemma tokenizer bu makinede yok, Colab'da yeniden süzülür).** Eğitim 600 / doğrulama 50 / test 100 oturum, eksik 0, bağlam nedeniyle elenen 0 (en uzun 7535 tahmini token),
tek etiket payı %57,1 (INVESTIGATE). Etiketler (toplam 750): INVESTIGATE 428, REJECT_SIGNAL 163, ANALYSIS_UNSAFE 60, WATCH 40, HOLD 39, FUNDAMENTAL_IMPROVEMENT_CANDIDATE 10, TECHNICAL_REVERSAL_CANDIDATE 10.
| Bölme | Tipler (bilanço) | Bilanço etiketleri | Bilanço kuralları |
|---|---|---|---|
| eğitim | 72 | INVESTIGATE 30, REJECT_SIGNAL 18, FUNDAMENTAL_IMPROVEMENT_CANDIDATE 10, WATCH 14 | F1 30, F2 18, F3 10, F4 14 |
| doğrulama | 6 | INVESTIGATE 2, WATCH 4 | F1 2, F4 4 |
| test | 12 | REJECT_SIGNAL 5, WATCH 6, INVESTIGATE 1 | F2 5, F4 6, F1 1 |
Diğer tiplerin oturum sayıları (eğitim): teknik dönüş 102, haftalık 90, catch-up 60, göstergeler 60, tavsiye 48, araçta olmayan 48, bayat 48, destek/direnç 36, geçmiş 36 (doğrulama 50, test 100'de orantılı). Hata-kurtarma eğitimde 54 oturum (%9,0), maskeli.
**KAPSAM SINIRI (dürüstlük).** Yahoo bilanço verisinin yalnızca ~%16'sında (159 satırın 25'i) açıklama tarihi eşleşti: bu satırlar `YAHOO_APPROX`, kalanı `STATUTORY_DEADLINE` (görünürlük = dönem sonu + yasal süre; fiyat tepkisine girmez).
Bu yüzden bilanço oturumlarının çoğunda tepki istatistiği YOKTUR: eğitimde 72 oturumun 18'inde tepki özeti n >= 1, 54'ünde "ALL grubu: gözlem 0"; doğrulamada 6'dan 3'ünde, testte 12'den 2'sinde tepki verisi var (tepkisi olan hisseler: TUPRS, EREGL, AKBNK, kısmen BIMAS, TCELL, ASELS).
Eğitim bilanço oturumları AKBNK (10), FROTO (10), ASELS (9) hisselerinde yoğunlaşır; test hisseleri (TURSG, ISMEN, TRALT, TCELL, TTKOM) ve doğrulama hisseleri (ENKAI, GUBRF, ARCLK) tamamen yasal süre görünürlüğüne dayanır. TUPRS (Soru 4'ün hissesi) eğitim bölmesindedir.
`FUNDAMENTAL_IMPROVEMENT_CANDIDATE` yalnızca eğitimde ve 10 örnekle (doğrulama ve testte hiç yok): çünkü 4 çeyrek görünür olmadan etiket F1'dir ve eğitim tarih aralığı (ve 2025Q1/Q2'nin Yahoo'da bulunmaması) F3'ü sınırlar. `POLICY_MIN_QUARTERS = 4` ve F1–F4 GEÇİCİDİR; değiştirilmedi.
Elle KAP CSV'si (TUPRS 2025Q1–2026Q3, kesin tarih/saat) gelince artımlı sürüm (`fundamentals_..._v2`) ve v2.1 veri üretimi yapılacaktır; makro snapshot'ı main'e girince Soru 5 oturumları da artımlı eklenecektir.

### 14.5 Değerlendirme Colab GPU'da koşulur: CPU'da Ollama önek önbelleği sorunu, dayanıklı koşucu, paket ve koşu planı
**Neden CPU değil.** Bilgisayar 1'de GPU yok (Ollama `size_vram: 0`). Ölçüm (2026-11-21): prompt işleme ~27 token/sn; `gemma3:4b` profil A tek soru ~114 sn; profil E (araç döngüsü, ~3,6 bin token, 11 tur) ~245 sn ve llama-server
`GGML_ASSERT` ile çöktü (`MODEL_ERROR`). **Önek önbelleği (prefix cache) sorunu:** araç döngüsünde her tur tüm geçmişi yeniden gönderir; Ollama ardışık isteklerde ortak öneki KV önbelleğinden yeniden kullanır. CPU'da gözlenenler/riskler:
(a) tur süreleri öngörülemez (önbellek isabeti/ıskası süreyi katlar); (b) önbellek isabetinde `prompt_eval_count` yalnızca YENİ işlenen tokenları sayabilir: `max_prompt_tokens` ve `prompt_eval_count >= num_ctx` bağlam denetimi gerçek bağlam uzunluğunu EKSİK görebilir
(bağlam ölçümü önbelleksiz çağrıyla yapılır: `experiments.check_template` raw `/api/generate`, `num_predict=1`); (c) E profilindeki çökme önbellek yoluyla ilişkili bir llama.cpp CPU hatası olabilir, ama kök neden DOĞRULANMADI (hipotez). Sonuç: A–E değerlendirmesi
**Colab GPU'da** (T4/L4/A100) koşulur; Bilgisayar 1'de yalnızca `--n 1` düzeyinde duman testi yapılır.
**Dayanıklı koşucu (`experiments/eval_runner.py`).** Her oturumdan sonra satır `results.jsonl` (tipli; devam için) ve `results.csv`'ye (ekleme, fsync) yazılır; süre log'lanır (`[i/N] model profil soru durum sn, geçen/tahmini kalan dk`). Aynı `--out` ile yeniden başlatınca biten
(model, profil, soru, tekrar) satırları atlanır (`--no-resume` sıfırlar); `--max-runs R` bu çağrıda en çok R yeni oturum koşar (iki Colab oturumuna bölmek için); Ctrl+C/bütçe sonunda `summary.json` (`meta.complete`, `meta.interrupted`) ve tekrarlanabilirlik sütunlu `results.csv` tüm satırlardan yeniden yazılır.
Zaman aşımı `HARNESS_LLM_TIMEOUT` (sn; `settings.llm_timeout()`, varsayılan 300). `experiments/check_template.py` her iki yolda (raw ve sohbet) `num_predict=1` ister (`OllamaBackend(max_new_tokens=1)`); önceden sohbet yolu SINIRSIZ üretiyordu: düzeltildi ve testlendi.
**Colab paketi.** `python -m experiments.colab.make_eval_bundle --out eval_bundle.zip`: repo kodu (harness, schemas, tools, config, training, experiments, scripts) + `data/snapshots/` altında YALNIZCA `LATEST`/`LATEST_FUNDAMENTALS`/`LATEST_MACRO` işaretçilerinin gösterdiği sürümler (v1 ham kaynak gerekmez)
+ `data/training/v2/{test,val}.jsonl` (+ rapor/manifest). `.git`, `.env*`, `.venv`, `__pycache__`, `tests/`, `reports/`, `data/raw`, `*.zip`, `*.gguf` HARİÇ (test: paket açılıp araçlar çalıştırılır). **Boyut:** kod 0,85 MB ham / 0,30 MB zip, snapshot'lar 0,93 / 0,70, sorular 3,60 / 0,20; toplam
5,38 MB ham, **1,21 MB zip** (GGUF dahil değil: Drive'dan ya da yüklemeyle). Notebook `experiments/colab/eval_ollama.ipynb`: GPU + plan, Ollama kurulumu/sunucu (yalnızca 127.0.0.1), paket, temel `gemma3:4b` + ince ayarlı GGUF (`training/ollama/Modelfile`), şablon denetimi, A–E koşusu (sonuçlar Drive'a, devam), indirme.
**Koşu planı (`python -m experiments.colab.plan --gpu T4|L4|A100`).** Süre = prompt/pp + üretim/tg + tur yükü + araç yükü; token yükü v2 test sorularının öğretmen oturumlarından; x1,5 güvenlik payı; hızlar gemma3:4b Q4_K_M için **VARSAYIMDIR** (GPU bu makinede yok; ilk ~6 koşudan sonra `--calibrate results.jsonl` ölçülen süreyi kullanır).
Varsayılan: 39 soru (n=40 orantılı alt küme) x 2 model (gemma3:4b, gemma3-bist) x 5 profil = 390 koşu:
| GPU (varsayılan hız pp/tg tok/sn) | Toplam | Öneri | Toplamı <= 180 dk tutan en büyük --n |
|---|---|---|---|
| T4 (1000 / 30) | ~222 dk | 2 oturum x ~111 dk (`--max-runs 195`) | 30 |
| L4 (1500 / 40) | ~171 dk | 2 oturum x ~86 dk (`--max-runs 195`) | 40 |
| A100 (4000 / 100) | ~86 dk | 1 oturum | 85 (hepsi) |
| CPU (27 / 4, ÖLÇÜM) | ~5441 dk (~91 saat) | pratik değil | 5 soru bile sığmaz |
**Eğitim süresi (ölçüm, Colab T4).** T4 bf16 desteklemediği için Gemma 3 float32 eğitilir: adım başına ~153 sn (8192 bağlam, batch 1, grad accum 8); 75 adımlık 1 epoch ~3,2 saat. GPU seçimi bilinmiyor: eğitim süresi buna bağlı kabul edilir. `training/colab/train_qlora.py` artık kesilebilir:
`--save-steps N` (kontrol noktası), `--checkpoint-dir` (Drive), `--resume` (en son TAMAMLANMIŞ kontrol noktasından), `--max-steps K` (epoch yerine K adım); çıktılar `--out` klasörüne.
**Örnek soruların araç zinciri.** `python -m experiments.sample_runs` -> `docs/sample_runs/` (5 soru, gerçek veri, as_of 2026-09-10; bkz. oradaki README).

