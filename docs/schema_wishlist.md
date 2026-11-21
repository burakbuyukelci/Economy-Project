# Şema 1.2.0 istek listesi (ÖNERİ; uygulanmadı)

> Durum (2026-11-21): **§1, §2, §4, §5 `schema-1.2.0` dalında UYGULANDI** (`docs/schema_1_2_0_plan.md`, `schemas/schema_changelog.md` 1.2.0); main'e birleştirme Bilgisayar 2 uyarlaması sonrası. §3 → §6 (ayrı küçük sürüm), §7 araç yazılırken. Aşağıdaki metin ilk öneridir. Eski durum: **hiçbiri uygulanmadı.** `schemas/` ortak sözleşmedir ve her değişiklik insan onayı gerektirir (`schemas/schema_changelog.md`).
> Bu dosya, araçları yazarken görülen eksikleri toplar; onaylananlar `schemas/schema_changelog.md` içine 1.2.0 olarak taşınır.
> Hepsi **eklemelidir** (varsayılanlı yeni alanlar); kırıcı değişiklik önerilmiyor. Yine de `extra="forbid"` olduğu için her yeni alan
> tüketicileri (harness mock araçları, sayı doğrulayıcı, eğitim verisi üreteci) etkiler ve `input_hash`'i (params genişlerse) değiştirir.
> Kaynak: Bilgisayar 1, `rank_sector_relative_strength` oturumu (2026-11-20/21); sayısal gerekçeler gerçek v2 snapshot üzerindendir.

## 1. `rank_sector_relative_strength`

### 1.1 Hisse bazlı kırılım ve ham olay sayıları
**Sorun.** `historical_catch_up` grubun tüm üyelerinin olaylarını havuzlar; hangi hissenin sonucu belirlediği görünmez. Retail örneği
(`as_of = 2026-09-10`): ham laggard hisse-günü BIMAS 43, MAVI 227, MGROS 128 (toplam 398); MAVI ham gözlemlerin %57'sini verir. Ham ve bağımsızlaştırılmış
olay sayıları bugün yalnızca `HISTORICAL_ONLY` uyarı **metninde** yazıyor; sayı doğrulayıcı bunları metinden ayrıştırmak zorunda, makine okunur alan yok.

**Öneri (sonuç alanları):**
- `n_raw_laggard_observations: int` (toplam) ve `cooldown_days: int` (= `max(forward_horizons)`, bugün türetiliyor).
- `per_ticker: list[TickerCatchUp]`, üye başına:
  `ticker`, `n_raw_laggard_observations`, `n_independent_events`, `n_excluded_incomplete_horizon` (en uzun ufuk),
  `per_horizon: list[HorizonBlock]` (yalnızca `full`; IS/OOS ve baz havuzdakiyle aynı kalır).
- Havuzlu `historical_catch_up` aynen kalır (geriye dönük uyumlu).

**Gerekçe.** "MAVI geride kalınca yakalar mı?" sorusu (Soru 1) hisse bazlı yanıt ister; havuzlu isabet oranı MAVI'nin davranışıyla örtüşür. Hisse başına
olay sayısı küçüktür (retail'de 9–21), bu yüzden `FEW_EVENTS` hisse bazında da değerlendirilmelidir.

### 1.2 Sonuç ölçütünün tanımı
**Sorun.** `benchmark_definition` yalnızca TESPİT medyanını anlatır (`includes_subject_stock = true`). Tarihsel SONUÇ ölçütü kendisi hariç peer medyanı;
bu yalnızca `HISTORICAL_ONLY` metninde ve `docs/data_dictionary.md` §14.2'de yazıyor.

**Öneri:** `outcome_benchmark_definition: BenchmarkDefinition` (`type = "peer_median"`, `includes_subject_stock = false`, aynı `price_field/return_type/members`).

### 1.3 (isteğe bağlı) Parametre
`cooldown_days: int | None = None` (None → `max(forward_horizons)`). Bugün sabit türetilir; duyarlılık analizi için ayarlanabilir olması yararlı olabilir.
Eklenirse `input_hash` değişir; varsayılan davranış aynı kalır.

## 2. `calculate_indicators`: daha hafif varsayılanlar, `columns` isteğe bağlı
**Sorun.** Zarf, küçük yerel model için gereğinden ağır. Tüm göstergeler, THYAO, `as_of = 2026-09-10` ölçümü (JSON karakter sayısı):

| `last_n_rows` | zarf | bunun `columns` kısmı |
|---|---|---|
| 0 | 4 941 | 2 945 (23 kolon, %60) |
| 5 (varsayılan) | 8 898 | 2 945 |
| 30 | 28 624 | 2 945 |

`columns[]` (her kolon için `warmup_bars`, `first_valid_date`, `valid_at_as_of`) çoğu çağrıda gereksiz tekrar bilgisidir; asıl gereken `latest.values/states`.
Bağlam penceresi dar olduğundan ve modelin gereksiz sayıya maruz kalması sayısal halüsinasyon riskini artırdığından zarfın küçültülmesi istenir.

**Öneri (hepsi varsayılanlı, geriye uyumlu davranış korunabilir):**
- `include_columns_meta: bool = True` (eski davranış). `False` → `columns` yalnızca ısınmadaki (geçersiz) kolonları listeler veya boş döner.
- `value_columns: list[ColumnName] | None = None` (None = tüm kolonlar). Verilirse `values` yalnızca bu anahtarları taşır.
- (tartışmalı) `last_n_rows` varsayılanı 5 → 0 (yalnızca `latest`). Varsayılanı değiştirmek `input_hash`'i değiştirir; yalnızca yeni çağrıları etkiler.
- `IndicatorConfig` varsayılanlarının tek yerden belgelenmesi (`docs/data_dictionary.md` §13.2 zaten var); modelin parametre uydurmaması için şema örneklerine
  (`schemas/examples.py`) "yalnızca RSI" ve "yalnızca Bollinger + hacim" örnekleri eklenebilir.

**Not.** Yalnızca `RSI` istenince zarf 2 374 karakter; maliyetin büyük kısmı seçilen gösterge sayısıyla ölçeklenir, yani doğru araç çağrısı (yalnız gereken göstergeler) zaten
en büyük kazançtır; şema değişikliği bunu destekler ama yerine geçmez.

> **Durum (2026-11-21):** §3 (makro) 1.2.0 kapsamından ÇIKARILDI; ayrıntılı notlar §6'da. Kapsama alınanlar: §1, §2, §4, §5 (bkz. `docs/schema_1_2_0_plan.md`).

## 3. `get_macro_context`: ilişki alanı (1.2.0 DIŞI, bkz. §6)
**Sorun.** Soru 5 ("Kur artışı ile EREGL getirisi arasındaki tarihsel ilişkiyi araç çıktısıyla göstermeli") için makro araç yalnızca seri noktalarını döndürür
(`MacroSeriesData.points`). İlişki hesabı için model, iki serinin hizalanmasını ve istatistiği kendi yapmak zorunda kalır; bu, "sayılar yalnızca araç çıktısından gelir" (kural 6)
ilkesini ihlal eder.

**Öneri (params):** `relate_to: list[RelationSpec] = []`, `RelationSpec`: `ticker`, `macro_series`, `horizon` (işlem günü, varsayılan 5), `lag_days` (varsayılan 0, ≥ 0),
`transform` (`PCT_CHANGE` | `LEVEL_DIFF`), `split_date | None`.

**Öneri (result):** `relations: list[MacroRelation]`, her biri:
- `ticker`, `macro_series`, `horizon`, `lag_days`, `transform`, `n_obs`, `n_excluded_incomplete_horizon`.
- `correlation` (−1…1, **birimsiz**; `_pct` kuralının bilinçli istisnası; açıkça belgelenmeli), `beta` (hisse getirisi / makro değişim, pp başına pp).
- Koşullu getiri: makro serinin yükseldiği dönemlerde ve düştüğü dönemlerde hissenin ortalama/medyan getirisi (`up`, `down`, her biri `n`, `mean_return_pct`,
  `median_return_pct`) ve koşulsuz baz (`HorizonStats`/`BaselineStats` benzeri).
- `in_sample` / `out_of_sample` (`split_date` varsa) ve `oos_degradation_flag` (data_dictionary §9 kuralı).
- Hizalama: makro gözlem `publication_date`'e göre (revizyon sonradan eklenmez); `as_of` sonrası yayınlananlar girmez. Uyarılar: `ASSOCIATION_NOT_CAUSATION`,
  `MULTIPLE_TESTING_RISK`, `FEW_EVENTS`, `MACRO_DATA_MISSING`, `HISTORICAL_ONLY` (mevcut `WarningCode` değerleri yeterli).

**Gerekçe.** "Kesin yükselir" gibi nedensellik iddiasının doğrulanmadığını araç çıktısıyla göstermek için ilişki, `n_obs`, örneklem dışı kararlılık ve çoklu test uyarısı birlikte
gelmelidir. Seri hizalama tarafı (yayın tarihi, gecikme) araçta deterministik yapılmalı; model hizalamayı yeniden yapmamalıdır.

## 4. `BundleItem`: kalite kapısı için iki alan (check_data_quality)
**Sorun.** `check_data_quality` HARD kuralları (proje dokümanı §26) `analysis_bundle` künyesinden değerlendirilir, fakat `BundleItem`
yalnızca `tool, as_of, data_version, input_hash, n_events, n_excluded_incomplete_horizon` taşır. Bu yüzden iki kural şema üzerinden **kurulamıyor**:
- `LOOKAHEAD_SIGNAL`: `signal_lag_days < 1` (şema `StrategySpec` içinde 0'ı reddeder, ama künyede lag yok; kapı bağımsız doğrulayamaz).
- `BACKTEST_FUTURE_INFO` / "`as_of` sonrası tarihli sonuç": künyede aracın ürettiği en geç tarih yok.
`extra="forbid"` olduğu için bu alanlar şemaya eklenmeden bundle'a konamaz.

**Öneri (ikisi de varsayılanı `None`, geriye uyumlu):**
- `signal_lag_days_applied: int | None = None` — yalnızca `run_backtest` künyesinde dolu (`RunBacktestResult.signal_lag_days_applied`'ten).
- `max_result_date: date | None = None` — aracın sonuçlarındaki en geç tarih (backtest: son `exit_date`; olay araçları: son olay/ufuk tarihi). Kapı `max_result_date > as_of` ise HARD verir.

**Geçici durum.** Kapı mantığı (`tools/check_data_quality.py`) bu iki kuralı **saf fonksiyon** olarak içerir ve sentetik girdiyle test edilir;
`params` üzerinden çalışmadığı için `checks_run`'a girmez ve `gate_reason` bunu yazar. Şema onaylanınca yalnızca bağlama eklenir.
`harness/gate_params.py::bundle_items` (Bilgisayar 2) yeni alanları zarftan/`results`'tan kopyalayacak şekilde güncellenmelidir.
`input_hash`'i etkilemez (`analysis_bundle` params içinde olduğundan çağrıların hash'i değişir; yalnızca yeni çağrılar etkilenir).

## 5. `TickerQuality`: alan açıklamaları araçla uyumsuz (yalnızca açıklama düzeltmesi; alan/tip değişmez)
`tools/check_data_quality.py` iki alanı şema açıklamasından **farklı** doldurur. Davranış `docs/data_dictionary.md` §15.6'da belgelidir ve testlidir; şema metni güncellenmelidir
(ya da araç şemaya uyarlanmalı; **önerimiz açıklamayı düzeltmek**, çünkü araç kuralı fiyat sıçraması sınıflandırmasıyla tutarlıdır).

| Alan | Şema açıklaması (bugün) | Araçta gerçek davranış | Öneri (açıklama) |
|---|---|---|---|
| `n_price_jumps_over_limit` | "`\|günlük getiri\| > price_jump_limit_pct` olan gün sayısı" | `\|adj_close getirisi\| > price_jump_limit_pct + PRICE_JUMP_TOLERANCE_PP` (varsayılan 10 + 0,5), pencere `[start, min(end, as_of)]`; `classify_price_jumps` ve manifest `price_jump_report` ile **aynı** kural | "`\|günlük adj_close getirisi\| > price_jump_limit_pct + tolerans` olan gün sayısı (sıçrama sınıflandırmasıyla aynı kural)". Aksi halde BIST ±%10 limit hareketleri (ör. +%10,4) bayraklanırdı |
| `last_data_age_days` | "`as_of - last_date` (takvim günü)" | `as_of − (as_of'a kadarki SON satır)`; `last_date` ise **pencerenin** son satırı. `end < as_of` iken ikisi farklıdır (ör. `end` 2026-06-30, `as_of` 2026-09-10: `last_date` 06-30, yaş 0) | "`as_of` − (`as_of`'a kadarki son satır tarihi), takvim günü; `last_date` pencere sonudur, bu yüzden `end < as_of` iken `as_of - last_date`'e eşit olmayabilir" |

Gerekçe (ikinci satır): bayatlık "snapshot `as_of`'u kapsıyor mu" sorusudur ve pencereye bağlı olmamalıdır; pencere `end` erken seçildi diye bayat veri "taze" görünmemeli.

**İsteğe bağlı (5.3): kodlu sayaçlar.** `hard_blocks`/`soft_warnings` "kodlu ve sayılı" isteniyor ama `CheckDataQualityResult`'ta sayaç alanı yok; sayılar yalnızca `gate_reason` metninde
("hard 1 (WRONG_TICKER_OR_BROKEN_HISTORY×1), soft 2 (…)"). Sayı doğrulayıcı bunları metinden ayrıştırmak zorunda. Öneri: `issue_counts: dict[str, int] = {}` (kod → adet, hard ve soft birlikte;
`DQCode` anahtarlı). Varsayılanlı ve geriye uyumlu; yalnızca harness/doğrulayıcı kolaylığıdır.

## 6. `get_macro_context` ilişki sözleşmesi: AYRI KÜÇÜK SÜRÜM (1.2.0'dan çıkarıldı, karar: 2026-11-21)
`get_macro_context` aracı gerçek veriyle yazılırken, **Optional/varsayılanlı alanlarla** ayrı küçük sürümde eklenecek. §3'ün önerisine ek notlar (planlama sırasında çıkanlar):
- **Params:** `relate_to: list[RelationSpec] = []` (en çok 5; sıralı-tekil, determinizm), her `macro_series` `series` içinde olmalı. `RelationSpec`: `ticker`, `macro_series`, `horizon` (=5),
  `lag_days` (>=0, =0), `transform: MacroTransform`, `split_date | None`. `n_tests_declared: int = 1` (çoklu test).
- **`MacroTransform` enum'u (yeni, enums.py):** `PCT_CHANGE`, `LEVEL_DIFF`.
- **Result:** `relations: list[MacroRelation] = []`. `MacroRelation` §3'teki alanlara ek: `multiple_testing: MultipleTesting` (CLAUDE.md kural 11: çoklu test), `cost_model: CostModel` (kural 11: maliyet),
  `sample_last_date: date | None` (`_PAST_ONLY_KEYS`'e eklenir; look-ahead taraması). `correlation`/`beta` birimsiz (`_pct` kuralının bilinçli istisnası, açıklamada yazılır).
- **Zarf `n_events`:** `relations` varsa en küçük `n_obs`, yoksa `None`; `schemas/envelope.py` docstring'ine satır eklenir ve gerekirse `EVENT_COUNT_RULES`'a girer.
- **Pencere politikası** (örtüşmeyen bloklar önerisi: örtüşme `n_obs`'u şişirir, rank'taki cooldown gibi) araç yazılırken `docs/data_dictionary.md` §16'da kesinleşir; `oos_degradation_flag` için §9 kuralının ilişki istatistiğine uyarlanması gerekir.
- Etki (Bilgisayar 2): `harness/evidence.py::_macro` + `evidence_headlines.json` `relations` bölümü, `training/RULES.md` kural 2'ye `relate_to[].split_date`, makro senaryosu için etiket politikası, MCP `input_schema` büyümesi.

## 7. `run_backtest`: `last_exit_date` (araç yazılırken ZORUNLU; 1.2.0'a girmez)
`RunBacktestResult`'a `last_exit_date: date | None` eklenir; **araç bunu her zaman doldurur** (işlem varsa; işlem yoksa `None`) ve `trade_log` kısaltılsa (`trade_log_truncated`) bile TÜM işlemlerin en geç `exit_date`'ini taşır.
`_PAST_ONLY_KEYS`'e eklenir. `schemas.registry.max_result_date` run_backtest için bu alanı kullanır (yoksa `trade_log`'a düşer). Gerekçe: kapı `max_result_date > as_of` kontrolünü kısaltılmış kayıt yüzünden kaçırmasın.
Sürüm koşullu zorunluluk (§1 / `docs/schema_1_2_0_plan.md` D1) ile birlikte eklenir.

## Uygulama notu (onay sonrası)
1. `schemas/` değişikliği tek commit, `SCHEMA_VERSION` → `1.2.0`, `schema_changelog.md` girişi, `schemas/examples.py` ve `tests/contract/` güncellemesi.
2. Bilgisayar 2 (harness mock araçları, sayı doğrulayıcı, eğitim verisi) yeni alanlara uyum sağlar; `data_version` v2 kuralı (kural 12) değişmez.
3. Bilgisayar 1 araçları yeni alanları doldurur; ham/bağımsız olay sayıları `HISTORICAL_ONLY` metninde de (geçiş dönemi için) kalabilir.
