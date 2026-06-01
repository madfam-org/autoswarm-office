# Selva to Tulana Commercial GA evidence producer

Status: producer contract
Date: 2026-06-01
Source system: Selva
Target system: Tulana

## ROI priority

Selva should only prepare outbound/commercial motions in this order until the
first cash path is proven:

1. `karafiel__contador`
2. `coforma__startup`
3. `tezca__pro`
4. `dhanam__pro` as billing smoke only
5. `pravara-mes__starter`

## Gates owned by Selva

| Gate | Evidence condition | Minimum payload |
| --- | --- | --- |
| `G2` Selva-to-Dhanam application | Tulana-approved handoff is applied to Dhanam. | handoff ID, SKU key, applied timestamp, Dhanam catalog reference |
| `G3` Campaign proof pack | Campaign proof pack is ready for a specific SKU. | campaign ID, target segment, offer, claims review, risk notes |

## Tulana write target

```http
POST /api/v1/madfam-skus/{product_slug}/{tier_slug}/commercial-ga-evidence/
```

## G3 example

```json
{
  "environment": "production",
  "period": "2026-06",
  "gate_id": "G3",
  "status": "passed",
  "confidence": "high",
  "evidence_type": "selva_campaign_proof_pack",
  "evidence_url": "https://selva-office.madfam.io/evidence/campaigns/{campaign_id}",
  "source_system": "selva",
  "source_record_id": "{campaign_id}",
  "metadata": {
    "sku_key": "karafiel__contador",
    "campaign_lane": "first_pesos_primary",
    "claim_risk": "reviewed"
  }
}
```

## Non-negotiables

- Selva agents must not claim a SKU is GA unless Tulana reports
  `campaign_ga_ready`.
- Selva may prepare `candidate` SKU proof packs, but may not send paid
  outbound campaigns before PhyndCRM writes `G4`.
- `G3` must include reviewed offer claims and risk notes.
