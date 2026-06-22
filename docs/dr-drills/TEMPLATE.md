# DR Drill Evidence Template

Copy to `docs/dr-drills/YYYYMMDDTHHMMSSZ.md` after executing:

```bash
DR_DRILL_EXECUTE=yes \
DR_SOURCE_ENV=prod \
DR_TARGET_ENV=staging-restore-sandbox \
DR_BACKUP_DATABASE_URL=postgresql://... \
DR_RESTORE_DATABASE_URL=postgresql://... \
  ./scripts/run-db-restore-drill.sh --execute
```

Replace placeholder values before commit. Never include connection strings or dumps.

| Field | Value |
|-------|-------|
| Status | PASS |
| Executed at (UTC) | YYYY-MM-DDTHH:MM:SSZ |
| Operator | name |
| Source environment | prod |
| Restore target | staging-restore-sandbox |
| Backup file | backups/drills/selva_YYYYMMDD_HHMMSS.dump |
| Measured RTO seconds | 123 |
| Backup age at restore seconds | 456 |
| Post-restore health URL | https://staging-api.selva.town/api/v1/health/ready |
| Post-restore health result | 200 ready |
| Notes | optional |
