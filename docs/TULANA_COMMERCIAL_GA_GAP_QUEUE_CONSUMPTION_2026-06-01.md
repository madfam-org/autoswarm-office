# Tulana Commercial GA gap queue consumption

Status: active owner queue contract
Date: 2026-06-01
Owner system: Selva

## Source

```http
GET https://tulana-api.madfam.io/api/v1/commercial-ga-gap-queue/?environment=production&period=2026-06&owner=selva&gate=G3
```

## Selva responsibility

Selva owns `G3` campaign proof packs:

- Target segment.
- Offer and price.
- Approved claims.
- Disallowed claims.
- Commercial risk controls.
- Downstream no-go gates.

## ROI rule

Process rows in returned order. `karafiel__contador` already has `G3` passed,
so the next expected Selva items begin with `coforma__startup`, then
`tezca__pro`, then `dhanam__pro`, then `pravara-mes__starter`.

Do not generate GA claims for `candidate` SKUs.
