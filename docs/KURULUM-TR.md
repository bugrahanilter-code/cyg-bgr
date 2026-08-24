# Kurulum ve Kullanım Rehberi (Türkçe)

> ## BU SİSTEM KÂR GARANTİSİ VERMEZ
>
> Kripto para ticareti, özellikle kaldıraçlı işlem, paranızın tamamını
> kaybettirebilir. Backtest ve paper trading sonuçları geçmişi anlatır,
> geleceği tahmin etmez. Bu yazılım yatırım tavsiyesi değildir.

Bu rehber, hiç yazılım bilgisi olmayan bir kullanıcı için yazılmıştır.

---

## 0. Docker çalışmıyorsa (muhtemelen sizin durumunuz)

Docker Desktop **"Virtualization support not detected"** hatası veriyorsa,
bilgisayarınızın BIOS/UEFI ayarlarında işlemci sanallaştırması kapalıdır.

**Docker'sız da çalışır.** İki seçeneğiniz var:

### Seçenek A: Docker'sız çalıştır (en hızlı, önerilen)

Gereken: **Python 3.11+** ve **Node.js 20+** (docker gerekmez).

1. `scripts` klasöründeki `start-backend.bat` dosyasına çift tıklayın.
   Açılan siyah pencereyi **kapatmayın**.
2. `scripts` klasöründeki `start-frontend.bat` dosyasına çift tıklayın.
   Bu pencereyi de **kapatmayın**.
3. Tarayıcıdan <http://localhost:3000> adresini açın.

Durdurmak için iki pencerede de `Ctrl + C` yapın veya pencereleri kapatın.

Bu modda veritabanı olarak PostgreSQL yerine **SQLite** kullanılır
(`backend/data/dev.db` dosyası). Tek kullanıcılı yerel çalışma için yeterlidir.

### Seçenek B: Sanallaştırmayı açıp Docker kullan

1. Bilgisayarı yeniden başlatın, açılışta BIOS/UEFI tuşuna basın
   (genelde `F2`, `F10`, `Del` veya `Esc`).
2. Şu ayarı bulup **Enabled** yapın:
   * Intel işlemcide: `Intel Virtualization Technology` veya `Intel VT-x`
   * AMD işlemcide: `SVM Mode`
3. Kaydedip çıkın (`F10`).
4. Windows açıldıktan sonra yönetici PowerShell'de:

   ```powershell
   wsl --install
   ```

5. Bilgisayarı tekrar başlatın, Docker Desktop'ı açın, "Engine running"
   yazmasını bekleyin.
6. Sonra bu rehberdeki normal Docker adımlarına devam edin.

---

## 1. Docker ile kurulum (sanallaştırma açıksa)

Sadece **Docker Desktop**. Python veya Node.js kurmanıza gerek yok.

1. <https://www.docker.com/products/docker-desktop/> adresinden Docker Desktop
   indirin ve kurun.
2. Bilgisayarı yeniden başlatın (Windows genelde ister).
3. Docker Desktop'ı açın ve sol altta "Engine running" yazana kadar bekleyin.

## 2. Docker ile projeyi başlatma

1. Bu klasörde bir terminal açın.
   * Windows: klasöre girin, adres çubuğuna `powershell` yazıp Enter'a basın.
2. Ayar dosyasını kopyalayın:

   ```powershell
   Copy-Item .env.example .env
   ```

3. `.env` dosyasını Not Defteri ile açın. Sadece şu satırı değiştirin:

   ```
   POSTGRES_PASSWORD=buraya_istediginiz_bir_sifre
   ```

   Binance ile ilgili satırları **boş bırakın**. Şimdilik gerekmiyor.

4. Sistemi başlatın:

   ```powershell
   docker compose up --build
   ```

5. İlk kurulum 5-10 dakika sürebilir. Bittiğinde tarayıcıdan
   <http://localhost:3000> adresini açın.

Panel açıldıysa her şey hazır demektir. Sistem otomatik olarak **paper trading**
(sanal para) modunda çalışmaya başlar.

## 3. Durdurma ve yeniden başlatma (Docker)

| Ne yapmak istiyorsunuz | Komut |
| --- | --- |
| Durdurmak | Terminalde `Ctrl + C`, sonra `docker compose down` |
| Arka planda başlatmak | `docker compose up -d` |
| Logları görmek | `docker compose logs -f backend` |
| Sadece backend'i yeniden başlatmak | `docker compose restart backend` |
| Her şeyi silip sıfırdan başlamak | `docker compose down -v` sonra `docker compose up --build` |

## 4. Paneldeki sayfalar

| Sayfa | Ne işe yarar |
| --- | --- |
| Markets | Binance'teki **bütün** coinler, canlı 24 saatlik veriler, arama/sıralama, TradingView grafiği, işleme açma |
| Overview | Genel durum: bakiye, kâr/zarar, açık pozisyonlar, günlük hedef |
| Positions | Açık pozisyonların detayı, tek tuşla kapatma |
| Trades | Tüm işlem geçmişi, filtrelerle |
| Strategies | Üç stratejiyi aç/kapat, ayarlarını değiştir, sinyalleri gör |
| Comparison | Stratejileri yan yana karşılaştır |
| Backtest Lab | Geçmiş veriyle strateji testi |
| Matrix Backtest | Bütün stratejileri, bütün coinlerde, bütün zaman dilimlerinde topluca test et |
| Rotation | 24 saatte en çok yükselen coinleri otomatik olarak işleme aç, saat başı güncelle |
| Risk Settings | Risk limitleri (en önemli sayfa) |
| System | Sistem sağlığı, motor başlat/durdur, olay kayıtları |
| Settings | Binance API, coin seçimi, canlı işlem anahtarı |

## 5. Backtest nasıl yapılır?

1. **Backtest Lab** sayfasını açın.
2. Strateji seçin (örneğin *Trend Following*).
3. Coin seçin (BTC/USDT), zaman dilimi seçin (15m).
4. Başlangıç ve bitiş tarihi seçin. İlk denemede son 3-6 ay yeterlidir.
5. Komisyon, slippage ve funding değerlerine dokunmayın; gerçekçi ayarlanmıştır.
6. **RUN BACKTEST** tuşuna basın. İlk çalıştırmada veri indirileceği için
   1-2 dakika sürebilir.
7. Sonuçlar aşağıda grafik ve tablo olarak çıkar.

**Önemli:** Sonuç çok güzel görünüyorsa şüphelenin. *Walk-forward analysis*
seçeneğini açın; bu, stratejiyi verinin bir kısmında ayarlayıp geri kalanında
test eder. Sadece "out-of-sample" sonuçlar anlamlıdır.

Şu durumlarda sonuca güvenmeyin:
* 30'dan az işlem varsa
* Bir ayarı biraz değiştirince sonuç çöküyorsa
* Sadece tek bir coinde çalışıyorsa

## 6. Paper trading (sanal para ile işlem)

Sistem zaten bu modda başlar. Yapmanız gereken bir şey yok.

* Sanal bakiye varsayılan olarak 10.000 USDT'dir.
* Gerçek Binance fiyatları kullanılır ama **gerçek emir gönderilmez**.
* Komisyon, slippage ve funding gerçeğe yakın simüle edilir.
* Overview sayfasında "Engine: running" ve "Market Data" yeşil olmalıdır.

Hesabı sıfırlamak isterseniz: Settings -> Paper account -> *Reset the paper
account*.

**En az birkaç hafta paper trading yapmadan canlı işleme geçmeyin.**

## 7. Binance API anahtarı nasıl alınır?

Backtest ve paper trading için **API anahtarına gerek yoktur**. Sadece gerçek
bakiyenizi görmek veya canlı işlem yapmak istiyorsanız gerekir.

1. Binance hesabınıza girin -> **API Management** -> **Create API**.
2. Bir isim verin, örneğin `local-trading-bot`.
3. Güvenlik doğrulamalarını tamamlayın.
4. API Key ve Secret Key'i kopyalayın. **Secret sadece bir kez gösterilir.**
5. İzinleri şöyle ayarlayın:

| İzin | Ayar |
| --- | --- |
| Enable Reading | **AÇIK** |
| Enable Futures | Vadeli işlem yapacaksanız açık |
| **Enable Withdrawals (Para çekme)** | **KESİNLİKLE KAPALI** |
| IP kısıtlaması | Kendi IP adresinizi girin (önerilir) |

Bu yazılım hiçbir zaman para çekme işlemi yapmaz. Anahtarınızda para çekme
izni açıksa panelde kırmızı uyarı görürsünüz.

İlk denemeleriniz için <https://testnet.binancefuture.com/> adresindeki
**testnet** hesabını kullanın ve Settings sayfasındaki "Use the Binance testnet"
düğmesini açın.

## 8. API anahtarını nereye gireceğim?

**Settings** sayfası -> **Binance API** bölümü.

* Anahtar şifrelenerek saklanır.
* Secret bir daha asla ekranda gösterilmez.
* Loglara asla yazılmaz.
* Tarayıcıya asla geri gönderilmez.

Kaydettikten sonra **Test connection** düğmesine basın.

## 9. Canlı işlem (Live Trading) nasıl açılır?

Canlı işlem varsayılan olarak **KAPALIDIR** ve kendi kendine açılamaz. Açmak
için sırayla:

1. API anahtarını kaydedin (Settings sayfası).
2. **Test connection** başarılı olsun.
3. Para çekme izninin kapalı olduğunu onaylayın.
4. Risk ayarlarını gözden geçirin (Risk Settings sayfası).
5. `.env` dosyasını açın ve şu satırı değiştirin:

   ```
   LIVE_TRADING_ENABLED=true
   ```

6. Backend'i yeniden başlatın:

   ```powershell
   docker compose restart backend
   ```

7. Settings -> Live trading bölümünde iki onay kutusunu işaretleyin ve
   **ENABLE LIVE TRADING** tuşuna basın.

Üst barda kırmızı `LIVE ORDERS ENABLED` yazısı görünür. Geri dönmek için
*Switch back to paper trading* tuşuna basın.

**Önce testnet, sonra kaybetmeyi göze alabileceğiniz çok küçük bir miktar.**

## 10. Risk ayarları

Risk Settings sayfasındaki varsayılan değerler bilinçli olarak temkinlidir:

| Ayar | Varsayılan | Anlamı |
| --- | --- | --- |
| Risk per trade | %0.5 | Stop olursa kaybedilecek miktar |
| Daily profit target | %2 | Ulaşınca yeni işlem açılmaz |
| Daily loss limit | %1.5 | Aşılınca güvenli moda geçilir |
| Max trades/day | 15 | Aşırı işlem koruması |
| Max concurrent positions | 2 | Aynı anda açık pozisyon sayısı |
| Max consecutive losses | 3 | Üst üste kayıptan sonra dur |
| Cooldown | 30 dk | Kayıptan sonra bekleme |
| Max drawdown | %15 | Hesap geneli sert durdurma |
| Max leverage | 3 | Kaldıraç üst sınırı |

Pozisyon büyüklüğü **sadece kaldıraca göre** hesaplanmaz. Bakiye, işlem başına
risk ve stop mesafesi kullanılır; sonra borsa kuralları ve marj limitleriyle
kısıtlanır.

Günlük hedefe ulaşıldığında bot yeni işlem açmayı durdurur, açık pozisyonları
yönetmeye devam eder. Hedefe ulaşmak için asla riski artırmaz.

### Stop loss ve take profit

İkisi de **Risk Settings** sayfasından ayarlanır ve ikisi de tek bir ortak
fonksiyonla karara bağlanır — backtester ve canlı motor aynı fonksiyonu çağırır.
Bu önemli: burada değiştirdiğiniz bir kural simülasyonu ve gerçek emirleri
birlikte hareket ettirir, yani backtest anlamını korur.

**Stop loss** üç mod:

| Mod | Ne yapar |
| --- | --- |
| Strategy (varsayılan) | Her strateji kendi stopunu koyar (genelde ATR bazlı) |
| Fixed | Stratejiyi yok sayar, her işlemde sabit yüzde |
| Bounded | Strateji seçer ama sonuç min/maks bandına sıkıştırılır |

Min/maks bandı, `fixed` dışındaki her modda **güvenlik zarfı** olarak uygulanır —
%40 stop isteyen bir strateji hata yapıyordur, tercih yapmıyordur.

Pozisyon büyüklüğü **karara bağlanan** stoptan hesaplanır. Yani stopu
genişletmek pozisyonu **küçültür**, riske attığınız parayı artırmaz.

**Take profit** dört mod: `strategy`, `fixed_pct`, `risk_multiple` (2R = stopun
iki katı uzaklıkta hedef; genişletilen stopu takip eder) ve `none`.

> **Bu platformda ölçülen sonuç:** take profit'i kaldırmak, **93 eşleştirilmiş
> testin 70'inde** beklentiyi iyileştirdi — aynı strateji, aynı market, aynı
> zaman dilimi, sadece bu tek ayar değiştirilerek; 6 strateji, 8 market,
> 2 zaman dilimi, 12 ay. Medyan beklenti **+0,048R'den +0,132R'ye** çıktı.
>
> Mekanizma trend takipçilerinin anlattığı şey: bu sistemler, birçok küçük zararı
> ödeyen birkaç büyük kazançtan para kazanır ve sabit hedef tam olarak o
> kazançları kesip atar. Take profit'i kaldırınca **kazanma oranı düşer** —
> bu yüzden panelde yanlış görünür, equity eğrisinde doğrudur.
>
> Bir yıl ve tek bir maliyet modeli, yani kesin gerçek değil güçlü bir hipotez.
> Ama 93 bağımsız hücrede doğrulanmış **yapısal** bir değişiklik — 74
> kombinasyonun en iyisini seçmekten çok daha sağlam bir kanıt.

**Trailing stop ve break-even** de burada. Stop sadece kâr yönünde hareket eder;
gevşetilemez. İkisi de varsayılan olarak kapalı ve ikisinin de bir bedeli var:
aynı testte BTC/USDT'de %2 trailing ve 1R'de break-even sonuçları **kötüleştirdi**,
çünkü kazançlı işlemleri başabaşa çeviriyorlar. Bunlar araçtır, bedava iyileştirme
değil.

**Minimum ödül/risk** oranı, hedefi stopa göre fazla yakın olan girişleri
reddeder. Varsayılan kapalı.

## 11. ACİL DURDURMA

Üst bardaki kırmızı **EMERGENCY STOP** düğmesi her sayfada vardır. Üç seçenek
sunar:

1. **Yeni işlem açmayı durdur** - açık pozisyonlar stop/hedefleriyle devam eder.
2. **Tüm pozisyonları kapat** - hepsi piyasa fiyatından kapatılır, sonra durur.
3. **Sistemi tamamen durdur** - motor durur ve siz açana kadar, bilgisayar
   yeniden başlasa bile durmuş kalır.

## 12. Sık karşılaşılan sorunlar

| Sorun | Çözüm |
| --- | --- |
| Panelde "The request timed out" | Backend çalışmıyor. `docker compose logs -f backend` |
| `docker: command not found` | Docker Desktop kurulu değil veya açık değil |
| Port 3000 kullanımda | `.env` içinde `FRONTEND_PORT=3001` yapın |
| Market Data kırmızı | İnternet yok veya Binance'a erişilemiyor |
| "Binance authentication failed" | Anahtar/secret yanlış ya da IP kısıtlaması engelliyor |
| Hiç işlem açılmıyor | Normaldir. Stratejiler şartların oluşmasını bekler; Strategies sayfasında güncel sinyali ve sebebini görebilirsiniz |
| Backtest "Not enough candles" diyor | Daha uzun tarih aralığı veya daha küçük zaman dilimi seçin |
| Anahtar çözülemiyor hatası | `SECRET_KEY` değişmiş; anahtarları yeniden girin |

## 13. Stratejiler ve coinler

### 14 strateji, 3 risk seviyesi

Panelde her stratejinin yanında risk rozeti görürsünüz:

| Seviye | Kaç tane | Ne demek |
| --- | --- | --- |
| **SAFE** | 4 | Az işlem, geniş stop, trendle birlikte, varsayılan olarak sadece alış |
| **MEDIUM** | 6 | Standart sistematik yaklaşımlar, trend ve güç filtreli |
| **RISKY** | 4 | Trende karşı, çok sık işlem veya yön belirsizken giriş |

**Güvenli (SAFE):** Golden Cross, Dual Momentum, VWAP Pullback, Keltner Trend
**Orta (MEDIUM):** Trend Following, Donchian Breakout, MACD, Ichimoku, SuperTrend,
Adaptive Momentum (15dk gün içi, 1s trend filtreli, 100 puanlık skor sistemi)
**Riskli (RISKY):** Mean Reversion, RSI Divergence, Volatility Breakout, Squeeze Momentum

"Güvenli" kelimesi **stratejinin yapısını** anlatır, sonucunu değil. Geniş stop
demek küçük zarar demek değildir; **daha seyrek** zarar demektir. Hepsinde para
kaybedebilirsiniz.

Her stratejinin nasıl çalıştığı, hangi varsayımlara dayandığı ve **hangi
durumlarda para kaybettiği** `docs/strategies/` klasöründe yazılıdır.

### Bütün Binance coinleri

**Markets** sayfası Binance vadeli borsasındaki **her USDT perpetual marketi**
listeler — şu an 525 tane. Her satırda canlı 24 saatlik veriler var:

| Sütun | Anlamı |
| --- | --- |
| Price | Son fiyat |
| 24h % | 24 saatlik değişim |
| 24h high / low | 24 saatlik en yüksek / en düşük |
| 24h range | Fiyat 24 saatlik bandın neresinde (0% = dip, 100% = tepe) |
| 24h volume | 24 saatlik USDT hacmi |
| Spread | Canlı alış-satış farkı |
| ATR % | Fiyatın yüzdesi olarak oynaklık |
| RSI | TradingView'in günlük RSI değeri |
| TV rating | TradingView'in teknik değerlendirmesi |
| **Round trip cost** | **Bir alım-satımın toplam maliyeti** |

**Round trip cost sütunu en önemlisi.** İçinde giriş komisyonu + çıkış
komisyonu + iki yönlü slippage + spread var. Bir stratejinin *herhangi bir
kazanç* elde etmesi için önce bu rakamı aşması gerekir. Düşük hacimli
coinlerde bu maliyet, şimdiye kadar bulunan her edge'den büyük çıktı.

İki durum bilinçli olarak ayrı tutulur:

* **Available (kullanılabilir)** — coin veritabanında, backtest yapılabilir.
  *Markets → "Import every market"* hepsini tek seferde ekler.
* **Enabled (işleme açık)** — bot her mumda o marketi de değerlendirir.
  Bu, coin başına ayrı bir tıklamadır. Sebebi: açık her market motora bir
  strateji değerlendirmesi ve risk motoruna bir pozisyon daha ekler.

Temiz kurulumda **sadece BTC/USDT ve ETH/USDT işleme açıktır.**

Tokenize hisse senetleri ve emtialar (SanDisk, altın, SpaceX gibi — Binance
bunları da aynı borsada listeliyor) **otomatik olarak eleniyor:** borsa
saatlerine göre çalışırlar, hafta sonu boşluk verirler ve buradaki her strateji
onları yanlış okur.

### Otomatik rotasyon (en çok yükselen coinler)

**Rotation** sayfası her marketi 24 saatlik değişime göre sıralar ve en üstteki
N tanesini işleme açık set yapar; varsayılan olarak saat başı yeniler.

**Kapalı ve dry-run modunda gelir.** Sebebi: botun neyi işlediğini sormadan
değiştiriyor. İki adımda açın — önce etkinleştirin, bir dry-run izleyin, sonra
dry-run işaretini kaldırın.

Açmadan önce şunu okuyun:

> Rotasyon bir **seçim kuralıdır, edge değildir.** Bir coin listeye *zaten
> yükseldiği için* girer; buradaki hiçbir şey yükselmeye devam edeceğini
> söylemez. Her yenileme ayrıca çıkan coinde bir kapanış, giren coinde bir açılış
> maliyeti öder — ve işlem maliyeti, bu platformda incelenen her stratejiyi yenen
> tek faktör.

Listeyi "dramatik" değil "işlenebilir" tutan kalite filtreleri:

| Filtre | Varsayılan | Neden |
| --- | ---: | --- |
| Minimum 24s hacim | $50M | 2 milyon dolarla pump olan coin emri kaldıramaz |
| Maksimum spread | %0,15 | Her girişte ve her çıkışta ödenir |
| Minimum listelenme yaşı | 30 gün | Geçen hafta listelenen coinin backtest geçmişi yok |
| Şundan büyük hareketleri yoksay | %100 | Genelde listeleme olayıdır, trend değil |
| Çıkarma sonrası bekleme | 4 saat | Sınırdaki coinin her saat girip çıkmasını önler |
| Çalışma başına maks. çıkarma | 10 | Tek bir volatil saat tüm defteri boşaltamaz |

Üç kural ayarlanamaz:

* **Açık pozisyonu olan market asla kapatılmaz.** Pozisyon kapanana kadar
  yerini korur, böylece motor çıkışı yönetmeye devam edebilir. Kayıtta
  *held open* olarak görünür.
* **Sadece-araştırma marketleri (EUR/USD, USD/JPY) asla seçilemez.**
* **Her reddin bir gerekçesi kaydedilir** — "bu coin neden listede yok"
  sorusu sonradan da cevaplanabilir.

### Sweep'ten strateji seçme

*Matrix Backtest → strateji seç*, bir sweep'teki her strateji/zaman dilimi
kombinasyonunu sıralar. Bilerek zor beğenir: 84 kombinasyonun en iyisini seçmek,
kendini kandırmanın klasik yoludur — o kadar çok denemede en iyi backtest sayısı,
stratejilerin hepsi değersiz olsa bile yaklaşık %99'luk dilimde çıkar.

Bir kombinasyonun geçmesi gereken dört bağımsız eşik:

1. **Yeterli işlem** — marketler toplamında 100, sayılan her markette 20.
2. **Genişlik, tek şanslı market değil** — test edildiği marketlerin en az
   %55'inde kârlı; *medyan* market üzerinden ölçülür, böylece tek bir aykırı
   değer kombinasyonu taşıyamaz.
3. **Maliyet farkında** — komisyon, spread ve slippage sonrası medyan beklenti
   R cinsinden pozitif.
4. **Örneklem dışı** — kazanan, onu seçmek için kullanılmayan bir pencerede
   yeniden çalıştırılır. Onay verilmeden uygulanamaz.

`NO_QUALIFYING_COMBINATION` normal bir cevaptır ve "en az kötü" satır yerine bu
döner — çünkü en az kötü satırı geri vermek, zarar eden bir konfigürasyonun
işleme başlamasının tam olarak yoludur.

### Altın ve forex (referans marketler)

Coinlerin yanına dört kripto-dışı market eklendi. Bunlar **işlem yapmak için
değil, karşılaştırma için** var:

| Market | Kaynak | İşlem açılabilir mi | Gidiş-dönüş maliyet | Seans |
| --- | --- | --- | ---: | --- |
| `XAU/USDT` | Binance perpetual | **Evet** | ~%0,12 | 7/24 |
| `PAXG/USDT` | Binance (altın destekli token) | **Evet** | ~%0,12 | 7/24 |
| `EUR/USD` | Yahoo Finance | **Hayır** | ~%0,02 | Pzt 22:00 – Cum 22:00 UTC |
| `USD/JPY` | Yahoo Finance | **Hayır** | ~%0,02 | Pzt 22:00 – Cum 22:00 UTC |

Buradaki bütün çalışmalar aynı duvara çarptı: küçük bir edge, işlem
maliyetlerinin altında kalıyor. Forex tam olarak **tek bir değişkeni**
değiştiriyor — EUR/USD'de bir alım-satım, kripto perpetual'ından yaklaşık altı
kat ucuz. Bir strateji orada kârlı, kriptoda zararlıysa sorun maliyettir.
İkisinde de zararlıysa stratejinin hiçbir yerde edge'i yoktur.

**EUR/USD ve USD/JPY ile işlem açılamaz.** Binance'in forex marketi yok, emir
hiçbir zaman gerçekleşemez. Bu iki yerde birden engellendi: Risk Engine bu
sembollerdeki her sinyali `SYMBOL_NOT_TRADABLE` ile reddediyor, emir
doğrulayıcı da süreçten çıkmadan önce son kontrolde reddediyor. Markets
sayfasında "backtest only" yazar, Enable düğmesi görünmez.

Forex sonuçlarını okumadan önce bilmeniz gereken üç tuzak:

1. **Hacim verisi yok.** Spot forexin merkezî bir borsası yok, dolayısıyla
   konsolide hacim de yok — her mumda hacim sıfır. `vwap_pullback` hacme bağlı
   olduğu için orada **hiç sinyal üretemez**; sıfır işlem göstermesi "çalıştı,
   bir şey bulamadı" değil, **"hiç çalışamadı"** demektir. Beş strateji daha
   (`adaptive_momentum`, `breakout_donchian`, `keltner_trend`, `mean_reversion`,
   `volatility_breakout`) hacmi birkaç puanlama bileşeninden biri olarak
   kullanır — işlem açmaya devam ederler, sadece o bileşen sürekli sıfır puan
   alır. Market detay panelinde iki grup da ayrı ayrı yazıyor. Bu ayrım
   tahminle değil ölçümle yapıldı: her strateji aynı fiyat serisi üzerinde iki
   kez çalıştırıldı, bir kez hacimle bir kez hacim sıfırlanmış olarak.
2. **Hafta sonu boşlukları.** Market cuma kapanır, pazar açılır. Buradaki her
   strateji kesintisiz akış varsayar ve bu boşluğu sıradan bir mum gibi okur.
3. **Kısa gün içi geçmiş.** Yahoo gün içi veriyi sınırlıyor: 1 saatin altında
   60 gün, 1 saatte 730 gün, günlükte yıllar. Yani 15 dakikalık bir forex
   sweep'i, hangi tarih aralığını isterseniz isteyin sadece 2 ayı kapsar.

Altında bu sorunların hiçbiri yok: `XAU/USDT` gerçek bir Binance perpetual'ı,
7/24 işlem görüyor, gerçek hacmi ve gerçek Binance maliyeti var. Aralık 2025'te
listelendiği için bir yıldan az geçmişi var.

### Toplu backtest (Matrix Backtest)

**Matrix Backtest** sayfası seçtiğiniz her stratejiyi, seçtiğiniz her coinde,
seçtiğiniz her zaman diliminde çalıştırır.

Çalıştırmadan önce **"Estimate the cost"** düğmesine basın. Sistem size kaç
backtest olacağını, ne kadar süreceğini ve ne kadar disk alacağını söyler.
Bu önemli, çünkü sayılar hızla büyür:

| Kapsam | Backtest sayısı | Süre | Disk |
| --- | ---: | ---: | ---: |
| 14 strateji x 30 coin x 6 zaman dilimi x 12 ay | 2.520 | ~53 dk | 1,4 GB |
| 14 strateji x 50 coin x 6 zaman dilimi x 12 ay | 4.200 | ~1,5 sa | 2,3 GB |
| 14 strateji x 523 coin x 6 zaman dilimi x 12 ay | 43.932 | ~15 sa | 24 GB |
| **14 strateji x 523 coin x 14 zaman dilimi x 24 ay** | **102.508** | **~397 sa (16 gün)** | **628 GB** |

Son satır fiziksel olarak yapılamaz demek değil, ama 16 gün kesintisiz CPU ve
628 GB disk demek. Asıl maliyeti 1m/3m/5m zaman dilimleri getirir: tek başına
1 dakikalık mumlar toplam işin dörtte üçünden fazlasını oluşturur. Üstelik
şimdiye kadarki bütün çalışmalarda işlem maliyetlerinin edge'i yendiği yer tam
olarak orasıydı.

Sonuç ekranında üç bölüm var:

1. **What the grid says** — kaç hücre kârlı, kaçı al-tut'u geçti, ortalama
   R cinsinden beklenti
2. **Where does the edge survive?** — strateji x zaman dilimi ısı haritası
   (yeşil = maliyetten sonra pozitif, kırmızı = negatif)
3. **Every result** — her hücrenin tam tablosu, filtrelenebilir ve sıralanabilir

İlginç bir hücre bulursanız aynı ayarlarla **Backtest Lab**'de tekrar çalıştırıp
equity eğrisini ve işlem listesini görebilirsiniz.

### Botu başlatma ve durdurma

Üst barda, kırmızı EMERGENCY STOP düğmesinin hemen solunda:

* **START BOT** — motor durmuşken görünür, çalıştırır
* **STOP BOT** — motor çalışırken görünür, durdurur (açık pozisyonlara dokunmaz)

Motor durduğunda yeni sinyal üretilmez ve yeni işlem açılmaz. Açık
pozisyonlarınızın stop ve hedefleri borsada duruyorsa orada kalmaya devam eder;
paper modda ise pozisyon yönetimi de durur.

## 14. Unutmayın

* Hiçbir strateji kâr garantisi vermez.
* Backtest sonuçları geleceğin garantisi değildir.
* Önce backtest, sonra haftalarca paper trading, sonra testnet, en son çok
  küçük gerçek para.
* Risk ayarlarını yükseltmek kazancı değil, kaybın büyüklüğünü artırır.
