# Hocanın açıklamaları (Dr. Alper Özcan) — CSE-481 projesi

Bu dosya öğrencilerin hocadan aldığı açıklamaların metnidir. `proje_dokumani.txt` ile çelişirse BU DOSYA geçerlidir.

## Questions and Answers About the Project

1. Will the project be completed individually or in groups?
   You may complete the project individually or in groups of two.

2. Can I use a data source other than Yahoo Finance?
   Yes. Yahoo Finance is not mandatory. If index data or historical data are insufficient, you may use another reliable and legally accessible data source.
   The important point is to clearly document the data source, date range, any adjustments applied, and how missing data are handled.
   Yahoo Finance / yfinance is provided in the project only as an example data source.

3. Is the news and speech layer mandatory? Can I use KAP disclosures?
   The news/context layer is part of the project architecture. You may use KAP disclosures for company-specific events, and this is actually a very appropriate source because KAP provides official disclosure timestamps. It is especially useful for financial results, material company events, and disclosure dates.
   The speech-to-text component may be implemented on a smaller scale using selected and instructor-approved examples. The main objective is to use textual sources as timestamped contextual evidence, not to replace numerical financial data with text-based information.

4. Companies, except banks, report their annual financial statements under TMS 29 after 2024. Since direct comparisons with earlier periods and with banks may be misleading, should I use only post-TMS 29 periods for quarterly analysis, or should I include earlier periods after adjusting them for inflation in real terms?
   TMS stands for Turkish Accounting Standards. TMS 29 is the accounting standard that governs financial reporting in hyperinflationary economies.
   Directly mixing older nominal financial statements with post-TMS 29 inflation-adjusted statements may be misleading. Therefore, for the main analysis, I recommend using post-TMS 29 periods that are internally consistent.
   You may use data from 1 January 2025 to November 2026 for your tests.

5. Is there a specific model you recommend for the harness experiments?
   No specific LLM is mandatory. My recommendation is to keep the same model fixed across the harness experiments and focus the comparison on the system architecture.
   Compare the following stages:
   Raw LLM → LLM + Tools → Tools + Stateful Harness → + Evidence/Quality Gate → + Memory + Human Review
   The objective is not to answer the question, "Which LLM is better?" Instead, the goal is to examine how much more reliable and reproducible the system becomes as tools, state, evidence, verification, and human review are added.

## Project Announcement: Development of Group-Specific Language Models

For the course project, each group will develop its own large language model (LLM). Grading will be based on testing the LLMs you develop.
This approach is intended to prevent submissions generated with cloud-based AI tools.
Groups may use any open-source LLM and fine-tune it for their own financial model.

(Ders projesi kapsamında her grup kendi büyük dil modelini (LLM) geliştirecektir. Notlandırma, geliştirdiğiniz LLM'lerin test edilmesiyle yapılacaktır.
Bu yaklaşımın amacı, bulut tabanlı yapay zekâ araçlarıyla üretilmiş ödevlerin önüne geçmektir.
Gruplar, herhangi bir açık kaynak LLM'i kendi finansal modellerine göre ince ayar (fine-tune) yapmakta serbesttir.)

## PROJE DUYURUSU – "KENDİ LLM'İNİZİ GELİŞTİRMEK" NE DEMEK?

Temel ilke: LLM yorumlar ve açıklar. Python araçları hesaplar. Harness kontrol eder. Backtest doğrular. Model yerel çalışır.

1. Sıfırdan model eğitmeyeceksiniz.
   Açık kaynak bir LLM seçip projenin finansal görevlerine göre ince ayar (fine-tuning) yapacaksınız. Qwen, Llama, Mistral, Gemma veya Phi gibi modeller kullanılabilir. 1–8 milyar parametrelik küçük modeller önerilir. Bu modeller LoRA/QLoRA gibi yöntemlerle tek bir GPU'da eğitilebilir.

2. LLM sistemin "hesaplayıcısı" değil, "yorumcusudur".
   Modeliniz şunları yapabilmelidir:
   - Kullanıcının sorusunu anlamak (ör. "Sektörünün gerisinde kalan bankaları bul").
   - Doğru MCP aracını doğru parametrelerle çağırmak (ör. rank_sector_relative_strength, run_backtest).
   - Yalnızca araçların döndürdüğü sonuçlara dayanarak açıklama yazmak.
   - Yalnızca izin verilen eylem setinden sonuç vermek (WATCH, POTENTIAL_CATCH_UP_CANDIDATE, ANALYSIS_UNSAFE vb.).
   - Sayı uydurmamak ve yatırım tavsiyesi vermemek. Kanıt yetersizse INVESTIGATE veya ANALYSIS_UNSAFE demek.

3. İnce ayar verisini siz hazırlayacaksınız.
   Örnek eğitim kaydı: soru → doğru araç çağrısı → araç çıktısı → kanıta dayalı açıklama.
   Kayıtlar dört zorunlu senaryodan üretilmelidir:
   - Sektörün gerisinde kalan hisseler (catch-up)
   - Haftanın günü ve çok günlü örüntüler
   - Teknik dönüşler
   - Çeyreklik temel veriler ve fiyat tepkisi

4. Final sistem tamamen yerel çalışmalıdır.
   Teslim edilen sistemde ChatGPT, Claude, Gemini veya başka bir bulut yapay zekâ API'sine çağrı OLMAYACAKTIR. Model, internet bağlantısı olmadan yerel makinede çalışabilmelidir (Ollama, llama.cpp, vLLM veya Hugging Face Transformers ile).

5. Notlandırma: modeliniz canlı olarak test edilecek.
   Önceden verilmeyen sorular sorulacaktır. Değerlendirme, dokümanın 30. bölümündeki metriklere göre yapılacaktır:
   - Sayısal halüsinasyon oranı
   - Hatalı araç çağrısı oranı
   - Kanıtsız sonuç oranı
   - Kanıt bütünlüğü ve tekrarlanabilirlik
   - Kural ihlalleri (ör. yatırım tavsiyesi verme, zorunlu kalite/backtest adımını atlama)

6. Sunum ve rapor.
   Modelinizi sunum sırasında canlı olarak gösterin ve raporda şunları açıkça belirtin:
   - Kullandığınız temel model ve neden onu seçtiğiniz
   - İnce ayar verinizi nasıl hazırladığınız ve kaç örnek kullandığınız
   - Eğitim yöntemi ve ayarlar (ör. LoRA/QLoRA, hiperparametreler)
   - Modeli yerelde nasıl çalıştırdığınız
   - Temel model ile ince ayarlı modelin karşılaştırması: fine-tuning neyi iyileştirdi?
   - Modelinizin bilinen sınırlamaları
