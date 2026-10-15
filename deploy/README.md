# Deployment Guide

Everything needed to run the full stack (FastAPI ML service + Spring Boot
orchestrator + MySQL + Redis) on a single EC2 instance via Docker Compose.

> **Honesty note:** these scripts and this production compose file are
> provided ready-to-use but were **not executed against a live AWS account**
> as part of this project's verification. Verified locally: `docker compose
> up` (dev file) is the workflow used during development; the prod file
> differs only in port exposure, env-var requirements and restart policy.
> Adjust/verify on your own instance before relying on them.

## Files

| File | Purpose |
|---|---|
| `ec2-setup.sh` | One-time provisioning of a fresh Amazon Linux 2023 / Ubuntu instance (Docker, git, app dir) |
| `docker-compose.prod.yml` | Production stack: MySQL & Redis **not** published on any host port; only backend `:8080` is public |
| `../docker-compose.yml` | Development stack (all services port-mapped for local debugging) |
| `../.env.example` | Template for all secrets/config — copy to `.env`, never commit `.env` |

## Steps (summary)

```bash
# 1. Provision the instance
scp -i key.pem deploy/ec2-setup.sh ec2-user@<ip>:~/
ssh -i key.pem ec2-user@<ip>
bash ec2-setup.sh

# 2. Get the code and configure secrets
git clone <repo-url> ~/cricket-model && cd ~/cricket-model
cp .env.example .env
nano .env        # real MYSQL_PASSWORD / MYSQL_ROOT_PASSWORD values

# 3. Build and start
docker compose -f deploy/docker-compose.prod.yml up -d --build

# 4. Verify
curl -s http://localhost:8080/actuator/health        # {"status":"UP"}
curl -s http://localhost:8080/api/matches/live        # []
docker compose -f deploy/docker-compose.prod.yml ps   # all services healthy
```

## Security group (inbound)

| Port | Source | Why |
|---|---|---|
| 22 | Your IP only | SSH |
| 8080 | Your IP only (or 443 behind a proxy) | Spring Boot API + `/ws` WebSocket |

**Never open 3306 (MySQL) or 6379 (Redis)** — in the prod compose file they
aren't even published on the host, so they're unreachable regardless of the
security group.

## Secrets policy

- All passwords/URLs come from environment variables (`.env`, git-ignored).
- Compose uses `${VAR:?message}` so the stack **refuses to start** with a
  missing required secret instead of silently defaulting.
- No credentials appear in any committed file (verified by grep in the
  final checklist).

## Data durability

- `mysql-data` and `redis-data` named volumes survive `docker compose down`
  (add `-v` to wipe them deliberately).
- Model artifacts are baked into the FastAPI image — no runtime downloads.

## Updates

```bash
cd ~/cricket-model && git pull
docker compose -f deploy/docker-compose.prod.yml up -d --build
```
