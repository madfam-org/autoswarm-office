# Phygital Quote Truth Contract

Selva agents may generate fabrication quote requests through Yantra4D or
Cotiza, but they must preserve the pricing truth labels returned by those
systems.

## Required behavior

1. Prefer `project_slug` so Yantra4D can attach project and mesh provenance.
2. Use direct Cotiza calls only when structured `project` and `geometry` data
   are already available.
3. Send `require_market_verified: true` when a client-facing quote requires
   ForgeSight market evidence.
4. Treat `market_context.market_verified: false` as a failed client quote, even
   if Cotiza created a quote record.
5. Do not create a work order until DFM has passed and the quote has human or
   market-verification approval.

## Response compatibility

Selva accepts both historical snake_case Cotiza fields and current camelCase
fields:

1. `quote_id` or `quoteId`
2. `total_price` or `totalPrice`

The authoritative truth label remains `market_context.market_verified`.
