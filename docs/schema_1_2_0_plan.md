# Şema 1.2.0 planı (ONAYLANDI; `schema-1.2.0` dalında UYGULANDI, main'e birleştirme bekliyor)

> Kaynak: `docs/schema_wishlist.md` §1–5. Onay: ekip, 2026-11-21. Bu dosya karar kaydıdır; ayrıntılı alan sözleşmesi uygulanınca
> `schemas/schema_changelog.md` içindeki 1.2.0 girişi bağlayıcı olur.
> **Kapsam dışı (ayrı küçük sürüm):** `get_macro_context` ilişki sözleşmesi (wishlist §6).

## Onaylı kararlar
| | Karar |
|---|---|
| D1 | Yeni sonuç alanları Optional/varsayılanlı; `schema_version >= 1.2.0` ve `status=OK` ise `registry.validate_envelope` bunların `None` olmamasını şart koşar (sürüm koşullu zorunluluk). `issue_counts` için `{}` değil `None` (= raporlanmadı). |
| D2 | `input_hash` değişimi kabul (§Hash etkisi). Hash tanımı değişmez. |
| D3 | `calculate_indicators`: `include_columns_meta=False`, `last_n_rows=0` varsayılan. |
| D4 | `cooldown_days` yalnızca SONUÇ alanı; param eklenmez (duyarlılık analizi gerekince, hash değişir). |
| D5 | `max_result_date` için `schemas/registry.py` yardımcı fonksiyonu (zarf şeması değişmez). **Ek:** `run_backtest` yazılırken sonuçta `last_exit_date` (en geç çıkış tarihi) **zorunlu** olur ve `trade_log` kısaltılsa bile korunur (wishlist §7). 1.2.0'a girmez. |
| D6 | `run_backtest` öğesinde `max_result_date > as_of` → `BACKTEST_FUTURE_INFO`; `signal_lag_days_applied < 1` ve diğer araçlarda `max_result_date > as_of` → `LOOKAHEAD_SIGNAL`. |
| D7 | **HAYIR.** (e) makro sözleşmesi 1.2.0'dan ÇIKTI; Optional alanlarla, `get_macro_context` gerçek veriyle yazılırken ayrı küçük sürümde eklenecek. Notlar wishlist §6'da. |
| D8 | `per_ticker` için `CatchUpHorizon` yeniden kullanılır (IS/OOS yok), `ranking` ile ayna alanlar. |
| D9 | Dal `schema-1.2.0`; Bilgisayar 2 aynı dalı çekip harness'i uyarlar, tüm testler yeşil olunca main'e birleştirilir. Dalı push etmeden önce insana sorulur. |

## 1. Sürüm ve geriye uyumluluk
- `SCHEMA_VERSION` 1.1.0 → 1.2.0 (tüm araçlar damgalar; şekli değişmeyen araçlar da 1.2.0 yazar).
- 1.1.0 zarfları geçerli kalır: değişiklikten ÖNCE örnek zarflar `tests/contract/fixtures/envelopes_1_1_0/` altına dondurulur ve `validate_envelope`'tan geçirilir.
- `validate_envelope` davranış değişikliği (changelog'da ayrıca onaylı): 1.2.0+ zarflarında yeni alanlar `None` olamaz.
- Kırıcı olan tek şey `calculate_indicators` varsayılanlarıdır; eski açık params geçerli kalır.

## 2. Alan tabloları (eski → yeni)
### (a) `BundleItem` (params.py)
| Alan | Eski | Yeni |
|---|---|---|
| `signal_lag_days_applied` | yok | `int \| None = None`. `ge=1` YOK: kapı 0'ı görüp HARD verebilsin. `StrategySpec`/`RunBacktestResult`'taki `ge=1` kalır. |
| `max_result_date` | yok | `date \| None = None`. `as_of`'u aşabilir (ihlali kapı yakalar); `_PAST_ONLY_KEYS`'e eklenmez. |

### (b) `rank_sector_relative_strength` (results.py)
| Alan | Eski | Yeni |
|---|---|---|
| `n_raw_laggard_observations` | yalnızca `HISTORICAL_ONLY` metninde | `int \| None = None` (ge=0), üyelerin toplamı; tek hisseli grupta `None` |
| `cooldown_days` | `max(forward_horizons)` türetiliyordu | `int \| None = None`; tek hisseli grupta `None` |
| `outcome_benchmark_definition` | yok | `BenchmarkDefinition \| None = None`: `peer_median`, `includes_subject_stock=False`, `members` = grup üyeleri (her hisse için kendisi çıkarılır) |
| `per_ticker` | yok | `list[TickerCatchUp] = []`; tek hisseli grupta `[]` |

`TickerCatchUp`: `ticker`; `is_laggard`, `lag_score_pp` (ranking aynası); `n_raw_laggard_observations`; `n_independent_events`;
`n_excluded_incomplete_horizon` (en uzun ufuk); `per_horizon: list[CatchUpHorizon]` (IS/OOS `None`).
Doğrulayıcılar: her ufukta Σ(`n_events_complete`, `n_excluded_incomplete_horizon`, `n_success`, `n_false_positive`) havuzlu blokla eşit;
Σ`n_raw_laggard_observations` üst alana eşit; ayna alanlar `ranking` ile aynı.
Retail örneği: ham 43 + 227 + 128 = 398, bağımsız 9 + 21 + 14 = 44.

### (c) `calculate_indicators`
| Alan | Eski | Yeni |
|---|---|---|
| `include_columns_meta` (params) | yok | `bool = False` |
| `value_columns` (params) | yok | `list[ColumnName] \| None = None` sıralı-tekil; bilinmeyen ad → `INVALID_PARAMS` (geçerli adlar mesajda) |
| `last_n_rows` (params) | varsayılan 5 | varsayılan **0** (aralık aynı) |
| `columns_meta_included` (result) | yok | `bool = True` (1.1.0 zarfları True) |
| `columns` (result) | her zaman dolu | `include_columns_meta=False` iken `[]` |
| `invalid_columns_at_as_of` (result) | yok | `list[ColumnName] \| None = None`: `latest.values`'ı `None` olan kolonlar |

`columns_meta_included=True` iken 1.1.0 kuralı aynen (values anahtarları = columns adları); `False` iken `columns == []`;
`first_valid_date` döndürülen (seçilen) kolonlar üzerinden.

### (d) `TickerQuality` yalnızca açıklama
`n_price_jumps_over_limit`: "|günlük adj_close getirisi| > price_jump_limit_pct + PRICE_JUMP_TOLERANCE_PP olan gün sayısı; pencere [start, min(end, as_of)]; classify_price_jumps ile aynı kural".
`last_data_age_days`: "as_of − (as_of'a kadarki son satır), takvim günü; last_date pencere sonudur, end < as_of iken as_of − last_date'e eşit olmayabilir".

### (f) `check_data_quality.issue_counts`
`dict[DQCode, int] | None = None`. Doğrulayıcı: sıfır girdi yok; Σ = `len(hard_blocks) + len(soft_warnings)`; her kodun sayısı listelerle birebir. `gate_reason` metni değişmez (geçiş dönemi).
Gerekçe: sayılar bugün `gate_reason` metninde ve sayı doğrulayıcı bunları serbest metinden ayrıştırarak havuza alıyor (`add_tree` → `extract_claims`); bu örtük bir biçim
sözleşmesidir. Sayılar makine okunur değil, kapı kanıt çıkarıcısında yok (committed kanıta giremez). Tipli alanda her sayının yolu belli olur (`issue_counts.FEW_EVENTS`).

## 3. Hash etkisi
| Araç | Etki |
|---|---|
| `calculate_indicators` | tüm hash'ler değişir (iki yeni param + `last_n_rows` varsayılanı) |
| `check_data_quality` | yalnızca boş olmayan `analysis_bundle` (öğeler iki `null` alan kazanır) |
| diğerleri | değişmez |

`schema_version` hash'e girmez. `training/` altında henüz kayıt yok; hash'e bağlı log/replay/fixture 1.2.0'dan önce dondurulmamalı.

## 4. Etkilenen dosyalar
**Bilgisayar 1:** `schemas/` (common, params, results, registry, examples, schema_changelog), `tools/rank_sector_relative_strength.py`, `tools/calculate_indicators.py`,
`tools/check_data_quality.py`, `docs/data_dictionary.md` (13.1/13.5, 14.3, 14.4, 15.1–15.3, 15.5, 15.6), wishlist, `tests/contract/` (+fixtures), `tests/tools/`.

**Bilgisayar 2 etki listesi (Bilgisayar 1 değiştirmez):**
| Dosya | Etki |
|---|---|
| `harness/gate_params.py` `bundle_items` | `signal_lag_days_applied` (run_backtest `results`'ından) ve `max_result_date` (`schemas.registry` yardımcısı) kopyalanmalı; kopyalanmazsa yeni kapı kontrolleri çalışmaz ("çalışmadı") |
| `harness/evidence.py` | `_rank_sector`: `per_ticker`, `n_raw…`, `cooldown_days`, `outcome_benchmark_definition`; opsiyonel `check_data_quality` çıkarıcısı (`issue_counts`) |
| `harness/evidence_headlines.json` | rank için `per_ticker` bölümü ve `policy_values`; `version` 3; test_evidence_headlines / test_policy_evidence |
| `harness/label_policy.py` `_catch_up` | özne bazlı olay sayısı (`per_ticker`) `C3_FEW_EVENTS`'i etkiler (retail: havuz 44 geçer, BIMAS 9 / MGROS 14 düşer); etiket dağılımı değişir; eşik/politika Bilgisayar 2'nin |
| `harness/number_verifier.py` | kod değişikliği gerekmez (`add_tree`); havuz büyür; `issue_counts` ile `gate_reason` ayrıştırma bağımlılığı bırakılabilir |
| `harness/mock_tools.py` | `example_envelope` kullanır, otomatik güncellenir |
| `harness/mcp_server.py` | `input_schema` params modellerinden: iki yeni indicators param'ı eklenir |
| `training/RULES.md`, veri üretici | kayıtlar yalnızca 1.2.0 şemasıyla üretilmeli |
| `docs/tool_usage_guide.md` | indicators hafif varsayılanları, `per_ticker` |

## 5. Test planı (önce test)
1. 1.1.0 dondurulmuş zarflar geçerli. 2. Sürüm koşullu zorunluluk (1.2.0 + `None` red; 1.1.0 + `None` kabul).
3. rank: per_ticker toplamları, aynalar, `cooldown_days == max(forward_horizons)`, tek hisseli grup. 4. indicators: meta açık/kapalı, `value_columns`, `invalid_columns_at_as_of`, varsayılanlar.
5. BundleItem: lag 0 BundleItem'da kabul / StrategySpec'te red; hash. 6. issue_counts doğrulayıcı + uçtan uca. 7. Birim kuralı testi yeni alan adlarında. 8. Sabit hash içeren testlerin taranması.

## 6. `check_data_quality`: 1.2.0 sonrası bağlama
| Kontrol | Bağlama |
|---|---|
| `LOOKAHEAD_SIGNAL` | her bundle öğesinde `signal_lag_days_applied < 1` → HARD; `run_backtest` dışı araçta `max_result_date > as_of` → HARD |
| `BACKTEST_FUTURE_INFO` | `run_backtest` öğesinde `max_result_date > as_of` → HARD (aynı olgu iki kodla yazılmaz) |
| `checks_run` | `SIGNAL_SHIFT`: en az bir `run_backtest` öğesinde `signal_lag_days_applied` doluysa; yoksa "çalışmadı" |
| Bağlanmayacak | "giriş ≤ sinyal günü" ve işlem bazlı çıkış (`check_backtest_information`): bundle'da işlem listesi yok; saf fonksiyon olarak kalır |

## 7. Uygulama sırası
1. Dal `schema-1.2.0`; 1.1.0 fixture'ları + yeni testler (kırmızı). 2. `schemas/` tek commit. 3. Araçlar ayrı commit (rank, indicators, check_data_quality).
4. data_dictionary + wishlist. 5. Tam `pytest`; kırılan harness testleri Bilgisayar 2'ye listelenir. Dal push öncesi insana sorulur; main'e Bilgisayar 2 uyarlaması + yeşil testler sonrası.

## 8. Uygulama notları (plandan sapmalar ve ölçümler)
- `schemas.registry.max_result_date(results)` tek argümanlıdır (plandaki `(tool, results)` yerine; araç bazlı özel kural gerekmedi). `run_backtest.last_exit_date` eklenince `_PAST_ONLY_KEYS`'e girer ve otomatik kapsanır.
- **Bulgu (kapı):** `DQIssue.date` geçmiş-only anahtardır; `as_of` sonrası tarihli ihlali orada taşıyan zarf look-ahead taramasında REDDEDİLİYORDU (önceden `AS_OF_VIOLATION` için de geçerliydi,
  sentetik testler zarfı doğrulamıyordu). Kural: `DQIssue.date` `as_of`'u aşmaz; ihlalin tarihi `message`'ta, `date` `None`. Dört saf kural fonksiyonu ve testleri güncellendi.
- **Ölçüm:** `calculate_indicators` THYAO, 2026-09-10, 23 kolon: hafif varsayılan 2 226 karakter; 1.1.0 varsayılanı 9 124; yalnız RSI hafif 1 514.
- **Rank:** gerçek retail `per_ticker` ham 43/227/128 (398), bağımsız 9/21/14 (44), ufku dolmamış 1 — `data_dictionary` §14.4 ile birebir.
- Plan dışı eklenmedi: hisse bazlı `FEW_EVENTS` uyarısı (araç yalnızca havuzlu `n_events` için üretir; hisse bazlı değerlendirme harness etiket politikasında).
