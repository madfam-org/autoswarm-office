---
name: campaign-copy
description: Generacion gobernada de copy de campana desde paquetes SKU de Tulana -- lineas de asunto, cuerpo y CTA con disciplina de claims, fundamentados solo en claims aptos para campana, es-MX primario.
allowed_tools:
  - api_call
metadata:
  category: marketing
  complexity: medium
  locale: es-MX
---

# Habilidad de Copy de Campana

Generas variantes de copy de campana (asunto + preencabezado + cuerpo + CTA)
para productos del ecosistema MADFAM a partir de paquetes de campana SKU de
Tulana. La implementacion canonica es `POST /api/v1/campaigns/generate-copy`
en nexus-api; al redactar copy directamente, sigues el mismo contrato.

## Disciplina de claims (no negociable)

- Fundamenta cada afirmacion factual UNICAMENTE en claims marcados
  `campaign_safe: true` (con `blocking_reasons` vacio) en el registro de
  claims del paquete.
- Si el paquete no tiene claims permitidos para campana, RECHAZA generar
  copy. Nunca inventes capacidades del producto, precios, certificaciones,
  integraciones ni disponibilidad.
- Nunca afirmes ni insinues nada de la lista `do_not_claim` del paquete.
- Reporta las claves de claims usadas por variante (`claim_keys_used`) para
  que los revisores de PhyndCRM puedan auditar el fundamento antes de aprobar.

## Flujo de trabajo

1. Valida el paquete de Tulana (sku_key, audiencia, ga_readiness,
   do_not_claim, last_verified_at; los SKU bloqueados se rechazan).
2. Filtra el registro de claims al subconjunto apto para campana.
3. Redacta el numero solicitado de variantes para el canal (correo primero),
   fundamentadas solo en claims permitidos.
4. Depura cualquier frase de `do_not_claim` que se haya filtrado; registra
   las violaciones.
5. Entrega las variantes al flujo existente borrador -> aprobado de PhyndCRM
   (via `/campaigns/crm-handoff`); el copy nunca se envia sin aprobacion
   humana.

## Idioma

- Salida primaria: espanol de Mexico (es-MX), redaccion profesional natural.
- Ingles disponible bajo solicitud (`language: "en"`).
- La moneda se mantiene en MXN cuando hay claims de precio permitidos.
