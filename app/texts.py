"""Controller bot'un tüm Türkçe metinleri (HTML parse mode)."""

from __future__ import annotations

from html import escape

CANCEL_HINT = "⚠️ İptal etmek için /cancel yazın."

# --------------------------------------------------------------------------- genel

ACCESS_DENIED = (
    "⛔ Bu botu kullanma yetkiniz yok.\n\n"
    "Erişim için yöneticiye kullanıcı kimliğinizi iletin: <code>{user_id}</code>"
)
CANCELLED = "❌ İşlem iptal edildi."
NOTHING_TO_CANCEL = "İptal edilecek bir işlem yok."
ACCOUNT_NOT_FOUND = "Hesap bulunamadı."
UNKNOWN_INPUT = (
    "Anlamadım. Menüyü açmak için /start yazın; bir hesabı açmak için adını yazabilirsiniz."
)
USE_BUTTONS = "Lütfen menüdeki butonları kullanın."
NOT_CONNECTED = "⚠️ Bu hesap şu an bağlı değil. Sistem Kontrolu'ndan yeniden bağlanmayı deneyin."

WELCOME_NEW = (
    "👋 <b>Hoş geldiniz!</b>\n\n"
    "Telegram hesaplarınızı bağlayıp otomatik mesaj, DM ve grup yönetimini "
    "buradan yapabilirsiniz.\n"
    "Başlamak için ilk hesabınızı ekleyelim."
)
ACCOUNTS_TITLE = (
    "📱 <b>Hesaplarınız</b> ({count}/{limit}){page_info}\n"
    "🟢 {running} çalışıyor · ⚪ {stopped} kapalı · ⚠️ {problem} sorunlu\n\n"
    "Yönetmek istediğiniz hesabı seçin:{search_hint}"
)
ACCOUNTS_PAGE_INFO = " — sayfa {page}/{pages}"
ACCOUNTS_SEARCH_HINT = "\n💡 Hesabı hızlı açmak için adını yazıp gönderin."
ACCOUNT_SEARCH_RESULTS = "🔍 <b>{query}</b> için bulunan hesaplar:"
SLOT_LIMIT_REACHED = (
    "⚠️ Hesap limitine ulaştınız ({limit}). Yeni hesap eklemek için önce bir hesabı silin."
)

INFO = (
    "ℹ️ <b>Bu Bot Ne İşe Yarar?</b>\n\n"
    "Ben, Telegram hesaplarınızı (userbot) yönetmek ve otomatize etmek için tasarlanmış "
    "gelişmiş bir asistanım.\n\n"
    "<b>Temel Özelliklerim:</b>\n\n"
    "🚀 <b>Otomatik Mesajlaşma:</b> Belirlediğiniz gruplara, ayarladığınız mesajı istediğiniz "
    "zaman aralıklarıyla otomatik olarak gönderirim.\n\n"
    "📷 <b>Fotoğraf Desteği:</b> Otomatik mesajlarınıza fotoğraf ekleyebilir, medya "
    "gönderilemeyen gruplara otomatik olarak yalnızca metin gönderebilirim.\n\n"
    "↗️ <b>Mesaj İletme:</b> Bir kanal veya gruptaki mesajı doğrudan iletebilir; bağlantı ile "
    "veya yönlendirerek ayarlayabilirsiniz.\n\n"
    "📞 <b>Kişi Paylaşma:</b> Otomatik mesajlarınızla birlikte Telegram kişisi "
    "paylaşabilirsiniz.\n\n"
    "✉️ <b>DM Toplu Mesaj:</b> Tüm DM'lerinizdeki kişilere tek seferde mesaj "
    "gönderebilirsiniz.\n\n"
    "📁 <b>Arşiv Grup Kontrolü:</b> Arşivlenmiş gruplara mesaj göndermeyi açıp "
    "kapatabilirsiniz.\n\n"
    "⛔ <b>İstisna Sohbetler:</b> Belirlediğiniz sohbetlere mesaj gönderilmesini "
    "engelleyebilirsiniz.\n\n"
    "✉️ <b>Akıllı DM Yanıtlama:</b> Userbot hesabınıza <i>ilk kez</i> özelden yazan kişilere "
    "otomatik yanıt veririm.\n\n"
    "🎯 <b>Akıllı Yanıt Filtreleri:</b> Gruplarda belirli kelimeler yazıldığında userbot "
    "hesabınızın otomatik yanıt vermesini sağlarım.\n\n"
    "✨ <b>Biçimlendirme Desteği:</b> Mesajlarınızda kalın, <i>italik</i>, <code>kod</code> ve "
    "özel emojiler gibi tüm biçimlendirmeleri desteklerim."
)

# --------------------------------------------------------------------------- oturum açma

ASK_SESSION_NAME = (
    "Lütfen userbot için benzersiz bir oturum adı girin "
    "(boşluk veya özel karakter kullanmayın):\n\n" + CANCEL_HINT
)
INVALID_SESSION_NAME = (
    "❌ Geçersiz oturum adı. Sadece harf, rakam ve alt çizgi kullanın (2-32 karakter)."
)
SESSION_NAME_TAKEN = "❌ Bu oturum adı zaten kullanılıyor, başka bir ad girin."
ASK_PHONE = (
    "✅ Oturum adı: <b>{name}</b>\n\n"
    "Şimdi hesabın telefon numarasını uluslararası formatta girin:\n"
    "Örnek: <code>+905xxxxxxxxx</code>\n\n" + CANCEL_HINT
)
INVALID_PHONE = "❌ Geçersiz numara. Uluslararası formatta girin, örnek: <code>+905xxxxxxxxx</code>"
SENDING_CODE = "⏳ Telegram'dan kod isteniyor…"
ASK_CODE = (
    "Telegram'dan gelen {length} haneli kodu girin "
    "(rakamların arasına boşluk bırakabilirsiniz):\n\n"
    "📨 Kod <b>{where}</b> gönderildi.\n"
    "💡 Aşağıdaki tuş takımını da kullanabilirsiniz; bu yöntem kodun iptal edilme riskini "
    "ortadan kaldırır.\n\n" + CANCEL_HINT
)
CODE_DISPLAY = "\n\n🔢 Girilen: <code>{display}</code>"
CODE_INCOMPLETE = "Kod {length} haneli olmalı."
INVALID_CODE_FORMAT = "❌ Kodu {length} haneli olarak girin (örn: <code>1 2 3 4 5</code>)."
CHECKING_CODE = "⏳ Kod doğrulanıyor…"
ASK_PASSWORD = (
    "🔐 Bu hesapta iki adımlı doğrulama açık.\n\n"
    "Lütfen 2FA şifrenizi girin{hint}.\n"
    "<i>Güvenliğiniz için şifre mesajınız hemen silinecek.</i>\n\n" + CANCEL_HINT
)
CHECKING_PASSWORD = "⏳ Şifre doğrulanıyor…"
CODE_RESENT = "📨 Yeni kod gönderildi."
LOGIN_SUCCESS = (
    "✅ <b>Hesap başarıyla eklendi!</b>\n\n"
    "📛 Oturum: <b>{name}</b>\n👤 Hesap: {display}\n📱 Numara: <code>{phone}</code>"
)
LOGIN_EXPIRED = "⌛ Giriş oturumu zaman aşımına uğradı. /start ile yeniden başlayın."

CODE_SENT_TO = {
    "app": "Telegram uygulamanıza",
    "sms": "SMS olarak",
    "call": "sesli arama ile",
    "flash_call": "arama ile",
    "fragment": "Fragment üzerinden",
    "email": "e-posta adresinize",
}

# --------------------------------------------------------------------------- hesap paneli

PANEL_TITLE = "⚙️ <b>{name}</b> hesabını yönetiyorsunuz:"
PANEL_STATUS = "\n\n{status_line}\n📊 Son döngü: {last} · Sonraki: {next}"
STATUS_RUNNING = "🟢 Otomatik mesaj çalışıyor"
STATUS_STOPPED = "⚪ Otomatik mesaj kapalı"
STATUS_AUTH_ERROR = "⚠️ Oturum geçersiz: hesabı silip yeniden ekleyin"
STATUS_SPAM = "🚫 Spam kısıtı algılandı (PeerFlood)"
STATUS_DISCONNECTED = "🔴 Bağlı değil"

BTN_AUTO_STOP = "✅ Otomatik Mesajı Durdur"
BTN_AUTO_START = "❌ Otomatik Mesajı Başlat"
BTN_AUTO_SETTINGS = "🚀 Otomatik Mesaj Ayarları"
BTN_DM_ALL = "💌 DM'deki Herkese Mesaj At"
BTN_DM_REPLY_OFF = "✅ DM Oto-Cevabı Kapat"
BTN_DM_REPLY_ON = "❌ DM Oto-Cevabı Aç"
BTN_DM_SETTINGS = "💬 DM Oto-Cevap Ayarları"
BTN_FILTERS = "🎯 Otomatik Yanıt Filtreleri"
BTN_EXCEPTIONS = "🚫 İstisna Sohbetler"
BTN_OTHER = "🔧 Diğer Özellikler"
BTN_HEALTH = "🧪 Sistem Kontrolu"
BTN_DELETE = "🗑 Hesabı Sil"
BTN_BACK_TO_LIST = "🔙 Hesap Listesine Dön"
BTN_BACK = "🔙 Geri"
BTN_BACK_ARROW = "← Geri"
BTN_ADD_ACCOUNT = "➕ Yeni Hesap Ekle"
BTN_INFO = "ℹ️ Bu Bot Ne İşe Yarar?"
BTN_CANCEL = "❌ İptal"
BTN_SHARE_PHONE = "📱 Numaramı Paylaş"

AUTO_STARTED = "{name} hesabı için otomatik mesaj açıldı."
AUTO_STOPPED = "{name} hesabı için otomatik mesaj kapatıldı."
AUTO_NOT_CONFIGURED = "Önce 🚀 Otomatik Mesaj Ayarları'ndan mesaj belirleyin."
DM_REPLY_ENABLED = "{name} hesabı için DM oto-cevap açıldı."
DM_REPLY_DISABLED = "{name} hesabı için DM oto-cevap kapatıldı."
DM_REPLY_NOT_CONFIGURED = "Önce 💬 DM Oto-Cevap Ayarları'ndan cevap mesajı belirleyin."

DELETE_CONFIRM = (
    "⚠️ <b>{name}</b> hesabı silinsin mi?\n\n"
    "• Tüm ayarlar, filtreler ve istisnalar silinir.\n"
    "• Userbot oturumu Telegram tarafında da kapatılır.\n\n"
    "Bu işlem geri alınamaz."
)
BTN_DELETE_YES = "✅ Evet, Sil"
BTN_DELETE_NO = "❌ Vazgeç"
DELETED_TOAST = "🗑 {name} hesabı silindi."

HEALTH_CHECKING = "🧪 Sistem kontrol ediliyor…"
BTN_REFRESH = "🔄 Yenile"
BTN_RECONNECT = "🔌 Yeniden Bağlan"
RECONNECT_OK = "✅ Bağlantı yenilendi."
RECONNECT_FAILED = "❌ Bağlanılamadı: {error}"

# --------------------------------------------------------------------------- otomatik mesaj

AUTO_SUMMARY = (
    "🚀 <b>Otomatik Mesaj Ayarları</b> — {name}\n\n"
    "📝 İçerik: {content}\n"
    "⏱ 3'lü gruplar arası bekleme: <b>{delay}</b> sn (grup boyutu: {batch})\n"
    "🔁 Döngü bekleme süresi: <b>{cycle}</b> dk\n"
    "📁 Arşiv grupları: {archived} · 📞 Kişi: {contact}\n"
    "📊 Son döngü: {last} · Toplam gönderim: {total}"
)
CONTENT_NONE = "<i>ayarlanmamış</i>"
CONTENT_TEXT = "metin — <i>{preview}</i>"
CONTENT_PHOTO = "fotoğraf + metin — <i>{preview}</i>"
CONTENT_FORWARD = "forward — {link}{hidden}"

ASK_AUTO_MESSAGE = (
    "📝 <b>Otomatik Mesaj Ayarlama</b>\n\n"
    "Lütfen yeni otomatik mesaj metnini gönderiniz:\n\n"
    "<b>İsteğe Bağlı:</b>\n"
    "• Sadece metin göndererek metin mesajı\n"
    "• Fotoğraf + metin göndererek medyalı mesaj\n"
    "• Kanaldan forward ederek mesaj iletme\n"
    "• Mesaj linkini göndererek iletme\n\n" + CANCEL_HINT
)
UNSUPPORTED_CONTENT = (
    "❌ Bu içerik türü desteklenmiyor. Metin, fotoğraf (+ açıklama), kanaldan forward "
    "veya mesaj linki gönderin."
)
CHECKING_SOURCE = "⏳ Kaynak mesaj kontrol ediliyor…"
SOURCE_ERROR = "❌ {error}"
FORWARD_ACCEPTED = "✅ İletilecek mesaj: {link}"
ASK_DELAY = (
    "Lütfen 3'lü gruplar arasındaki bekleme süresi aralığını <b>saniye</b> cinsinden girin "
    "(örn: <code>0-5</code> veya <code>0 5</code>). Minimum sınır kaldırıldı, 0 saniye "
    "girebilirsiniz:"
)
INVALID_DELAY = "❌ Geçersiz aralık. Örnek: <code>0-5</code>, <code>0 5</code> veya <code>3</code>."
ASK_CYCLE = (
    "Lütfen tüm gruplara mesaj atıldıktan sonra beklenecek süreyi <b>dakika</b> cinsinden "
    "girin (örn: 60):"
)
INVALID_CYCLE = "❌ {min} ile {max} arasında bir dakika değeri girin."
AUTO_SAVED = "✅ <b>Otomatik mesaj ayarlandı.</b>"
SPAM_WARNING = (
    "\n\n⚠️ {minutes} dakikadan kısa döngüler hesabın spam kısıtına alınma riskini artırır."
)
RESTARTED_NOTE = "\n🔁 Çalışan döngü yeni ayarlarla yeniden başlatıldı."

# --------------------------------------------------------------------------- diğer özellikler

OTHER_TITLE = (
    "🔧 <b>Diğer Özellikler</b> — {name}\n\n"
    "📁 <b>Arşiv Grupları:</b> arşivlenmiş gruplara da otomatik mesaj gönderilsin mi?\n"
    "🖼 <b>Medya → Metin:</b> fotoğraf gönderilemeyen gruplara sadece metin gönderilsin mi?\n"
    "↗️ <b>Forward Başlığı:</b> iletilen mesajda kaynak kanal görünsün mü?\n"
    "📞 <b>Kişi Paylaşma:</b> otomatik mesajın ardından bir kişi kartı gönderilir.\n"
    "🔢 <b>Grup Boyutu:</b> kaç grup birlikte gönderildikten sonra bekleneceği (varsayılan 3)."
)
BTN_ARCHIVE = "📁 Arşiv Grupları: {state}"
BTN_FALLBACK = "🖼 Medya → Metin: {state}"
BTN_FORWARD_HEADER = "↗️ Forward Başlığı: {state}"
BTN_CONTACT = "📞 Kişi Paylaşma: {state}"
BTN_BATCH = "🔢 Grup Boyutu: {size}"
BTN_PREVIEW = "👁 Mesaj Önizleme"
BTN_EXPORT = "💾 .session Dışa Aktar"
STATE_ON = "Açık"
STATE_OFF = "Kapalı"
STATE_VISIBLE = "Görünür"
STATE_HIDDEN = "Gizli"

ASK_CONTACT = (
    "📞 Otomatik mesajla paylaşılacak kişiyi gönderin:\n\n"
    "• 📎 → <b>Kişi</b> menüsünden bir kişi paylaşın, veya\n"
    "• <code>+905xxxxxxxxx Ad Soyad</code> biçiminde yazın.\n\n" + CANCEL_HINT
)
INVALID_CONTACT = "❌ Geçersiz kişi. Örnek: <code>+905551234567 Ahmet Yılmaz</code>"
CONTACT_SAVED = "✅ Kişi kaydedildi: <b>{name}</b> (<code>{phone}</code>)"
CONTACT_REMOVED = "Kişi paylaşma kapatıldı."
BTN_CONTACT_SET = "✏️ Kişiyi Ayarla"
BTN_CONTACT_REMOVE = "🗑 Kişiyi Kaldır"
CONTACT_MENU = "📞 <b>Kişi Paylaşma</b>\n\nMevcut kişi: {current}"
ASK_BATCH = "🔢 Kaç grupta bir bekleme yapılsın? (1-{max}, varsayılan 3)\n\n" + CANCEL_HINT
INVALID_BATCH = "❌ 1 ile {max} arasında bir sayı girin."
BATCH_SAVED = "✅ Grup boyutu: <b>{size}</b>"
PREVIEW_HEADER = "👁 <b>Önizleme</b> — gruplara bu şekilde gönderilecek:"
PREVIEW_FORWARD = "↗️ Bu mesaj {link} kaynağından {mode} iletilecek."
PREVIEW_NOT_CONFIGURED = "Henüz otomatik mesaj ayarlanmamış."
EXPORT_WARNING = (
    "💾 <b>{name}</b> oturum dosyası.\n\n"
    "⚠️ Bu dosya hesabınıza <b>tam erişim</b> sağlar. Kimseyle paylaşmayın ve güvenli bir yerde "
    "saklayın."
)
EXPORT_FAILED = "❌ Oturum dosyası oluşturulamadı: {error}"

# --------------------------------------------------------------------------- DM

DM_SCANNING = "⏳ DM listesi taranıyor…"
ASK_BROADCAST = (
    "💌 <b>DM'deki Herkese Mesaj</b>\n\n"
    "DM listenizde <b>{count}</b> kişi bulundu (botlar ve silinmiş hesaplar hariç).\n\n"
    "Göndermek istediğiniz mesajı yazın (metin veya fotoğraf + metin):\n\n" + CANCEL_HINT
)
BROADCAST_EMPTY = "DM listenizde mesaj gönderilecek kimse bulunamadı."
BROADCAST_CONFIRM = "Yukarıdaki mesaj <b>{count}</b> kişiye gönderilsin mi?"
BTN_BROADCAST_GO = "✅ Gönder"
BTN_BROADCAST_STOP = "⏹ Durdur"
BROADCAST_PROGRESS = (
    "📤 <b>DM toplu gönderim</b> — {name}\n\n"
    "İlerleme: {done}/{total}\n✅ Başarılı: {sent} · ❌ Başarısız: {failed}"
)
BROADCAST_DONE = (
    "✅ <b>DM toplu gönderim tamamlandı</b> — {name}\n\n"
    "Toplam: {total}\n✅ Başarılı: {sent} · ❌ Başarısız: {failed}"
)
BROADCAST_CANCELLED = "⏹ <b>Gönderim durduruldu</b> — {name}\n\n✅ {sent} · ❌ {failed} / {total}"
BROADCAST_ABORTED = (
    "🚫 <b>Gönderim yarıda kesildi</b> — {name}\n\n{reason}\n\n✅ {sent} · ❌ {failed} / {total}"
)
BROADCAST_RUNNING = "Bu hesap için zaten bir toplu gönderim çalışıyor."

DM_SETTINGS = (
    "💬 <b>DM Oto-Cevap Ayarları</b> — {name}\n\n"
    "Durum: {state}\n"
    "Cevap modu: {mode}\n"
    "WhatsApp butonu: {whatsapp}\n"
    "Kişilerime de cevap ver: {contacts}\n"
    "Şimdiye kadar cevaplanan: {replied} kişi\n\n"
    "Cevap mesajı:\n{preview}"
)
DM_MODE_NAMES = {"first": "🆕 Sadece ilk mesaja", "always": "🔁 Her mesaja"}
DM_MODE_ALWAYS_DETAIL = " (aynı kişiye en fazla {minutes} dk'da bir)"
BTN_DM_SET_MESSAGE = "✏️ Cevap Mesajını Ayarla"
BTN_DM_CONTACTS = "👥 Kişilerime de Cevap Ver: {state}"
BTN_DM_MODE = "Cevap: {mode}"
BTN_DM_COOLDOWN = "⏱ Aynı Kişiye Tekrar: {minutes} dk"
BTN_DM_WHATSAPP = "💚 WhatsApp Butonu: {state}"
BTN_DM_PREVIEW = "👁 Önizleme"
DM_MODE_CHANGED = "Cevap modu: {mode}"
ASK_DM_REPLY = (
    "✏️ Hesaba özelden yazan kişilere gönderilecek mesajı yazın "
    "(metin veya fotoğraf + metin):\n\n" + CANCEL_HINT
)
DM_PREVIEW_HEADER = "👁 <b>Önizleme</b> — özelden yazan kişi bunu görecek:"

WA_MENU = (
    "💚 <b>WhatsApp Butonu</b> — {name}\n\n"
    "Oto-cevap mesajının altına, basınca doğrudan WhatsApp sohbetini açan bir buton eklenir.\n\n"
    "📱 Numara: {phone}\n"
    "🔤 Buton yazısı: {button}\n"
    "✉️ Hazır mesaj: {message}\n\n"
    "{status}"
)
WA_STATUS_OK = (
    "✅ Buton aktif. Telegram'da yalnızca botlar buton gönderebildiği için cevap "
    "@{bot} üzerinden gönderilir; mesajda küçük bir “via @{bot}” etiketi görünür."
)
WA_STATUS_NO_INLINE = (
    "⚠️ Butonun görünmesi için @BotFather → /setinline → @{bot} ile <b>inline modu açın</b>. "
    "Kapalıyken WhatsApp linki mesajın sonuna tıklanabilir yazı olarak eklenir."
)
WA_STATUS_OFF = "Numara ayarlanınca buton otomatik eklenir."
BTN_WA_PHONE = "📱 Numarayı Ayarla"
BTN_WA_BUTTON = "🔤 Buton Yazısı"
BTN_WA_MESSAGE = "✉️ Hazır Mesaj"
BTN_WA_REMOVE = "🗑 Butonu Kaldır"
ASK_WA_PHONE = (
    "📱 WhatsApp numarasını uluslararası formatta girin (örn: <code>+905551234567</code>):\n\n"
    + CANCEL_HINT
)
ASK_WA_BUTTON = (
    "🔤 Buton yazısını girin (en fazla {max} karakter).\nVarsayılan: <b>{default}</b>\n\n"
    + CANCEL_HINT
)
ASK_WA_MESSAGE = (
    "✉️ WhatsApp açıldığında yazma kutusunda hazır duracak mesajı yazın "
    "(en fazla {max} karakter). Kaldırmak için <code>-</code> gönderin.\n\n" + CANCEL_HINT
)
INVALID_WA_BUTTON = "❌ Buton yazısı 1-{max} karakter olmalı."
INVALID_WA_MESSAGE = "❌ Hazır mesaj en fazla {max} karakter olabilir."
WA_SAVED = "✅ WhatsApp butonu güncellendi."
WA_REMOVED = "WhatsApp butonu kaldırıldı."
DM_REPLY_SAVED = "✅ DM oto-cevap mesajı kaydedildi."

# --------------------------------------------------------------------------- filtreler

FILTERS_TITLE = (
    "🎯 <b>Otomatik Yanıt Filtreleri</b> — {name}\n\n"
    "Gruplarda bu kelimeler yazıldığında userbot mesaja yanıt verir.\n"
    "Aynı grupta aynı filtre en fazla {cooldown} sn'de bir çalışır.\n\n{items}"
)
FILTERS_EMPTY = "<i>Henüz filtre yok.</i>"
BTN_FILTER_ADD = "➕ Filtre Ekle"
ASK_FILTER_KEYWORDS = (
    "🎯 Tetikleyici kelimeyi girin.\n"
    "Birden fazla kelime için virgül kullanın: <code>fiyat, ücret, kaç tl</code>\n\n" + CANCEL_HINT
)
INVALID_KEYWORDS = "❌ En az bir kelime girin (her biri en fazla 64 karakter)."
ASK_FILTER_REPLY = "✏️ Bu kelimeler yazıldığında gönderilecek yanıtı yazın:\n\n" + CANCEL_HINT
FILTER_SAVED = "✅ Filtre eklendi."
FILTER_LIMIT = "⚠️ Bir hesap için en fazla {limit} filtre eklenebilir."
FILTER_DETAIL = (
    "🎯 <b>Filtre #{id}</b>\n\n"
    "🔑 Kelimeler: {keywords}\n"
    "🔍 Eşleşme: {match}\n"
    "⏱ Bekleme: {cooldown} sn\n"
    "Durum: {state}\n\n"
    "💬 Yanıt:\n{reply}"
)
MATCH_NAMES = {"contains": "İçinde geçerse", "exact": "Tam eşleşme", "word": "Kelime olarak"}
BTN_FILTER_MATCH = "🔍 Eşleşme: {match}"
BTN_FILTER_COOLDOWN = "⏱ Bekleme: {cooldown} sn"
BTN_FILTER_PAUSE = "⏸ Pasif Yap"
BTN_FILTER_RESUME = "▶️ Aktif Yap"
BTN_FILTER_DELETE = "🗑 Sil"
FILTER_DELETED = "Filtre silindi."
FILTER_NOT_FOUND = "Filtre bulunamadı."

# --------------------------------------------------------------------------- istisnalar

EXCEPTIONS_TITLE = (
    "🚫 <b>İstisna Sohbetler</b> — {name}\n\n"
    "Bu sohbetlere otomatik mesaj gönderilmez ve yanıt filtreleri çalışmaz.\n"
    "Kaldırmak için sohbete dokunun.\n\n{summary}"
)
EXCEPTIONS_EMPTY = "<i>Henüz istisna yok.</i>"
EXCEPTIONS_COUNT = "Toplam: <b>{count}</b> sohbet"
BTN_EXC_PICK = "➕ Gruplardan Seç"
BTN_EXC_MANUAL = "✍️ Manuel Ekle"
EXC_PICKER_TITLE = (
    "📋 <b>Gruplarınız</b> ({count}) — sayfa {page}/{pages}\n\n"
    "✅ işaretli gruplar istisnadır. Değiştirmek için dokunun."
)
EXC_LOADING = "⏳ Gruplar yükleniyor…"
EXC_NO_GROUPS = "Bu hesapta hiç grup bulunamadı."
ASK_EXC_MANUAL = (
    "✍️ İstisna eklemek istediğiniz sohbeti gönderin:\n\n"
    "• <code>@kullaniciadi</code> veya <code>t.me/…</code> linki\n"
    "• Sohbet kimliği (örn: <code>-1001234567890</code>)\n"
    "• Gruptan/kanaldan bir mesajı buraya forward edin\n\n" + CANCEL_HINT
)
EXC_RESOLVE_FAILED = "❌ Sohbet bulunamadı: {error}"
EXC_ADDED = "✅ İstisnaya eklendi: <b>{title}</b>"
EXC_ALREADY = "Bu sohbet zaten istisna listesinde."
EXC_REMOVED = "İstisnadan çıkarıldı."

# --------------------------------------------------------------------------- sistem kontrolü

HEALTH_REPORT = (
    "🧪 <b>Sistem Kontrolu</b> — {name}\n\n"
    "🔌 Bağlantı: {connected}\n"
    "🔑 Oturum: {authorized}\n"
    "👤 Hesap: {me}\n"
    "📶 Ping: {ping}\n"
    "⚙️ Hesap durumu: {status}\n\n"
    "🚀 Otomatik mesaj: {worker}\n"
    "🕐 Son döngü: {last_cycle}\n"
    "📊 Son sonuç: ✅ {sent} · ❌ {failed} · ⏭ {skipped} / {targets} grup\n"
    "⏭ Sonraki döngü: {next_cycle}\n"
    "⏳ Flood beklemesi: {flood}\n\n"
    "👥 Grup sayısı: {groups} · 🚫 İstisna: {exceptions}\n"
    "🎯 Aktif filtre: {filters} · 💬 DM oto-cevap: {dm}\n"
    "📤 DM toplu gönderim: {broadcast}"
)
YES = "✅"
NO = "❌"

# --------------------------------------------------------------------------- bildirimler

NOTIFY_NOT_CONFIGURED = "⚠️ <b>{name}</b>: otomatik mesaj ayarlanmadığı için döngü durduruldu."
NOTIFY_SOURCE_UNAVAILABLE = (
    "⚠️ <b>{name}</b>: {reason}\nOtomatik mesaj durduruldu, ayarları kontrol edin."
)
NOTIFY_SPAM_LIMITED = (
    "🚫 <b>{name}</b> hesabı Telegram tarafından spam kısıtına alındı (PeerFlood).\n"
    "Otomatik mesaj durduruldu. Durumu @SpamBot'a yazarak kontrol edebilirsiniz."
)
NOTIFY_SESSION_DEAD = (
    "⚠️ <b>{name}</b> hesabının oturumu sonlandırılmış veya geçersiz.\n"
    "Hesabı silip yeniden eklemeniz gerekiyor."
)
NOTIFY_LONG_FLOOD = (
    "⏳ <b>{name}</b>: Telegram {duration} bekleme (FloodWait) uyguladı. "
    "Gönderim bu süre sonunda otomatik devam edecek."
)
NOTIFY_CYCLE_ERRORS = (
    "⚠️ <b>{name}</b>: otomatik mesaj döngüsü art arda {count} kez hata verdi "
    "(<code>{error}</code>). Tekrar denenecek."
)
NOTIFY_NEW_USER = (
    "👤 <b>Yeni kullanıcı erişim istiyor</b>\n\n"
    "Ad: {name}\nKullanıcı adı: {username}\nID: <code>{user_id}</code>"
)
BTN_ALLOW = "✅ İzin Ver"
BTN_BAN = "⛔ Yasakla"

# --------------------------------------------------------------------------- admin

ADMIN_USAGE = (
    "🛠 <b>Admin komutları</b>\n\n"
    "/izin &lt;id&gt; — kullanıcıya erişim ver\n"
    "/kaldir &lt;id&gt; — erişimi kaldır\n"
    "/yasakla &lt;id&gt; — kullanıcıyı yasakla (hesapları durdurulur)\n"
    "/kullanicilar — kullanıcı listesi\n"
    "/durum — sistem özeti"
)
ADMIN_USER_ALLOWED = "✅ <code>{user_id}</code> kullanıcısına erişim verildi."
ADMIN_USER_REVOKED = "✅ <code>{user_id}</code> kullanıcısının erişimi kaldırıldı."
ADMIN_USER_BANNED = "⛔ <code>{user_id}</code> yasaklandı, hesapları durduruldu."
ADMIN_USER_NOT_FOUND = "Kullanıcı bulunamadı (önce botu /start ile başlatmış olmalı)."
ADMIN_CANT_TARGET_ADMIN = "Admin kullanıcılar üzerinde bu işlem yapılamaz."
ADMIN_BAD_ID = "Kullanım: <code>/{command} 123456789</code>"
USER_GRANTED = "✅ Bota erişiminiz açıldı. Başlamak için /start yazın."
ADMIN_STATUS = (
    "📊 <b>Sistem Özeti</b>\n\n"
    "👥 Kullanıcı: {users}\n📱 Hesap: {accounts}\n🔌 Bağlı userbot: {connected}\n"
    "🚀 Çalışan döngü: {workers}\n📤 Çalışan DM gönderimi: {broadcasts}"
)


def html(text: str | None) -> str:
    return escape(text or "", quote=False)


def on_off(value: bool) -> str:
    return STATE_ON if value else STATE_OFF
