#!/usr/bin/env bash
# One-time setup on a fresh Amazon Linux 2023 EC2 instance.
#   curl -s https://raw.githubusercontent.com/collaborate-bhavishya/zuno-content-pipeline/main/deploy/ec2-setup.sh | bash
# or: bash deploy/ec2-setup.sh
set -euo pipefail

# 2 GB swap so a 1 GB t3.micro can build the image / run without OOM.
if [ ! -f /swapfile ]; then
  echo "==> Creating 2GB swap"
  sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Installing Docker + git"
sudo dnf install -y docker git >/dev/null
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

echo "==> Cloning repo (if not present)"
cd ~
[ -d zuno-content-pipeline ] || git clone https://github.com/collaborate-bhavishya/zuno-content-pipeline.git

echo
echo "✅ Setup complete."
echo "   Log out and back in (so the docker group applies), then:"
echo "   1) cd ~/zuno-content-pipeline/backend && create prod.env (see deploy/README.md)"
echo "   2) bash ~/zuno-content-pipeline/deploy/run-backend.sh"
