#!/usr/bin/env bash
# Temiz bir Ubuntu (22.04 / 24.04) sunucusunu TGBT için hazırlar:
# paket güncellemeleri, otomatik güvenlik güncellemeleri, Docker, güvenlik duvarı ve swap.
#
# Kullanım (sunucuda):  sudo bash scripts/vps-setup.sh
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Bu betiği root olarak çalıştırın: sudo bash scripts/vps-setup.sh" >&2
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive

echo "==> Paketler güncelleniyor"
apt-get update -y
apt-get upgrade -y
apt-get install -y ca-certificates curl git ufw unattended-upgrades

echo "==> Otomatik güvenlik güncellemeleri açılıyor"
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Docker kuruluyor"
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    usermod -aG docker "${SUDO_USER}"
    echo "    ${SUDO_USER} docker grubuna eklendi (etkili olması için çıkış yapıp tekrar bağlanın)."
fi

echo "==> Güvenlik duvarı: yalnızca SSH açık"
# Bot dışarıya port açmaz; PostgreSQL ve Redis yalnızca Docker'ın iç ağında çalışır.
ufw allow OpenSSH
ufw --force enable

echo "==> Swap (RAM dolarsa botun çökmemesi için 2 GB)"
if ! swapon --show | grep -q .; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
else
    echo "    Swap zaten var, atlandı."
fi

echo
echo "Sunucu hazır. Sonraki adım: docs/VPS_KURULUM.md → '4) Botu kur'."
