#!/usr/bin/env bash
# One-shot operator script: create the `selva_migrator` DB role, store its URL
# as a selva-secrets key, apply Alembic 0041 to prod, and verify.
#
# WHY THIS EXISTS (2026-07-19): `alembic upgrade head` as the app role
# (`autoswarm`) fails with `must be owner of table tenant_configs` — 20 of
# Selva's ~39 tables (the audit/consent/security set: audit_logs,
# consent_ledger, secret_audit_log, tenant_configs, tenant_identities, …) are
# deliberately owned by `enclii` so the app role has DML but not DDL on them.
# Migrations therefore need a dedicated role that is a member of BOTH owning
# roles. PR #238's migrate-job must use this role's URL (key
# `migration-database-url`), not the app's `database-url`.
#
# DESIGN:
#  - selva_migrator LOGIN, member of enclii + autoswarm (INHERIT): ownership
#    checks pass for members of the owning role, so it can ALTER all tables
#    and update alembic_version (autoswarm-owned).
#  - ALTER DEFAULT PRIVILEGES: tables/sequences created by future migrations
#    automatically get DML granted to the app role — no per-migration GRANT
#    boilerplate.
#  - The migration URL points DIRECTLY at postgres (:5432), not pgbouncer
#    (:6432): pgbouncer auth is a static userlist (auth_type=plain +
#    auth_file) so new roles won't authenticate through it, and DDL shouldn't
#    run through a transaction pooler anyway.
#  - Secrets hygiene: the password is generated on the node, flows via stdin
#    and a patch-file (shredded after), and is never echoed or passed as a
#    command-line argument.
#
# RUN FROM: your workstation. Uses the mandated `ssh ssh.madfam.io` tunnel.
# IDEMPOTENT: CREATE ROLE may NOTICE-fail if the role exists (harmless);
# ALTER/GRANT/patch/upgrade are all re-run-safe. Alembic 0041 is guarded.
set -euo pipefail

timeout 300 ssh -o ConnectTimeout=30 -o BatchMode=yes ssh.madfam.io '
set -e
PGPOD=$(sudo /usr/local/bin/k3s kubectl -n data get pods -l app=postgres -o jsonpath="{.items[0].metadata.name}")
KPG="sudo /usr/local/bin/k3s kubectl -n data exec -i $PGPOD -c postgres --"
KS="sudo /usr/local/bin/k3s kubectl -n selva"

echo "== [1/6] create selva_migrator (password via stdin, never in args) =="
PW=$(openssl rand -hex 24)
$KPG psql -U postgres -d autoswarm -f - <<EOF
CREATE ROLE selva_migrator;
ALTER ROLE selva_migrator LOGIN PASSWORD '"'"'$PW'"'"';
GRANT enclii TO selva_migrator;
GRANT autoswarm TO selva_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE selva_migrator IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO autoswarm;
ALTER DEFAULT PRIVILEGES FOR ROLE selva_migrator IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO autoswarm;
EOF

echo "== [2/6] store URL as selva-secrets/migration-database-url (patch-file) =="
PATCHFILE=$(mktemp)
printf "{\"stringData\":{\"migration-database-url\":\"postgresql+asyncpg://selva_migrator:%s@postgres.data.svc.cluster.local:5432/autoswarm\"}}" "$PW" > "$PATCHFILE"
$KS patch secret selva-secrets --patch-file "$PATCHFILE" >/dev/null && echo "secret patched"
rm -f "$PATCHFILE"; unset PW

echo "== [3/6] resolve running nexus-api pod =="
POD=$($KS get pods -l app.kubernetes.io/name=nexus-api --field-selector=status.phase=Running -o jsonpath="{.items[0].metadata.name}")
echo "pod: $POD"

echo "== [4/6] connectivity test as selva_migrator (direct :5432) =="
MURL=$($KS get secret selva-secrets -o jsonpath="{.data.migration-database-url}" | base64 -d)
printf "%s" "$MURL" | $KS exec -i $POD -c nexus-api -- sh -lc "read -r DATABASE_URL; export DATABASE_URL; cd /app/apps/nexus-api && /app/.venv/bin/python - <<PYEOF
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def m():
    e = create_async_engine(os.environ[\"DATABASE_URL\"])
    async with e.connect() as c:
        print(\"connected as:\", (await c.execute(text(\"select current_user\"))).scalar())
    await e.dispose()
asyncio.run(m())
PYEOF"

echo "== [5/6] alembic upgrade head as selva_migrator =="
printf "%s" "$MURL" | $KS exec -i $POD -c nexus-api -- sh -lc "read -r DATABASE_URL; export DATABASE_URL; cd /app/apps/nexus-api && /app/.venv/bin/alembic upgrade head"
unset MURL

echo "== [6/6] verify: revision + column + app-role readability =="
$KS exec $POD -c nexus-api -- sh -lc "cd /app/apps/nexus-api && /app/.venv/bin/alembic current 2>/dev/null | tail -1"
$KS exec $POD -c nexus-api -- sh -lc "cd /app/apps/nexus-api && /app/.venv/bin/python - <<PYEOF
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def m():
    e = create_async_engine(os.environ[\"DATABASE_URL\"])
    async with e.connect() as c:
        col = (await c.execute(text(\"select data_type, is_nullable from information_schema.columns where table_name='"'"'tenant_configs'"'"' and column_name='"'"'office_size'"'"'\"))).first()
        print(\"office_size column:\", col)
        cnt = (await c.execute(text(\"select count(*) from tenant_configs\"))).scalar()
        print(\"tenant_configs readable as app role, rows:\", cnt)
    await e.dispose()
asyncio.run(m())
PYEOF"
'
echo "DONE — prod at 0041, migration identity ready for PR #238."
