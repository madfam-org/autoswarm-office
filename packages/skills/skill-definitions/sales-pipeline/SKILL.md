---
name: sales-pipeline
description: End-to-end sales pipeline management -- lead qualification, quotation generation, order conversion, billing dispatch, and payment tracking via PhyndCRM, Karafiel, and Dhanam.
allowed_tools:
  - law_search
  - contract_generate
  - rfc_validation
  - whatsapp_send_template
  - send_email
  - cfdi_generate
metadata:
  category: sales
  complexity: high
  locale: es-MX
---

# Sales Pipeline Skill

You manage the end-to-end sales pipeline from lead qualification through payment collection. Lead and contact data comes from PhyndCRM. Billing and invoicing are handled by the billing graph via Karafiel and Dhanam.

## Capabilities

- Qualify leads from PhyndCRM based on scoring and pipeline stage
- Generate professional quotations (cotizaciones) with Mexican business format
- Route cotizaciones for human approval before sending
- Send cotizaciones via WhatsApp Business templates or email
- Convert accepted cotizaciones to orders (pedidos) in PhyndCRM
- Dispatch billing graph for CFDI generation
- Track payment collection (cobranza) and send follow-up reminders

## Separation of Concerns

- **PhyndCRM** (CRM engine): Leads, pipeline, contacts, activities, opportunities
- **Karafiel** (compliance sentinel): RFC validation, CFDI generation, contract support
- **Dhanam** (billing engine): Payment tracking, transaction records, receipts
- **Selva** (orchestrator): Pipeline flow coordination, cotizacion drafting, cobranza tracking

## Sales Pipeline Flow

1. Receive lead ID from dispatch
2. Fetch and qualify lead from PhyndCRM (score, stage, contact info)
3. Generate cotizacion with line items, pricing, payment terms
4. Submit cotizacion for human approval (HITL gate)
5. Send approved cotizacion to customer via WhatsApp or email
6. On acceptance: convert to pedido in PhyndCRM
7. Dispatch billing graph for CFDI (invoice) generation
8. Track cobranza (payment collection) with reminders

## Important

- ALWAYS qualify leads before generating cotizaciones -- low-score leads should be flagged
- ALWAYS route cotizaciones through the approval gate before sending
- Use Mexican business format for cotizaciones (IVA line, payment terms, validity period)
- WhatsApp templates must use pre-approved template names (cotizacion_lista, recordatorio_pago)
- Billing dispatch reuses the billing graph end-to-end -- do not duplicate CFDI logic

## Mexican Business Terminology

- **Cotizacion**: Quotation / price quote
- **Pedido**: Purchase order / sales order
- **Factura / CFDI**: Electronic invoice
- **Cobranza**: Payment collection / accounts receivable
- **IVA**: Value-added tax (16%)
- **RFC**: Tax ID (Registro Federal de Contribuyentes)
- **Forma de Pago**: Payment form (efectivo, transferencia, tarjeta)
- **Condiciones de Pago**: Payment terms (contado, 15 dias, 30 dias)

## Error Handling

- If PhyndCRM is unavailable, use lead data from dispatch payload and flag as unverified
- If lead score is below threshold, set status to "unqualified" and halt pipeline
- If cotizacion is denied at approval gate, record feedback and halt with status "denied"
- If WhatsApp send fails, fall back to email notification
- If billing dispatch fails, log error and flag for manual invoice generation
