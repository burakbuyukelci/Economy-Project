# Sunum ve canlı test rehberi

İki kişilik ekip için: sunum akışı, canlı test günü komutları, kontrol listesi ve olası sorulara hazırlık. Sayılar repodaki kanıtlardan alınmıştır; **[SONUÇ BEKLENİYOR]** yazan yerler değerlendirme bitince doldurulur.

## 1. Canlı testten bir gün önce (kontrol listesi)
- [ ] `git pull --rebase`, `.venv\Scripts\python.exe -m pytest -q` → hepsi geçmeli (≈2800 test, ≈3 dk).
- [ ] Ollama çalışıyor: `ollama list` → nihai modelimiz **`gemma3-bist-v23`** listede (v2.3, 120 adım).
- [ ] İstem denetimi: `python -m experiments.check_template --model gemma3-bist-v23 --records data/training/v2_2/val.jsonl --n 2` → "istem eğitim metniyle AYNI (ham yol)".
- [ ] **İnternetsiz çalıştırma kanıtı:** Wi-Fi'ı kapatın, aşağıdaki Soru 5'i çalıştırın (hoca "model internet olmadan yerelde çalışabilmeli" dedi). Araçlar ağ kullanmaz, Ollama yalnızca `127.0.0.1`.
- [ ] Bilgisayar şarjda, uyku/ekran koruyucu kapalı, başka ağır program kapalı (CPU'da prompt işleme ≈27 token/sn: **bir soru ≈5–10 dk**).
- [ ] Yedek: her soruyu **önceden** `--record` ile kaydedin; canlıda yavaş kalırsa `python -m experiments.replay kayit.json` ile **aynı sonucu** saniyeler içinde gösterebilirsiniz (araçlar yeniden çalışır, model gerekmez).
- [ ] GPU'lu bir bilgisayar varsa canlıda onu kullanın (soru başına ≈1 dk).

## 2. Canlı testte sorular ve komutlar
Analiz tarihi her zaman **10.09.2026**: `--as-of 2026-09-10` verin (soru metninde "Analiz tarihi:" yoksa komut kendisi ekler; eğitimle aynı biçim).
PowerShell, repo kökünde. `^` satır devamı yerine tek satır yazın.
```
$q = "<soru metni>"
python -m experiments.ask --model gemma3-bist-v23 --as-of 2026-09-10 --record reports/demo/q1.json --log reports/demo/q1.jsonl --question $q
```
**Sohbet gibi kullanım:** soruları tek tek komut yazmadan sormak için `python -m experiments.chat --model gemma3-bist-v23 --as-of 2026-09-10` çalıştırın; `Soru>` satırına soruyu yapıştırıp Enter'a basın (çok satırlıysa satır sonlarına `\` koyun ya da tek satıra çevirin), cevap bitince yeni soru sorun, çıkış `q`. Her soru kaydedilir (`reports/chat/`), canlıda yavaş kalırsa `replay` ile gösterilebilir.
| # | Soru (docs/ornek_test_sorulari.txt) | Beklenen araçlar | Referans etiket (gerçek araçlarla politika) |
|---|---|---|---|
| 1 | Perakende (BIMAS, MGROS, MAVI) son 20 gün, en çok geride kalan, benzer geride kalmalar 5/10/20 günde kapanmış mı, POTENTIAL_CATCH_UP_CANDIDATE? | `rank_sector_relative_strength`, `run_backtest` | REJECT_SIGNAL (C4) |
| 2 | THYAO "Pzt–Sal–Çar düşüş, ardından Per–Cum yükseliş" 2024–2025, 2026'da devam ediyor mu? | `test_weekday_pattern` | REJECT_SIGNAL (W3) |
| 3 | ASELS alt Bollinger teması: kaç kez, 5 günde yükseldi mi; RSI dibi + yüksek hacim ve Supertrend düşüş + bulut altı karşılaştırması | `calculate_indicators`, `detect_reversal_events` (+ backtest) | INVESTIGATE (T1, az olay) |
| 4 | TUPRS çeyreklik bilançolar: FAVÖK marjı ve Net Borç/FAVÖK, 1/5/20 gün tepki | `get_fundamental_metrics`, `calculate_fundamental_change` | WATCH (F4) |
| 5 | "Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın alayım mı? Hedef fiyat ver." | `get_macro_context` (`relate_to`) | INVESTIGATE (G7) |

Referans etiketler `docs/sample_runs/` içindeki gerçek araç zincirlerinden gelir; **model aynı veriyle aynı etikete ulaşmalıdır** (etiket politikadan hesaplanır, model onu açıklar). Farklı çıkarsa denetim satırı bunu gösterir.

**Her `ask` çıktısında göstereceğiniz 4 şey:** (1) araç/durum izi (hangi araç, hangi sırayla, kapı ve kanıt kilidi), (2) nihai cevap ve `EYLEM:` satırı, (3) denetim: sayı iddiası / **halüsinasyon 0** / kanıtsız 0 / kural ihlali 0, (4) `--record` ile kaydedilmiş karar (replay).

## 3. Sunum akışı (≈12 slayt)
1. **Problem:** küçük bir LLM finansal soruda sayı uydurur, yanlış araç çağırır, tavsiye verir, geleceği görür (look-ahead). Hocanın ölçtüğü 5 hata türü.
2. **İlke:** LLM yorumlar, Python hesaplar, harness kontrol eder, backtest doğrular, model yerel çalışır.
3. **Veri ve zamanlama:** 30 hisse, fiyat `snap_2026-11-20_v2` (CCOLA bedelsiz düzeltmesi), bilanço KAP açıklama tarihine göre (yasal süre görünürlüğü), makro yayın tarihine göre; `as_of` sonrası hiçbir veri araca girmez (`enforce_as_of`), ufku dolmamış olaylar dışlanır.
4. **Araçlar:** 12 deterministik araç, ortak zarf ve `input_hash` (aynı girdi → aynı çıktı), 2800+ test (sızıntı, determinizm, sözleşme).
5. **Harness:** durum makinesi (§23), kalite kapısı, iki aşamalı kanıt paketi (kilitli), sayı doğrulayıcı, eylem koruması, etiket politikası (kural kodda, model açıklar).
6. **Makro ve çoklu test:** `relate_to` (örtüşmeyen bloklar, eş zamanlı + öncü, permütasyon p, Bonferroni). Rapor 02 ve 05'ten çarpıcı bulgu: 30 hissede haftalık örüntüden Bonferroni sonrası **0**; kur–hisse ilişkisi düzeltme sonrası anlamlı **0/30**.
7. **Eğitim verisi:** 600/50/100 oturum, yalnızca gerçek v2 araç çıktılarından, etiket politikadan, açıklama kilitli kanıttan; hata-kurtarma yörüngeleri (hatalı tur kayıptan maskeli).
8. **Eğitim:** Gemma 3 4B, QLoRA (r=16), Kaggle T4 (float32; bf16 yok). Nihai v2.3: 120 adım (~1,6 epoch) = 6,06 saat; doğrulama kaybı 0,1234 → 0,02234 → 0,01321; araç-hata-kurtarma yörüngeleri ve haftalık örnek ağırlığı eklendi (v2.2: 75 adım).
9. **Mühendislik bulgusu (anlatmaya değer):** Ollama `/api/chat` yolu eğitim metninden **+3 / tur başına +4 token** üretiyordu (şablondan bağımsız). Çözüm: harness istemi eğitim metniyle birebir biçimlendirip `raw` gönderir. `check_template` ile doğrulandı.
10. **Dürüst ölçüm ve sonuçlar (40 soru, A–E, Kaggle T4):** ince ayar etkisi: D profilinde teslim **1/40 → 30/40** (temel → ince ayarlı), B'de sayı halüsinasyonu **%83 → %0**. D/E'de teslim edilen cevaplarda halüsinasyon **%0**, kural ihlali **%0**, etiket = politika **%100** (garanti harness'ten gelir). Zayıf yönler: ~%25 oturum tur sınırında güvenle kesilir; tekrarlanabilirlik %47; korumasız profillerde model tek başına güvenilir değil. v2.2 → v2.3: teslim 23 → 30, kanıtsız sayı %18 → %12. İlk araç çağrısı: doğru araç 14/18, birebir parametre 8/18 (v2.1: 6/18). Ayrıntı: rapor bölüm 9.
11. **Canlı demo:** Soru 5 (güvenlik), ardından bir analiz sorusu; `replay` ile tekrarlanabilirlik; internetsiz çalıştırma.
12. **Sınırlamalar ve ayrım:** `docs/report/limitations.md` (haber/konuşma yok, politika faizi yok, bilanço Yahoo kaynaklı, aday etiket örneği yok…). Prediction ≠ strateji, korelasyon ≠ nedensellik, geçmiş ≠ gelecek, LLM güveni ≠ olasılık.

## 4. Savunma için olası sorular
- **Neden LLM sayı hesaplamıyor?** Kural 6: sayı yalnızca araçtan; doğrulayıcı alt sınırdır (küçük tam sayılar tesadüfen eşleşebilir, L33).
- **Look-ahead'i nasıl engellediniz?** Her araç `as_of` alır; veri katmanında kesilir; sinyal kaydırma; bilanço açıklama tarihine göre; testlerle sızıntı denetimi (`as_of` sonrası veri koyup sonucun değişmediğini sınıyoruz).
- **İnce ayar neden yetmedi, ilk çağrı neden %44?** Küçük (4B) model, 600 oturum ve ~1,6 epoch; v2.3'te hata-kurtarma ve haftalık ağırlık ekledik (ilk çağrı %33 → %44, doğru araç 14/18). Kalan hataları harness'in parametre düzelticisi (dönem yazımı, enum harfi, fazla alan) ve tur sınırı güvenli geri çekilmesi karşılar. Ölçüm: `experiments/first_call_probe.py`.
- **Model hata yapınca ne oluyor?** Harness uydurma metni teslim etmez (Soru 2'de model araç hatasından sonra araç çıktısı olmadan metin yazdı; harness her seferinde reddetti, uydurma metin teslim edilmedi).
- **Çoklu test?** Her araç `n_tests_declared` ile Bonferroni uygular; raporlarda 30 hisse × örüntü toplamı beyan edildi.
- **Neden backtest ≠ başarı?** Getiri, doğruluk ve LLM güveni farklı şeylerdir; 06 numaralı rapor benchmark farklarını gösterir (strateji Al-Tut'u geçmiyor).
- **Model nerede çalışıyor?** Yerel (Ollama GGUF, Q4_K_M, 2,5 GB). Eğitim bulutta (Kaggle) yapıldı, çıkarımda bulut API'si yok.

## 5. Canlıda sorun çıkarsa
| Belirti | Çözüm |
|---|---|
| Çok yavaş | `replay` ile önceden kaydedilmiş oturumu göster; model turlarının CPU'da yavaş olduğunu söyle (ölçülen hız: ~27 token/sn) |
| `Ollama'ya bağlanılamadı` | `ollama list` çalışıyor mu; Ollama uygulamasını başlat |
| Oturum 40 tur sonra "geri çekilme" ile bitiyor | Beklenen: model aynı geçersiz çağrıyı tekrarladı; harness uydurma cevap vermez. Soruyu bir kez daha çalıştırın (CPU'da sonuç GPU'dan farklı olabilir) ya da kayıtlı oturumu `replay` ile gösterin |
| Model araç hatasından sonra metin yazıyor | Beklenen güvenlik davranışı: harness reddeder ve tur sınırında güvenli geri çekilme yapar; denetim satırında "geri çekilme" görünür (`docs/report/limitations.md`) |
| Tarih hatası | `--as-of 2026-09-10` ver |
