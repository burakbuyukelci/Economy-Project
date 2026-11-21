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
* `committed_evidence_set`: sonucu gerekçelendiren **başlık bölümleri**; ham veri yükleri ve bağlam (haber, rejim kırılımı, destek/direnç) yalnızca `full_evidence_set`'te.
  Hangi bölümün başlık olduğu **veri**dir: `harness/evidence_headlines.json` (araç → `headline` / `context` / `excluded`). Çıkarıcılar her kanıt adayına bir bölüm adı verir;
  bildirilmemiş bölüm bağlam sayılır. `calculate_indicators` için başlık = `latest` (as_of günü değerleri ve durumları); `recent_rows` kasıtlı olarak kanıta HİÇ girmez.
  `tests/harness/test_evidence_headlines.py` çıkarıcı ↔ dosya tutarlılığını (bildirilmemiş ve bayat bölüm adı) denetler.
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
İkisi de **saf fonksiyon**dur (oturum/MCP bağımlılığı yok); oturuma bağlama (`complete_explanation` öncesi çağrı, yeniden deneme) sonraki iştir.
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
