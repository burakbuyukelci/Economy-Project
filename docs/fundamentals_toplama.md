# TUPRS bilanço verisini KAP'tan elle toplama (arkadaş için kılavuz)

Amaç: `data/raw/fundamentals_kap.template.csv` dosyasını doldurmak. Yahoo'nun çeyreklik tabloları 2025Q1–Q2'yi vermiyor ve
açıklama tarihi/saati resmî değil; bu yüzden **TUPRS için** resmî KAP verisini elle giriyoruz. Dolu CSV, Yahoo'yu **satır bazında ezer**.

Çalışma kopyası: şablonu `data/raw/fundamentals_kap.csv` adıyla kopyalayıp onu doldur (şablonu bozma). Boş bıraktığın satırlar
Yahoo'yu EZMEZ (araç `disclosure_date` boş veya tüm finansal alanlar boş satırı atlar).

## Her satır = bir çeyrek (TUPRS x 2025Q1 … 2026Q3)

### 1. Açıklama tarihi ve saati (`disclosure_date`, `disclosure_time`) — EN ÖNEMLİ alan
1. kap.org.tr → **Bildirim Sorgulama** → Şirket: **TÜPRAŞ** (TUPRS) → Bildirim türü / konu: **Finansal Rapor** → tarih aralığı: ilgili çeyreğin açıklandığı dönem (ör. 2026Q2 için Temmuz–Ağustos 2026).
2. İlgili çeyreğin **ilk** "Finansal Rapor" bildirimini aç (sonradan gelen "Düzeltme/Değişiklik" bildirimlerini kullanma; ilk yayın tarihi esastır).
3. Bildirimin üstündeki **yayın/gönderim tarihi ve saatini** kopyala. `disclosure_date` = `YYYY-AA-GG`, `disclosure_time` = `SS:DD` (24 saat, İstanbul saati). Örn. `2026-08-11` ve `18:42`.
4. Saat nedir neden önemli: 18:00 ve sonrası = kapanış sonrası; fiyat tepkisi ertesi gün ölçülür. Saati bulamazsan boş bırak (araç muhafazakâr davranır) ama tarihi mutlaka yaz.
5. `source` sütununa bildirim bağlantısını veya bildirim numarasını yaz (ör. `KAP-bildirim-1234567`) — kanıt izi.

### 2. Dönem alanları
`fiscal_period` ve `period_end_date` şablonda dolu; değiştirme. `disclosure_date` dönem sonundan SONRA olmalı (araç aksi halde hata verir).

### 3. Rakamlar (milyon TL; KAP tabloları çoğu zaman "bin TL" → 1000'e böl)
Cari dönem sütununu kullan; "önceki dönem" karşılaştırma sütununu KULLANMA (TMS 29'da yeniden ifade edilmiş olabilir).

| Sütun | KAP kalemi |
|---|---|
| `revenue` | Kâr veya Zarar Tablosu → **Hasılat** |
| `ebitda` | **Esas Faaliyet Kârı (Zararı) + Amortisman ve İtfa Payları** (amortisman/itfa: Nakit Akış Tablosu'ndaki "Amortisman ve itfa gideri ile ilgili düzeltmeler" ya da ilgili dipnot; maddi + maddi olmayan duran varlık toplamı) |
| `net_profit` | **Dönem Net Kârı (Zararı) — Ana Ortaklık Payları** |
| `total_financial_debt` | Finansal Durum Tablosu → **Kısa Vadeli Borçlanmalar + Uzun Vadeli Borçlanmaların Kısa Vadeli Kısımları + Uzun Vadeli Borçlanmalar** (kiralama yükümlülükleri DAHİL; hangisini dahil ettiysen `source` sütununa not düş) |
| `cash_and_equivalents` | Finansal Durum Tablosu → **Nakit ve Nakit Benzerleri** |
| `equity` | Finansal Durum Tablosu → **Ana Ortaklığa Ait Özkaynaklar** |

### 4. `report_basis` ve çeyreklik (tek çeyrek) değer
Araç **tek çeyreklik** akış değeri bekler (`revenue`, `ebitda`, `net_profit`). Bilanço kalemleri (borç, nakit, özkaynak) dönem sonu değeridir.
- **Q1:** 3 aylık = kümülatif; `STANDALONE`.
- **Q2 / Q3:** KAP gelir tablosunda hem kümülatif (6/9 aylık) hem **3 aylık** sütun vardır; **3 aylık** sütunu gir → `STANDALONE`.
- **Q4:** yıllık raporda 3 aylık sütun yoktur. İki yol: (a) kendin hesapla, `yıllık − 9 aylık`, `STANDALONE` yaz; veya (b) Q1–Q4 dört satırın akış değerlerini **kümülatif** gir ve hepsine `YTD` yaz; araç farkı kendisi alır (sonuç `YTD_DIFFERENCED` olur).
- Karışık kullanma: bir yıl için ya hep `STANDALONE` ya hep `YTD`.

### 5. `tms29_restated`
2025 ve sonrası raporlar TMS 29 (enflasyon muhasebesi) uygulanmış rakamlardır → `true`. (Dikkat: TMS 29'da her rapor kendi dönem sonu satın alma gücündedir; farklı raporların rakamlarını toplamak/çıkarmak birim karışımı içerir. Araç bunu uyarı olarak taşır.)

## Örnek satır (UYDURMA rakamlar; yalnız biçim göstermek için)
```
TUPRS,2026Q2,2026-06-30,2026-08-11,18:42,KAP-bildirim-1234567,STANDALONE,true,386000,41000,20500,95000,60000,150000
```

## Bitirince
1. `python -m scripts.download_fundamentals --date YYYY-AA-GG` (ağ gerekir, Yahoo'yu çeker; yalnız CSV'yi denemek için `--no-yahoo`). Betik hatalı satırı satır numarasıyla bildirir.
2. Yeni bir `data/snapshots/fundamentals_<tarih>_v1/` oluşur. Aynı sürüm numarası tekrar yazılmaz (snapshot'lar değişmez); düzeltme için `--version-no 2`.
3. CSV ve yeni snapshot klasörünü commit'le.
