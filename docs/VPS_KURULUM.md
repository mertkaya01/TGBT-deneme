# VPS Kurulum Rehberi

Bu rehber botu bir Linux sunucusuna (VPS) kurmayı, yedeklemeyi ve güncel tutmayı adım adım anlatır.
Kurulum yaklaşık **30-45 dakika** sürer. Sonrasında bot 7/24 çalışır, bilgisayarınızın açık olması gerekmez.

> Komutlar Windows'ta **PowerShell**'de, Mac'te **Terminal**'de çalıştırılır. `<...>` ile gösterilen
> yerleri kendi bilgilerinizle değiştirin.

---

## 0) Müşteriden alınacaklar (kurulumdan önce)

Bunları müşteri **kendi hesabıyla** oluşturmalı. Bot onun adına çalışır; bir gün siz çekilseniz de onda kalır.

| Ne | Nereden | Not |
|---|---|---|
| **BOT_TOKEN** | Telegram → [@BotFather](https://t.me/BotFather) → `/newbot` | Botun adı ve kullanıcı adı müşteriye ait olur. |
| **Inline mod** | @BotFather → `/setinline` → botu seç → bir yer tutucu yaz (ör. `oto-cevap`) | WhatsApp butonu için gerekli. |
| **API_ID / API_HASH** | [my.telegram.org](https://my.telegram.org) → telefonla giriş → *API development tools* | Müşterinin numarasıyla alınır. Bu değerler şifre gibi gizli tutulmalı. |
| **Müşterinin Telegram ID'si** | [@userinfobot](https://t.me/userinfobot)'a `/start` | `ADMIN_IDS` alanına yazılır. Destek verebilmek için kendi ID'nizi de ekleyin. |

> my.telegram.org bazen "ERROR" verir. Farklı bir tarayıcı veya gizli pencere ile tekrar denemek genelde çözer.
> Bu adımı müşteriyle ekran paylaşarak birlikte yapmak en kolayıdır.

## 1) Sunucu seçimi

| Bağlanacak hesap | Önerilen sunucu |
|---|---|
| 50'ye kadar | **2 vCPU, 4 GB RAM, 40 GB SSD** |
| 50-150 | 4 vCPU, 8 GB RAM |

- İşletim sistemi: **Ubuntu 24.04 LTS** (22.04 da olur).
- Konum: Avrupa (ör. Almanya, Hollanda). Telegram sunucularına yakındır.
- Herhangi bir VPS sağlayıcısı olur. Sunucuyu **müşterinin adına / kartıyla** açmak masrafı doğrudan ona bırakır.

> Hesap başına bellek kullanımı hesabın grup sayısına ve trafiğine göre değişir. İlk hafta
> `docker stats` ile izleyin (bkz. 7. adım). RAM sürekli %80'in üzerindeyse bir üst pakete geçin.

Sağlayıcı size bir **IP adresi** ve **root şifresi** (veya SSH anahtarı) verir.

## 2) Sunucuya bağlan

```powershell
ssh root@<SUNUCU_IP>
```
İlk bağlantıda `yes` yazın, ardından şifreyi girin (yazarken ekranda görünmez, normaldir).

**Önerilen: şifre yerine SSH anahtarı.** Kendi bilgisayarınızda bir kez:
```powershell
ssh-keygen -t ed25519            # sorulara Enter ile geçebilirsiniz
type $env:USERPROFILE\.ssh\id_ed25519.pub   # Windows (Mac/Linux: cat ~/.ssh/id_ed25519.pub)
```
Çıkan satırı sunucuda `~/.ssh/authorized_keys` dosyasına ekleyin (veya sağlayıcının panelindeki
"SSH Keys" bölümüne yapıştırın). Bundan sonra şifresiz bağlanırsınız.

## 3) Kodu indir ve sunucuyu hazırla

Önce git'i kurun (çoğu sunucuda zaten vardır):
```bash
apt-get update && apt-get install -y git
```
Repo özelse sunucunun kodu okuyabilmesi için bir **deploy key** tanımlayın (sunucuda):
```bash
ssh-keygen -t ed25519 -f ~/.ssh/tgbt_deploy -N ""
cat ~/.ssh/tgbt_deploy.pub
```
Çıkan satırı GitHub → repo → **Settings → Deploy keys → Add deploy key** bölümüne ekleyin (yazma izni **vermeyin**). Sonra:
```bash
cat >> ~/.ssh/config <<'CFG'
Host github.com
    IdentityFile ~/.ssh/tgbt_deploy
CFG
git clone git@github.com:<KULLANICI>/<REPO>.git /opt/tgbt
cd /opt/tgbt
sudo bash scripts/vps-setup.sh
```
`vps-setup.sh` şunları yapar: sistem güncellemeleri, otomatik güvenlik güncellemeleri, Docker kurulumu,
yalnızca SSH'a izin veren güvenlik duvarı ve 2 GB swap.

## 4) Botu kur

```bash
cd /opt/tgbt
cp .env.example .env
chmod 600 .env                                   # yalnızca siz okuyabilin
docker compose run --rm --no-deps --build bot python -m app.tools.genkey   # anahtarı kopyalayın
nano .env
```
`nano` içinde şunları doldurun (kaydet: `Ctrl+O` → Enter, çık: `Ctrl+X`):

```ini
BOT_TOKEN=<müşterinin bot token'ı>
API_ID=<müşterinin API_ID'si>
API_HASH=<müşterinin API_HASH'i>
SESSION_ENCRYPTION_KEY=<genkey çıktısı>
ADMIN_IDS=<müşteri ID>,<sizin ID>
MAX_ACCOUNTS_PER_USER=50                         # sunucu kapasitesine göre
POSTGRES_PASSWORD=<uzun ve rastgele bir şifre>
```

> ⚠️ `SESSION_ENCRYPTION_KEY`'i **kaybetmeyin ve değiştirmeyin**. Kaybolursa bağlı tüm hesapların yeniden
> eklenmesi gerekir. 6. adımdaki yedekler bu anahtarı da içerir.
>
> `POSTGRES_PASSWORD`'ü ilk kurulumda belirleyin. Veritabanı oluştuktan sonra değiştirirseniz bot bağlanamaz.

Başlatın:
```bash
mkdir -p data && sudo chown 1000:1000 data
docker compose up -d --build
docker compose logs -f bot        # "Controller bot hazır: @..." görünmeli, çıkmak için Ctrl+C
```
Artık müşteri Telegram'da botu açıp `/start` yazabilir (bkz. Kullanım Kılavuzu).

Sunucu yeniden başlarsa bot otomatik açılır (`restart: unless-stopped`).

## 5) Güncelleme

```bash
cd /opt/tgbt
bash scripts/update.sh
```
Önce yedek alır, sonra yeni kodu çekip botu yeniden başlatır. Veritabanı değişiklikleri otomatik uygulanır.
Hesaplar ve ayarlar korunur, açık olan döngüler kaldığı yerden devam eder.

## 6) Yedekleme

Elle yedek:
```bash
bash scripts/backup.sh            # ~/tgbt-backups/tgbt-YYYYmmdd-HHMMSS.tar.gz
```
Yedek; veritabanını, `.env`'i (şifreleme anahtarı dahil) ve yüklenen fotoğrafları içerir. Son 14 gün tutulur.

**Her gece otomatik yedek:**
```bash
crontab -e
```
En alta ekleyin:
```
0 4 * * * cd /opt/tgbt && bash scripts/backup.sh >> /var/log/tgbt-backup.log 2>&1
```

**Yedeği sunucu dışına alın** (sunucu tamamen giderse diye), kendi bilgisayarınızda:
```powershell
scp root@<SUNUCU_IP>:~/tgbt-backups/tgbt-*.tar.gz .
```
> Yedek dosyaları müşterinin hesaplarına erişim sağlayan bilgiler içerir. Güvenli bir yerde saklayın, kimseyle paylaşmayın.

**Geri yükleme** (veya yeni sunucuya taşıma):
```bash
bash scripts/restore.sh ~/tgbt-backups/tgbt-<TARİH>.tar.gz
```
Yeni bir sunucuya taşırken 3. adımı yapın, ardından **4. adım yerine** doğrudan bu komutu çalıştırın.
Veritabanı, `.env` ve fotoğraflar yedekten gelir, hesaplar tekrar giriş gerektirmeden bağlanır.

## 7) İzleme

| Komut | Ne gösterir |
|---|---|
| `docker compose ps` | Servisler çalışıyor mu (`Up` / `healthy`) |
| `docker compose logs -f bot` | Botun canlı logları |
| `docker compose logs --since 24h bot \| grep -iE "error\|peerflood\|hata"` | Son 24 saatteki hatalar |
| `docker stats` | RAM / CPU kullanımı |
| `df -h` | Disk doluluğu |

Telegram'dan: admin olarak `/durum` yazınca bağlı hesap, çalışan döngü ve gönderim sayıları görünür.

## 8) Aylık bakım kontrol listesi

- [ ] `bash scripts/update.sh` ile güncelle.
- [ ] `docker compose ps` ile her şeyin `Up` olduğunu doğrula.
- [ ] `docker stats` ile RAM'i kontrol et, `df -h` ile disk %80'in altında olsun.
- [ ] `ls -lh ~/tgbt-backups` ile gece yedeklerinin alındığını doğrula, birini sunucu dışına kopyala.
- [ ] Loglarda `PeerFlood` / oturum hatası var mı bak, varsa müşteriyi bilgilendir.
- [ ] Telegram'da `/durum` ile kontrol et.

## 9) Sık karşılaşılan sorunlar

| Belirti | Çözüm |
|---|---|
| Bot `/start`'a cevap vermiyor | `docker compose ps` → `bot` çalışmıyorsa `docker compose logs --tail 50 bot` ile hatayı okuyun. |
| `Yapılandırma hatası (.env): …` | Listelenen değeri `.env`'de düzeltin, sonra `docker compose up -d`. |
| `BOT_TOKEN geçersiz` | Token'ı @BotFather'dan yeniden kopyalayın (`/mybots` → bot → *API Token*). |
| "Bu botu kullanma yetkiniz yok" | Kişinin ID'sini `ADMIN_IDS`'e ekleyip `docker compose up -d` yapın, ya da admin olarak `/izin <id>` yazın. |
| WhatsApp butonu yerine link gidiyor | @BotFather → `/setinline` ile inline modu açın. |
| Hesap panelinde ⚠️ "Oturum geçersiz" | Oturum Telegram'dan kapatılmış. Hesabı panelden silip yeniden ekleyin. |
| Hesap panelinde 🚫 spam kısıtı | Telegram hesabı kısıtlamış. @SpamBot'a yazarak durumu öğrenin, döngü süresini uzatın. |
| `.env` değiştirdim ama etkisi yok | `docker compose restart` `.env`'i okumaz; `docker compose up -d` kullanın. |
| Disk doldu | `docker system prune -f` eski imajları temizler; yedek sayısını `KEEP_DAYS` ile azaltın. |
