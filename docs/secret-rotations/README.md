# Secret Rotation Evidence

This directory stores scheduled and executed Selva-owned secret rotation
records.

The Phase 0.7 schedule gate is verified with:

```bash
./scripts/verify-secret-rotation-schedule.sh
```

Do not commit secret values, kubeconfig output, screenshots with credentials,
or provider tokens. Rotation evidence should include only target names,
timestamps, namespaces, operator identity if appropriate, and masked
fingerprints already emitted by `scripts/rotate-secret.sh`.
