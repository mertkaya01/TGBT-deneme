#!/usr/bin/env bash
# Güncelleme: önce yedek alır, sonra yeni kodu çekip botu yeniden başlatır.
# Veritabanı değişiklikleri (migration) bot açılırken otomatik uygulanır.
#
# Kullanım:  bash scripts/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."

bash scripts/backup.sh
git pull --ff-only
docker compose up -d --build
docker compose ps
echo "Güncelleme tamam. Loglar: docker compose logs -f bot"
