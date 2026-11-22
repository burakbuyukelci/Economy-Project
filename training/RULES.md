# Eğitim verisi kuralları (BİLGİSAYAR 2)

CLAUDE.md kural 12 ve 6 ile birlikte okunur. Bu dosya eğitim kaydı üretiminin harness'e özgü kurallarını toplar.

1. **Yalnızca v2 snapshot.** Kayıttaki her araç zarfı `harness.mock_tools.assert_training_eligible` ile denetlenir (mock ve v1 reddedilir).
2. **`split_date` kuralı (OOS):** eğitim kaydındaki her `rank_sector_relative_strength` / `detect_reversal_events` çağrısı `split_date` taşır, her `test_weekday_pattern` çağrısı
   `out_of_sample_start`, her `run_backtest` çağrısı `strategy.train_end` taşır. Değer **her zaman as_of yılının 1 Ocak'ı** (ya da `train_end` için bir gün öncesi) veya **sorudaki OOS başlangıcıdır**.
   Eksik OOS ile üretilmiş kayıt yalnızca "OOS doğrulaması yapılmadı" gerekçeli `INVESTIGATE` etiketi içerebilir (bilinçli negatif örnek); aday etiketli kayıtta OOS ZORUNLUDUR.
3. **Etiket politikadan gelir.** Kaydın `EYLEM:` etiketi `harness.label_policy.decide_label` / `decide_session` çıktısıdır; elle etiket yazılmaz. Eğitim ve değerlendirme aynı politikayı kullanır
   (`docs/harness_design.md` bölüm 11). Kayıtta politikanın `rule_id` ve `reasons` alanları saklanır (izlenebilirlik).
4. **Açıklama doğrulamadan geçer.** Her kaydın açıklaması `harness.number_verifier.verify_numbers` (halüsinasyon oranı 0) ve `harness.action_guard.check_final_output(..., required_action=decision.label)` (ihlal 0)
   ile denetlenir; geçmeyen kayıt eğitim setine alınmaz.
5. **Kanıta dayalı gerekçe.** Açıklama yalnızca committed kanıtta bulunan sayıları kullanır (`UNEVIDENCED` sayı yok); türetilmiş sayı (örn. 14/22 -> %64) yazılmaz, araç değeri aynen alınır.
6. **Çürütme biçimi:** kullanıcı kesinlik iddiası taşıyorsa açıklama `“kesin yükselir” iddiası … doğrulanmamıştır` biçimini kullanır (tırnak içinde + iddia/ifade/söylem + çürütme sözcüğü); yalnızca
   "doğrulanmamış" demek eylem korumasında muafiyet vermez.
7. **Aday etiketli kayıtlarda** açıklama "tarihsel gözlem, örnek küçük, belirsizlik var" notunu içerir; negatif örnekler (REJECT_SIGNAL, WATCH, INVESTIGATE, HOLD, ANALYSIS_UNSAFE) dengeli üretilir
   (modelin hep aday etiket vermeye alışmaması için).
8. **Bilanço/makro veri seti sürümü (kural 12'nin karşılığı).** Bilanço/makro araçlarının zarfındaki `data_version` fiyat sürümüdür (`snap_*_v2`); veri seti sürümü (`fundamentals_YYYY-MM-DD_vN`, `macro_YYYY-MM-DD_vN`) zarfta ayrı alan olmadığından `HISTORICAL_ONLY` uyarı metninde taşınır.
   `harness.mock_tools.assert_training_eligible` bu sürümü regex ile çeker ve `harness.settings.ACCEPTED_FUNDAMENTALS_VERSIONS` / `ACCEPTED_MACRO_VERSIONS` kabul listesine karşı denetler (tam BİR sürüm olmalı; yoksa/liste dışıysa kayıt reddedilir).
   Kayıtta `versions.fundamentals` bulunur; bilanço oturumunda boş olamaz. Makro snapshot'ı main'e girip kabul listesine eklenmeden makro oturumu üretilmez (`spec.REAL_TOOLS` makroyu içermez).
9. **Açıklama tarihi belirsizliği açıkça yazılır.** `YAHOO_APPROX` (yaklaşık) ve `STATUTORY_DEADLINE` (açıklama tarihi bilinmiyor, yasal süre sonu varsayıldı) uyarıları modele gider (model görünümü atmaz); açıklama bunu sayısız bir notla belirtir (`composer.FUNDAMENTAL_WARNING_NOTES`).
   Yasal süre satırları fiyat tepkisi istatistiğine girmez; açıklamada "nedensellik iddia edilmez" notu her bilanço oturumunda bulunur.
