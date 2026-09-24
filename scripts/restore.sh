#!/usr/bin/env bash
# Yedekten geri yükler: veritabanı, .env ve medya dosyaları.
#
# Kullanım:  bash scripts/restore.sh ~/tgbt-backups/tgbt-20260101-040000.tar.gz
#
# Yeni bir sunucuya taşırken bu betiği, o sunucuda ilk kez `docker compose up` çalıştırmadan
# ÖNCE kullanın; böylece PostgreSQL yedekteki şifreyle (POSTGRES_PASSWORD) oluşturulur.
set -euo pipefail
cd "$(dirname "$0")/.."

ARCHIVE="${1:?Kullanım: bash scripts/restore.sh <yedek.tar.gz>}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

tar -xzf "${ARCHIVE}" -C "${WORK}"
SRC="$(find "${WORK}" -mindepth 1 -maxdepth 1 -type d -name 'tgbt-*' | head -n 1)"
if [[ -z "${SRC}" || ! -f "${SRC}/db.sql.gz" || ! -f "${SRC}/env" ]]; then
    echo "Geçersiz yedek dosyası: ${ARCHIVE}" >&2
    exit 1
fi

read -r -p "Mevcut veritabanı ve .env, yedektekiyle DEĞİŞTİRİLECEK. Devam etmek için 'evet' yazın: " answer
if [[ "${answer}" != "evet" ]]; then
    echo "İptal edildi."
    exit 1
fi

docker compose stop bot || true
install -m 600 "${SRC}/env" .env
docker compose up -d postgres redis

echo "PostgreSQL bekleniyor…"
for _ in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U tgbt -d tgbt >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

gunzip -c "${SRC}/db.sql.gz" \
    | docker compose exec -T postgres psql -U tgbt -d tgbt -v ON_ERROR_STOP=1 -q >/dev/null
mkdir -p data
if [[ -f "${SRC}/media.tar.gz" ]]; then
    tar -xzf "${SRC}/media.tar.gz" -C data
fi
if [[ ${EUID} -eq 0 ]]; then
    chown -R 1000:1000 data  # konteyner içindeki bot kullanıcısı (uid 1000) yazabilsin
fi

docker compose up -d --build
echo "Geri yükleme tamam. Loglar: docker compose logs -f bot"
