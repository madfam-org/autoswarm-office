# Contrato de datos — el nivel `restricted` de Selva

**Para quien consume Selva** (equipos de producto del ecosistema) y para
quien tiene que responderle a un cliente, a una familia o a una autoridad
qué pasa exactamente con un dato sensible.

Escrito en español llano a propósito: si una frase de aquí no se puede
sostener frente a la madre de un menor atendido, está mal escrita o el
sistema está mal hecho.

---

## 1. Los cuatro niveles

Selva no adivina qué tan sensible es lo que le mandas. **Tú lo declaras**
en el header `X-Sensitivity`, y ese header es **obligatorio**.

| Nivel | Qué significa | A dónde va |
|---|---|---|
| `public` | Puede publicarse. Marketing, texto de sitio. | Proveedor de nube más barato |
| `internal` | Interno de MADFAM. No confidencial de cliente. | Proveedor de nube |
| `confidential` | Confidencial de un cliente. | **Sólo modelo local** |
| `restricted` | Dato personal sensible o regulado: clínico, de menores, fiscal, laboral. | **Sólo modelo local** |

Si no mandas el header, o mandas un valor que no está en esta lista, la
llamada **se rechaza con 400**. No se adivina, no se degrada al nivel más
barato, no se procesa. Antes esto no era así: la ausencia del header
significaba `public`, y un valor mal escrito se ignoraba en silencio. Esa
era la peor falla posible, porque el modo de falla por defecto era «mandar
el dato a la nube más barata».

---

## 2. Qué garantiza `restricted` (y qué no)

### Lo que sí

1. **El dato no sale del perímetro.** Una llamada `restricted` sólo puede
   ser servida por el modelo local que corre dentro del cluster. No hay
   ningún camino de código por el que llegue a Anthropic, OpenAI,
   DeepInfra ni ningún otro tercero.

2. **Ningún atajo puede saltarse esa regla.** La sensibilidad se evalúa
   **antes** que cualquier otra decisión de ruteo. Ni el `task_type`, ni
   las listas de prioridad de la configuración de la organización, ni la
   cadena de reintentos pueden ampliar el conjunto de proveedores
   permitidos. Si alguien configura «los resúmenes van a DeepInfra», esa
   configuración es **rechazada** para datos `restricted` y queda un
   WARNING en la bitácora.

   *Esto no era así antes.* El ruteo por `task_type` se evaluaba primero
   y ganaba. El MAP de Crea Tu Mundo se salvaba de casualidad, porque los
   nombres que usa (`summarization`, `family-feedback`) no estaban en el
   catálogo interno de tipos de tarea. Estaba protegido por el nombre que
   eligió, no por una garantía. Ahora es una garantía.

3. **Si no hay modelo local, la llamada falla.** Devuelve **503** con el
   código `local_backend_unavailable`. Nunca se sirve desde la nube «para
   que al menos funcione». Falla cerrado.

4. **No se guarda ni el texto que mandas ni el que responde.** La bitácora
   de consumo registra: organización, quién llamó, proveedor, modelo,
   cuántos tokens y cuánto costó. **No hay ninguna columna donde quepa un
   prompt o una respuesta.** Las líneas de bitácora del gateway llevan
   metadatos de ruteo (organización, tipo de tarea, nivel de
   sensibilidad) y nunca contenido. Hay pruebas automáticas que fallan si
   alguna vez el contenido se filtra a una bitácora o a la base.

5. **Un piso por cliente, por si el header se pierde.** Una organización
   regulada puede declarar un `sensitivity_floor`. Con el piso en
   `restricted`, aunque una llamada llegue marcada como `public` —header
   perdido en un salto, proxy que lo borra, superficie nueva que se
   olvidó de ponerlo— se trata como `restricted`. El piso sube, nunca
   baja: quien pida más protección que su piso, la conserva.

### Lo que no

1. **No es cifrado de extremo a extremo.** El texto se procesa en claro
   en la memoria del modelo local, dentro del cluster.

2. **No es una afirmación sobre los otros niveles.** `public` e
   `internal` sí van a proveedores de nube. Si tienes duda de qué nivel
   corresponde, sube de nivel: el costo de marcar de más es latencia; el
   de marcar de menos es un dato personal en un tercero.

3. **No sustituye la minimización.** Selva no puede saber que le mandaste
   un nombre completo cuando bastaban iniciales. **Manda lo mínimo.** La
   responsabilidad de no incluir lo que no hace falta es del llamador.

4. **No hay afirmación de «cero retención» (ZDR) con proveedores de
   nube.** No existe hoy, ni documentada ni aplicada. El sustituto
   arquitectónico es la localidad: por eso el dato regulado se sirve
   localmente en lugar de confiar en la promesa de un tercero.

---

## 3. Por qué esto importa legalmente (caso CTM/MAP)

El MAP de Crea Tu Mundo trata datos personales sensibles de menores.
Existe un Anexo A firmado que es un acuerdo de **encargado** bajo la
LFPDPPP. Bajo esa ley, que un encargado trate el dato no es una
*transferencia* sino una *remisión*.

El aviso de privacidad que leen las familias dice que **no se transfieren
sus datos a terceros**. Esa frase es defendible **mientras la inferencia
se sirva dentro de la cadena de encargado** — es decir, dentro del
perímetro, no en un proveedor de nube externo.

Si `restricted` alguna vez se sirviera desde un tercero, esa frase
quedaría en falso frente a las familias, con datos sensibles de menores.
De ahí que la regla sea estructural en el código y no una convención, y
que la falla sea cerrada (503) en vez de abierta.

**Pendiente que no es de Selva:** el aviso de privacidad del MAP no
menciona hoy que hay apoyo automatizado en la redacción. No es un
incumplimiento evidente —sigue siendo tratamiento para la misma
finalidad, la terapeuta decide, y el texto no se guarda— pero conviene
cerrarlo con una línea explícita en el aviso, no con silencio.

---

## 4. Cómo llamar bien (contrato del cliente)

```http
POST /v1/chat/completions
Authorization: Bearer <token>
X-Sensitivity: restricted          ← obligatorio, literal fijo en tu código
X-Selva-Tenant-Org: <org id>       ← tu organización
X-Task-Type: summarization         ← dado de alta para tu tenant
Content-Type: application/json
```

Reglas para el llamador:

1. **Fija el literal en el código.** Que ninguna superficie pueda bajar
   el nivel por descuido: una constante, no un parámetro. (`crea-map`
   lo hace bien: `const SELVA_SENSITIVITY = 'restricted'`.)
2. **Manda tu propio `AbortSignal`**, un poco por encima del deadline del
   servidor (45 s de cliente contra 40 s de servidor, para CTM).
3. **Recorta la entrada** antes de mandarla. No dependas del tope del
   servidor.
4. **Degrada con gracia.** Si Selva no está configurado o responde 503,
   esconde la superficie de IA; el trabajo manual debe seguir intacto.
5. **No registres el prompt de tu lado tampoco.** El contrato se rompe
   igual si el dato queda en la bitácora del consumidor.

### Qué significa cada respuesta

| Código | Significa | Qué hacer |
|---|---|---|
| `200` | Listo. | Un humano revisa antes de enviar/guardar |
| `400 missing_sensitivity` | No mandaste el header | **Bug tuyo.** Alerta a ops; no lo trates como «la IA no pudo» |
| `400 invalid_sensitivity` | Valor fuera del enum | **Bug tuyo.** El log del gateway nombra el valor |
| `400 task_type_not_allowed` | Superficie no dada de alta | Alta previa en la política del tenant |
| `429 tenant_rate_limited` | Ráfaga | Respeta `Retry-After`. Revisa si hay un bucle |
| `504 inference_timeout` | Tardó más que el deadline | Reintento manual del usuario; entrada más corta |
| `503 local_backend_unavailable` | No hay modelo local | **IA no disponible.** Esconde la superficie. No es un error del usuario |

---

## 5. Si alguien pregunta

**«¿Mis datos van a ChatGPT / a una IA de Estados Unidos?»**
No, si están marcados como `restricted` o `confidential`. Esos se
procesan con un modelo que corre en la infraestructura de MADFAM, dentro
del mismo perímetro donde ya vive el dato. No se envían a ningún
proveedor externo, y si ese modelo local no está disponible la función
simplemente no funciona: no hay un plan B que mande el dato afuera.

**«¿Se guarda lo que escribo?»**
El texto que se manda al modelo y el que el modelo responde no se
guardan. Sólo se registra cuánto se usó (cuántos tokens, qué modelo,
cuánto costó) para poder facturar y vigilar el gasto. El resultado que la
profesional decida conservar se guarda en el expediente del sistema que
lo pidió —no en Selva— y siempre después de que ella lo revise.

**«¿La IA decide algo?»**
No. Redacta un borrador. Siempre hay una persona que lo lee, lo corrige
y decide si se usa.

---

## 6. Referencias

- Runbook de encendido para CTM: [RUNBOOK_SELVA_CTM.md](RUNBOOK_SELVA_CTM.md)
- Ruteo y proveedores: [INFERENCE_PROVIDERS.md](INFERENCE_PROVIDERS.md)
- Residencia por tenant (borrador): [rfcs/0020-per-tenant-data-residency.md](rfcs/0020-per-tenant-data-residency.md)
- Código: `packages/inference/madfam_inference/router.py` (frontera de
  sensibilidad), `madfam_inference/tenant_policy.py` (pisos y topes),
  `apps/nexus-api/nexus_api/routers/inference_proxy.py` (validación).
- Pruebas que sostienen cada afirmación de este documento:
  `packages/inference/tests/test_router_sensitivity_precedence.py`,
  `apps/nexus-api/tests/test_inference_proxy_sensitivity.py`.
