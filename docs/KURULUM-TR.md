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
| Overview | Genel durum: bakiye, kâr/zarar, açık pozisyonlar, günlük hedef |
| Positions | Açık pozisyonların detayı, tek tuşla kapatma |
| Trades | Tüm işlem geçmişi, filtrelerle |
| Strategies | Üç stratejiyi aç/kapat, ayarlarını değiştir, sinyalleri gör |
| Comparison | Stratejileri yan yana karşılaştır |
| Backtest Lab | Geçmiş veriyle strateji testi |
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

## 13. Unutmayın

* Hiçbir strateji kâr garantisi vermez.
* Backtest sonuçları geleceğin garantisi değildir.
* Önce backtest, sonra haftalarca paper trading, sonra testnet, en son çok
  küçük gerçek para.
* Risk ayarlarını yükseltmek kazancı değil, kaybın büyüklüğünü artırır.
