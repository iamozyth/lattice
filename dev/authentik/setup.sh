#!/bin/sh
# Generates dev/authentik/.env with random secrets (once).
cd "$(dirname "$0")"
[ -f .env ] && { echo ".env exists"; exit 0; }
umask 077
cat > .env <<ENV
PG_PASS=$(openssl rand -hex 24)
AUTHENTIK_SECRET_KEY=$(openssl rand -hex 50)
AUTHENTIK_BOOTSTRAP_PASSWORD=$(openssl rand -hex 12)
AUTHENTIK_BOOTSTRAP_EMAIL=akadmin@example.com
LATTICE_CLIENT_SECRET=$(openssl rand -hex 32)
LATTICE_TEST_PASSWORD=$(openssl rand -hex 12)
ENV
echo "Wrote dev/authentik/.env"
