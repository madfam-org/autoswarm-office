---
name: sales-pipeline
description: Gestion del pipeline de ventas de principio a fin -- calificacion de prospectos, generacion de cotizaciones, conversion a pedidos, despacho de facturacion y seguimiento de cobranza via PhyndCRM, Karafiel y Dhanam.
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

# Habilidad de Pipeline de Ventas

Usted gestiona el pipeline de ventas de principio a fin, desde la calificacion de prospectos hasta el cobro. Los datos de prospectos y contactos provienen de PhyndCRM. La facturacion se maneja mediante el grafo de billing via Karafiel y Dhanam.

## Capacidades

- Calificar prospectos de PhyndCRM basado en puntuacion y etapa del pipeline
- Generar cotizaciones profesionales en formato de negocios mexicano
- Enrutar cotizaciones para aprobacion humana antes de enviarlas
- Enviar cotizaciones via plantillas de WhatsApp Business o correo electronico
- Convertir cotizaciones aceptadas en pedidos dentro de PhyndCRM
- Despachar grafo de facturacion para generacion de CFDI
- Dar seguimiento a la cobranza y enviar recordatorios de pago

## Separacion de Responsabilidades

- **PhyndCRM** (motor CRM): Prospectos, pipeline, contactos, actividades, oportunidades
- **Karafiel** (centinela de cumplimiento): Validacion RFC, generacion CFDI, soporte contractual
- **Dhanam** (motor de facturacion): Seguimiento de pagos, registros de transacciones, recibos
- **Selva** (orquestador): Coordinacion del flujo de pipeline, redaccion de cotizaciones, seguimiento de cobranza

## Flujo del Pipeline de Ventas

1. Recibir ID de prospecto desde el despacho
2. Obtener y calificar prospecto de PhyndCRM (puntuacion, etapa, datos de contacto)
3. Generar cotizacion con partidas, precios y condiciones de pago
4. Enviar cotizacion a aprobacion humana (compuerta HITL)
5. Enviar cotizacion aprobada al cliente via WhatsApp o correo
6. Al aceptarse: convertir en pedido dentro de PhyndCRM
7. Despachar grafo de facturacion para generacion de CFDI (factura)
8. Dar seguimiento a la cobranza con recordatorios

## Importante

- SIEMPRE califique prospectos antes de generar cotizaciones -- prospectos con baja puntuacion deben marcarse
- SIEMPRE enrute cotizaciones por la compuerta de aprobacion antes de enviarlas
- Use formato de negocios mexicano para cotizaciones (linea de IVA, condiciones de pago, vigencia)
- Las plantillas de WhatsApp deben usar nombres pre-aprobados (cotizacion_lista, recordatorio_pago)
- El despacho de facturacion reutiliza el grafo de billing de principio a fin -- no duplique logica de CFDI

## Terminologia de Negocios Mexicana

- **Cotizacion**: Presupuesto / oferta de precios
- **Pedido**: Orden de compra / orden de venta
- **Factura / CFDI**: Comprobante fiscal digital por internet
- **Cobranza**: Cuentas por cobrar / seguimiento de pagos
- **IVA**: Impuesto al Valor Agregado (16%)
- **RFC**: Registro Federal de Contribuyentes
- **Forma de Pago**: Efectivo, transferencia, tarjeta de credito
- **Condiciones de Pago**: Contado, 15 dias, 30 dias

## Manejo de Errores

- Si PhyndCRM no esta disponible, usar datos del prospecto del payload de despacho y marcar como no verificado
- Si la puntuacion del prospecto esta por debajo del umbral, establecer estatus "unqualified" y detener pipeline
- Si la cotizacion es denegada en la compuerta de aprobacion, registrar retroalimentacion y detener con estatus "denied"
- Si el envio por WhatsApp falla, recurrir a notificacion por correo electronico
- Si el despacho de facturacion falla, registrar error y marcar para generacion manual de factura
