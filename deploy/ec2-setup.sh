#!/usr/bin/env bash
# ============================================================
# One-time setup for a fresh Amazon Linux 2023 / Ubuntu EC2 instance.
# Run as the default user (this script escalates with sudo where needed).
#
#   scp -i your-key.pem deploy/ec2-setup.sh ec2-user@<ip>:~/
#   ssh -i your-key.pem ec2-user@<ip>
#   bash ec2-setup.sh
#
# After this script: clone the repo, create .env from .env.example,
# then run the deployment (see deploy/README.md).
#
# NOTE: this script is provided as-is and has NOT been executed against a
# live AWS account as part of this project's verification. Review before use.
# ============================================================
set -euo pipefail

echo "==> Installing Docker..."
if ! command -v docker >/dev/null 2>&1; then
  if grep -qiE "amzn|amazon" /etc/os-release; then
    sudo dnf install -y docker
  else
    sudo apt-get update -y
    sudo apt-get install -y docker.io docker-compose-v2 || sudo apt-get install -y docker.io
  fi
  sudo systemctl enable --now docker
else
  echo "    Docker already installed: $(docker --version)"
fi

echo "==> Adding current user to the docker group..."
sudo usermod -aG docker "$USER"
echo "    (log out/in for this to take effect, or use 'newgrp docker')"

echo "==> Installing git..."
command -v git >/dev/null 2>&1 || { sudo dnf install -y git 2>/dev/null || sudo apt-get install -y git; }

echo "==> Creating app directory..."
APP_DIR="$HOME/cricket-model"
mkdir -p "$APP_DIR"

cat <<'EOF'

============================================================
Next steps
------------------------------------------------------------
1. Log out and back in (or run: newgrp docker)

2. Clone the repository into ~/cricket-model:
     git clone <your-repo-url> ~/cricket-model
     cd ~/cricket-model

3. Create your secrets file (NEVER commit it):
     cp .env.example .env
     nano .env            # set strong MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD

4. Build and start:
     docker compose -f deploy/docker-compose.prod.yml up -d --build

5. Verify:
     curl -s http://localhost:8080/actuator/health
     curl -s http://localhost:8080/api/matches/live

EC2 Security Group (inbound rules) - only these:
     TCP 22   from your IP        (SSH)
     TCP 8080 from your IP        (API - or 443 behind a proxy)
     (optionally 80/443 if you put nginx/Caddy in front)

MySQL (3306) and Redis (6379) must NOT be open to the world.
============================================================
EOF
