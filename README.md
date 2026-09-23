# TGBT: Çoklu Hesap Telegram Otomasyon Sistemi

Tek bir **controller bot** (aiogram 3) üzerinden birden fazla Telegram hesabını (**userbot**, Telethon)
yöneten; otomatik grup mesajı, DM toplu mesaj, DM oto-cevap ve kelime filtreleri sunan asenkron sistem.

- **Controller bot:** aiogram 3.31, FSM ile çok adımlı akışlar, inline klavyeler
- **Userbot'lar:** Telethon 1.45, hesap başına tek bağlantı, hesap başına tek döngü (`asyncio.Task`)
- **Veritabanı:** SQLAlchemy 2.0 async. Geliştirmede SQLite, üretimde PostgreSQL (asyncpg). Şema Alembic ile yönetilir.
- **Redis:** FSM durumları ve dağıtık döngü kilidi. Aynı hesabın döngüsü iki süreçte aynı anda çalışmaz.
- **Güvenlik:** userbot oturumları DB'de **Fernet ile şifreli** StringSession olarak durur. Erişim beyaz liste ile sınırlıdır.

---

## Özellikler

| Özellik | Açıklama |
|---|---|
| 🚀 Otomatik mesaj | Gruplara **3'lü paketler** hâlinde gönderir. Paketler arasında `0-5` sn rastgele, tur sonunda `60` dk bekler (değerler ayarlanabilir). |
| 📷 Fotoğraf | Fotoğraf + açıklama. Fotoğraf her turda **bir kez** yüklenir, diğer gruplara Telegram'daki kopyası gider. |
| 🖼 Medya → metin | Medya yasak olan gruplara otomatik olarak yalnızca metin gönderir. |
| ↗️ Forward / link | Bot'a kanal postunu forward etmek veya `t.me/kanal/123` linki göndermek yeterli. Başlıklı ya da başlıksız iletilebilir. |
| 📞 Kişi paylaşma | Otomatik mesajın ardından kişi kartı gönderir. |
| 💌 DM toplu mesaj | DM listesindeki herkese gönderir (botlar ve silinmiş hesaplar hariç). İlerleme canlı izlenir, istenince durdurulabilir. |
| 💬 Akıllı DM oto-cevap | Hesaba **ilk kez** yazan kişiye bir kez cevap verir. Sohbet geçmişi olan tanıdıklara yazmaz. |
| 🎯 Yanıt filtreleri | Gruplarda kelime yakalanınca mesaja yanıt verir. Türkçe büyük/küçük harf uyumludur (İ/ı). Üç eşleşme tipi ve grup başına bekleme süresi vardır. |
| 🚫 İstisnalar | Gruplar listeden seçilir veya `@kullanıcı` / link / ID ile eklenir. İstisna gruplara mesaj gitmez, filtreler de çalışmaz. |
| 📁 Arşiv kontrolü | Arşivlenmiş gruplara gönderim açılıp kapatılabilir. |
| ✨ Biçimlendirme | Kalın, italik, kod, spoiler, alıntı ve **özel emoji** olduğu gibi aktarılır (entity'ler UTF-16 offset'leriyle birebir). |
| 🧪 Sistem kontrolü | Bağlantı, ping, döngü durumu, son tur istatistikleri, flood durumu ve grup sayısını gösterir. |
| 💾 .session dışa aktarma | Şifreli oturumdan Telethon uyumlu `.session` dosyası üretir. |

## Klasör yapısı

```
app/
├── __main__.py              # giriş noktası (python -m app)
├── config.py                # .env ayarları (pydantic-settings)
├── bot_factory.py           # Bot, Dispatcher, FSM storage
├── texts.py                 # tüm Türkçe arayüz metinleri
├── database/
│   ├── base.py              # async engine, UTC datetime tipi
│   ├── models.py            # User, Account, AutoMessageConfig, ExceptionChat, DMAutoReplyConfig, ReplyFilter…
│   ├── repositories.py      # sorgular + sahiplik kontrolü (get_owned_account)
│   └── migrate.py           # açılışta Alembic upgrade
├── handlers/                # aiogram router'ları
│   ├── start.py             # /start, hesap listesi, bilgi, /cancel
│   ├── login_handler.py     # oturum adı → telefon → kod → 2FA
│   ├── account_panel.py     # panel, toggle'lar, sistem kontrolü, silme
│   ├── auto_message.py      # 3 adımlı otomatik mesaj sihirbazı
│   ├── other_features.py    # 🔧 Diğer Özellikler
│   ├── dm.py                # DM toplu mesaj + oto-cevap ayarları
│   ├── reply_filters.py     # 🎯 filtreler
│   ├── exceptions.py        # 🚫 istisnalar
│   ├── admin.py             # /izin /kaldir /yasakla /kullanicilar /durum
│   └── fallback.py          # yakalanmayan mesajlar
├── keyboards/               # CallbackData + inline klavyeler
├── middlewares/             # DB oturumu, beyaz liste
├── states/                  # FSM durumları
├── userbots/
│   ├── userbot_manager.py   # istemci yaşam döngüsü, login, worker/broadcast görevleri
│   ├── worker.py            # zamanlanmış mesaj döngüsü
│   ├── sender.py            # metin/foto/forward/kişi gönderimi + fallback
│   ├── event_handlers.py    # DM oto-cevap + grup filtreleri
│   ├── broadcast.py         # DM toplu gönderim
│   ├── runtime.py           # hesap başına bellek içi durum/önbellek
│   └── errors.py            # Telethon hata sınıflandırması
└── utils/                   # flood kapısı, Redis kilidi, şifreleme, entity & metin yardımcıları
migrations/                  # Alembic
tests/                       # 76 test (uçtan uca bot akışları dahil)
```

## Kurulum

### 1) Ön hazırlık
1. [@BotFather](https://t.me/BotFather)'dan bir bot oluşturup **BOT_TOKEN** alın.
2. [my.telegram.org](https://my.telegram.org) → *API development tools* bölümünden **API_ID** ve **API_HASH** alın.
3. `.env.example` dosyasını `.env` olarak kopyalayıp doldurun. Şifreleme anahtarı için:
   ```bash
   python -m app.tools.genkey   # çıktıyı SESSION_ENCRYPTION_KEY'e yazın
   ```
   > ⚠️ Bu anahtarı yedekleyin. Kaybolursa kayıtlı hesapların oturumları çözülemez.

### 2a) Docker ile (önerilen)
```bash
mkdir -p data && sudo chown 1000:1000 data   # konteyner kullanıcısı yazabilsin
docker compose up -d --build
docker compose logs -f bot
```
PostgreSQL ve Redis compose tarafından ayağa kaldırılır. Migration'lar açılışta otomatik uygulanır.

### 2b) Yerel geliştirme
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app          # SQLite + (REDIS_URL boşsa) bellek içi FSM
```

## Kullanım

1. Bot'a `/start` yazın. İlk hesap yoksa doğrudan **oturum adı** istenir (örn. `Deneme`).
2. Telefon numarasını uluslararası formatta girin: `+905xxxxxxxxx`.
3. Telegram'dan gelen kodu **tuş takımıyla** veya `1 2 3 4 5` şeklinde boşluklu yazarak girin.
   Kod sohbette düz hâlde paylaşılırsa Telegram onu iptal edebilir; tuş takımı bu riski tamamen ortadan kaldırır.
   Yazılı kod ve 2FA şifresi okunduktan hemen sonra silinir.
4. Hesap panelinden **🚀 Otomatik Mesaj Ayarları** ile mesaj, bekleme (`0-5` veya `0 5`) ve döngü süresini (`60`) ayarlayın,
   ardından **❌ Otomatik Mesajı Başlat**'a basın.

İşlemleri her adımda `/cancel` ile iptal edebilirsiniz.

### Admin komutları
| Komut | İşlev |
|---|---|
| `/izin <id>` | Kullanıcıya erişim verir (yeni kullanıcılar için adminlere onay butonu da gelir). |
| `/kaldir <id>` | Erişimi kaldırır ve hesaplarını durdurur. |
| `/yasakla <id>` | Kullanıcıyı yasaklar ve hesaplarını durdurur. |
| `/kullanicilar` | Kullanıcı listesi. |
| `/durum` | Bağlı userbot, çalışan döngü ve gönderim sayıları. |

## Döngü (worker) nasıl çalışır?

```
┌─ ayarları DB'den oku (panel değişiklikleri bir sonraki turda geçerli)
│  son turdan beri cycle_minutes geçmediyse kalan süreyi bekle  ← restart sonrası tekrar spam yok
│  hedefler = gruplar − istisnalar − yazma yasağı olanlar − slow-mode'dakiler (arşiv: ayara göre)
│  for paket in 3'lü paketler:
│      paket içi gönderimler paralel  (asyncio.gather)
│      paketler arası: random(min_delay, max_delay) sn
│  istatistikleri yaz → cycle_minutes dk bekle
└─ başa dön
```

Bütün beklemeler `asyncio.sleep` ile yapılır, event loop hiç bloklanmaz. Durdurma (`task.cancel()`) beklemenin ortasında bile anında çalışır.
Aynı hesap iki süreçte çalışmasın diye Redis kilidi (`SET NX PX` + heartbeat) kullanılır.

### Hata yönetimi
| Hata | Davranış |
|---|---|
| `FloodWaitError` | **Hesap genelinde** bekleme kapısı kapanır (paralel gönderimler de bekler), süre bitince tekrar dener. Uzun beklemelerde sahibine bildirim gider. |
| `SlowModeWaitError` | O grup, belirtilen süre boyunca atlanır. |
| `ChatSendMedia/PhotosForbidden`, `ChatForwardsRestricted` | Metinle tekrar gönderilir (ayarlıysa). |
| `ChatWriteForbidden`, `UserBannedInChannel`, `ChannelPrivate`… | Grup atlanır, döngü devam eder. |
| `PeerFloodError` | Spam kısıtı: döngü durur, hesap 🚫 olarak işaretlenir, sahibine bildirim gider. |
| `AuthKeyUnregistered`, `SessionRevoked`, `UserDeactivated` | Oturum ⚠️ olarak işaretlenir, istemci kapanır, sahibine bildirim gider. |
| Ağ kopması | Telethon otomatik yeniden bağlanır. Bakım döngüsü her dakika kopan veya açılışta bağlanamayan hesapları tekrar dener. |
| Beklenmeyen hata | Exponential backoff (1 dk → 30 dk). Art arda 3 hatada bildirim gider. Çöken worker 60 sn sonra yeniden başlar. |

## Geliştirme

```bash
pytest                   # 76 test (SQLite)
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost/tgbt pytest   # PostgreSQL ile
ruff check . && ruff format --check .
alembic revision --autogenerate -m "açıklama"   # model değişikliğinden sonra
```

Testler gerçek `Dispatcher` + `UserbotManager` ile koşar. Telegram Bot API ve Telethon sahte nesnelerle taklit edilir:
login'den panele, otomatik mesaj sihirbazından DM toplu gönderime kadar kullanıcı akışları uçtan uca doğrulanır.

## Riskler ve bilinen sınırlar

- **Telegram spam politikası:** Gruplara otomatik reklam atmak, hesabın spam kısıtına (PeerFlood) alınmasına veya
  yasaklanmasına yol açabilir. Sistem bunu algılar, gönderimi durdurur ve sizi bilgilendirir, ancak Telegram'ın kararını
  engelleyemez. Yeni açılmış hesaplarla ve reklama izin vermeyen gruplarda dikkatli olun. Çok kısa döngüler için panel uyarı verir.
- **Özel emoji:** yalnızca Premium userbot hesaplarında görünür. Diğer hesaplarda standart emojiye düşer.
- **Login yarıda kalırsa:** Bot yeniden başlarsa yarım kalan giriş işlemi sıfırlanır, `/start` ile baştan başlayın.
- **Dışa aktarılan `.session` dosyası** hesaba tam erişim verir. Kimseyle paylaşmayın.
