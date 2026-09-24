#!/usr/bin/env bash
# Yedek alır: veritabanı + .env (oturum şifreleme anahtarı dahil) + medya dosyaları.
# Yedekler tek bir .tar.gz dosyasında, yalnızca sahibinin okuyabileceği izinlerle tutulur.
#
# Kullanım:  bash scripts/backup.sh
# Ayarlar:   BACKUP_DIR (varsayılan ~/tgbt-backups), KEEP_DAYS (varsayılan 14)
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-$HOME/tgbt-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="tgbt-${STAMP}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

umask 077
mkdir -p "${BACKUP_DIR}" "${WORK}/${NAME}"

docker compose exec -T postgres pg_dump -U tgbt -d tgbt --clean --if-exists \
    | gzip > "${WORK}/${NAME}/db.sql.gz"
cp .env "${WORK}/${NAME}/env"
if [[ -d data/media ]]; then
    tar -czf "${WORK}/${NAME}/media.tar.gz" -C data media
fi

tar -czf "${BACKUP_DIR}/${NAME}.tar.gz" -C "${WORK}" "${NAME}"
find "${BACKUP_DIR}" -name 'tgbt-*.tar.gz' -mtime +"${KEEP_DAYS}" -delete

echo "Yedek alındı: ${BACKUP_DIR}/${NAME}.tar.gz"
