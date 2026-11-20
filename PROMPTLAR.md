# Claude Code başlangıç promptları

## Önce yapılacaklar (bir kez, Bilgisayar 1'de)
1. Boş bir klasör aç, `git init`, bu zip'in içeriğini oraya çıkar (`CLAUDE.md` kökte, `docs/` altında 3 dosya).
2. İsteğe bağlı: orijinal PDF'i de `docs/` içine koy (metin hâli zaten `docs/proje_dokumani.txt`).
3. VS Code'da klasörü aç, Claude Code'u başlat. `CLAUDE.md` otomatik okunur. PDF'i veya hocanın yazdıklarını ayrıca yapıştırmana gerek yok, `docs/` içinde.
4. GitHub/GitLab'da özel bir repo oluştur, ilk commit'i push et, arkadaşın klone etsin.

---

## PROMPT 1 — Bilgisayar 1 (iskelet + sözleşme + ilk veri araçları)
Claude Code'a plan modunda (önce plan, sonra onay) yapıştır:

```
Bu repo CSE-481 dersi için iki kişilik bir ödev. Başlamadan önce şunları oku: CLAUDE.md, docs/hoca_qa.md, docs/proje_dokumani.txt, docs/ornek_test_sorulari.txt. CLAUDE.md'deki değişmez kurallara uy.

Bugün sadece "Adım 0" ve ilk veri araçlarını yapacağız. Önce kısa bir plan çıkar, onayımı bekle, sonra uygula.

1) İskelet: CLAUDE.md'deki repo yapısını kur (boş klasörler için .gitkeep), Python 3.11 + requirements.txt (pandas, numpy, pyarrow, yfinance, pydantic, pytest, python-dotenv), .gitignore (.env, data/raw, __pycache__, model dosyaları).

2) config/universe.csv: docs/proje_dokumani.txt Bölüm 5'teki 30 hisseyi (ticker, yahoo_symbol, sector) yaz. Ek bir peer_group sütunu öner: aynı grupta en az 2 hisse olacak şekilde benzer sektörleri birleştir (ör. perakende, havayolu, telekom, elektrik, çelik, otomotiv, kimya). Hangi hisselerin tek başına kaldığını (peer_group_size = 1) listele. Peer grup önerini bana onaylat; ben onaylamadan kesinleştirme.

3) schemas/: pydantic modelleri ve enum'lar: araç zarfı (CLAUDE.md'deki JSON), AllowedAction, GateStatus, ve 15 aracın parametre/sonuç şemaları (şimdilik results alanı gevşek olabilir, parametreler kesin olsun). Her aracın as_of parametresi zorunlu olsun. Şema dosyalarını bitirince DUR ve bana göster, çünkü diğer bilgisayardaki arkadaşım bu sözleşmeye göre çalışacak.

4) Veri katmanı:
   - scripts/download_prices.py: yfinance ile 30 hisse + XU100 için 2024-01-01'den bugüne günlük OHLCV indir, data/snapshots/ altına parquet olarak, data_version ile kaydet. Hangi fiyatın (adjusted/unadjusted) kullanıldığını, eksik günlerin nasıl ele alındığını docs/data_dictionary.md'ye yaz. XU100 için doğru Yahoo sembolünü doğrula; bulamazsan bana söyle.
   - tools/common.py: enforce_as_of(df, as_of), input_hash(params), zarf oluşturucu.
   - tools/get_stock_history.py ve tools/get_index_history.py: snapshot'tan oku, as_of'tan sonrasını kesin, şemaya uygun zarf döndür.
   - tests/: as_of sonrası hiçbir satırın dönmediğini, aynı çağrının aynı input_hash/çıktıyı verdiğini, bilinmeyen ticker'da status ERROR döndüğünü test et.

5) Bitirince: ne yaptığını gerçek değerlerle adım adım açıkla (örnek: as_of=2026-09-10 ile THYAO çağrısında son satırın tarihi ne, kaç satır döndü, 11 Eylül neden yok).

Ağ erişimi yalnızca scripts/ içinde olsun, tools/ içinde olmasın. Küçük commit'ler at.
```

**Plan geldiğinde:** onaylamadan önce peer grubu ve şema kısmını arkadaşınla birlikte oku. Sözleşme burada belirlenir.

---

## PROMPT 2 — Bilgisayar 2 (harness tarafı). Şemalar push'landıktan SONRA başlat
Arkadaşın `git pull` yapsın, kendi bilgisayarında Claude Code'u açıp (plan modunda) şunu yapıştırsın:

```
Bu repo CSE-481 dersi için iki kişilik bir ödev. Başlamadan önce şunları oku: CLAUDE.md, docs/hoca_qa.md, docs/proje_dokumani.txt, docs/ornek_test_sorulari.txt. CLAUDE.md'deki değişmez kurallara uy. Sen BİLGİSAYAR 2 bölgesindesin: harness/, training/, experiments/. tools/ ve schemas/ klasörlerini değiştirme; arkadaşım orada çalışıyor.

Önce kısa bir plan çıkar, onayımı bekle. Sonra:

1) harness/mock_tools.py: schemas/ içindeki sözleşmeye uyan, gerçek araçlar bitene kadar kullanılacak sahte araçlar (sabit, uydurma ama şemaya uygun JSON döndüren). Gerçek araçlar gelince tek bir ayarla (config) değiştirilebilsin.

2) harness/mcp_server.py: araçları MCP sunucusu olarak sunan iskelet (Python MCP SDK; sürümü ve kullanımı bana doğrula, tahmin etme).

3) harness/state_machine.py: proje dokümanı §23'teki durumlar (START → … → LOG_AND_CLOSE). Her durum yalnızca tanımlı araç alt kümesini açsın; mandatory CHECK_DATA_QUALITY ve RUN_BACKTEST adımları atlanamasın; izinli olmayan araç çağrısı "invalid tool call" olarak sayılsın ve loglansın.

4) harness/number_verifier.py: bir metindeki tüm sayıları çıkarıp, o analizdeki araç çıktılarında geçip geçmediğini kontrol eden modül (tarih, yüzde, ondalık biçimlerini ve yuvarlamayı nasıl ele aldığını açıkla). Testlerini yaz.

5) harness/action_guard.py: nihai çıktının eylem etiketi AllowedAction enum'u içinde mi, metinde al/sat/hedef fiyat dili var mı kontrol et.

6) experiments/eval_set.py: docs/ornek_test_sorulari.txt'deki 5 soruyu yapılandırılmış değerlendirme kayıtlarına çevir (soru, beklenen araçlar, beklenen eylem/davranış, tuzak notu: ufku dolmamış olay, 10.09.2026 sonrası veri, tavsiye reddi). Ek olarak benzer yapıda 15 soru taslağı üret; farklı hisse/sektör/tarihlerle (hisseler config/universe.csv'den).

7) Yerel modeli Ollama ile çağıran ince bir istemci (harness/llm_client.py): sıcaklık 0, sabit seed, model adı config'ten. Henüz fine-tune yok; baz model ile "A — Raw LLM" ve "B — LLM + Tools" deney iskeletini kur.

Bitirince her modülü gerçek örnek değerlerle adım adım açıkla; sunumda savunacağız. Küçük commit'ler at.
```

---

## Sonraki promptlar (şimdilik yazma, sırası gelince)
- **PROMPT 3 (Bilgisayar 1):** senaryo 1–3 araçları: calculate_indicators, detect_reversal_events, rank_sector_relative_strength, test_weekday_pattern. Her biri ayrı oturum/ayrı prompt.
- **PROMPT 4 (Bilgisayar 2):** gerçek araçlar merge olunca `training/`: eğitim verisi üreteci (araç çıktılarından şablonla), olumsuz örnekler, QLoRA, değerlendirme.
- **PROMPT 5 (Bilgisayar 1):** run_backtest, bilanço (KAP tarihleri), makro, check_data_quality.
