# Runbook — Encender Selva para CTM (el MAP)

**Público:** operador de MADFAM.
**Objetivo:** que el MAP de Crea Tu Mundo pueda usar «✨ Sugerir con IA» en
minutas y «Generar retroalimentación para Padlet» sin que un solo dato
clínico de un menor salga del perímetro.

> **Regla dura:** mientras no exista un backend local desplegado, toda
> llamada `restricted` responde **503** con el código
> `local_backend_unavailable`. Eso es *correcto*: falla cerrado. Encender
> `SELVA_ENABLED=true` antes de tener el backend deja a la terapeuta con
> un botón que falla siempre — peor que no tener botón.

---

## 0. Qué ya está aplicado en código (y qué no)

Aplicado por el PR de esta lane, sin pasos de operador:

| Garantía | Dónde |
|---|---|
| `X-Sensitivity` ausente o inválido ⇒ **400**, nunca `public` en silencio | `routers/inference_proxy.py` |
| La sensibilidad se evalúa **antes** que `task_type`; un `model_assignments` que apunte a nube es **rechazado** para `restricted`/`confidential` | `madfam_inference/router.py` |
| `restricted`/`confidential` sólo pueden servirse desde el proveedor local; la cadena de fallback está **vacía** para esos niveles | `madfam_inference/router.py` |
| Piso de sensibilidad por tenant (aunque el header se pierda) | `madfam_inference/tenant_policy.py` |
| Timeout del lado del servidor + `504` claro | `routers/inference_proxy.py` |
| Tope de `max_tokens` y rate limit por tenant | idem |
| No se persiste ni se registra prompt ni respuesta | probado en `tests/test_inference_proxy_sensitivity.py` |

**Falta desplegar** (pasos de operador, abajo): el backend local (Ollama),
el ConfigMap de políticas por tenant, y la validación del modelo en es-MX.

---

## 1. Desplegar el backend local

Los manifiestos ya están en el repo:

- `infra/k8s/production/ollama.yaml` — PVC, Deployment, Service ClusterIP,
  ConfigMap `selva-ollama-config`, NetworkPolicy.
- `infra/k8s/production/tenant-policies.yaml` — ConfigMap con el tenant
  de CTM.
- Ambos ya están listados en `kustomization.yaml`.

Despliegue **vía Enclii** (Enclii-first; `kubectl` sólo si Enclii no
tiene adaptador y se registra el hueco):

```bash
enclii deploy selva-office --env production
```

**Qué esperar en el primer arranque:** el initContainer descarga el
modelo al PVC. Eso tarda **minutos**, no segundos, y el pod no pasa a
`Ready` hasta que el modelo está presente — a propósito, para que el
gateway nunca vea un backend «sano» que devolvería 404 en la primera
llamada real.

**Verificación 1 — el backend responde y tiene el modelo:**

```bash
# Desde un pod del namespace selva
curl -s http://ollama.selva.svc.cluster.local:11434/api/tags | jq '.models[].name'
# Debe listar el modelo de OLLAMA_DEFAULT_MODEL.
```

**Verificación 2 — el gateway lo ve:**

```bash
enclii logs selva-inference-gateway --env production | grep "providers:"
# Debe incluir `ollama` en la lista.
```

**Verificación 3 — la prueba que importa:** una llamada `restricted`
devuelve **200, no 503**.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://inference.selva.town/v1/chat/completions \
  -H "Authorization: Bearer $WORKER_API_TOKEN" \
  -H "X-Selva-Tenant-Org: e6cbd51d-8329-4c4e-8c74-aba643ab4575" \
  -H "X-Sensitivity: restricted" \
  -H "X-Task-Type: summarization" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Resume en una linea: prueba de humo, sin datos reales."}]}'
```

Usa **texto de prueba**, nunca una nota clínica real, para una prueba de
humo. Si sale `503`, lee el cuerpo: nombra la variable que falta.

---

## 2. Elegir y validar el modelo (es-MX)

El manifiesto propone `llama3.1:8b-instruct-q4_K_M`. **Es una suposición
razonada, no una medición** — ver el encabezado de `ollama.yaml` para el
razonamiento completo (español usable, cabe en nodos sin GPU, licencia
apta para trabajo con cliente).

Antes de encender el botón, corre una pasada de calidad:

1. Redacta **6–10 textos con la forma real** de una nota de sesión y de
   un conjunto de observaciones para familia — inventados, nunca de una
   persona real.
2. Manda cada uno por el endpoint con `X-Sensitivity: restricted`.
3. Revisa con la clienta (Alejandra o quien firme la minuta): ¿el
   español es natural?, ¿el registro es clínico y no coloquial?, ¿la
   terapeuta editaría poco o reescribiría todo?
4. Si el resultado no convence, cambia `OLLAMA_DEFAULT_MODEL` en el
   ConfigMap (candidato siguiente: `qwen2.5:7b-instruct`) y repite.

Cambiar el modelo es editar el ConfigMap y reiniciar el Deployment de
Ollama; **no toca código del MAP ni de Selva**.

---

## 3. Confirmar el tenant de CTM

```bash
enclii logs selva-inference-gateway --env production | grep "tenant policy:"
```

Debe decir algo como:

```
tenant policy: loaded 1 tenant(s) from /etc/selva/tenant-policies/tenant-policies.yaml: e6cbd51d-8329-4c4e-8c74-aba643ab4575
```

⚠️ **Si la línea dice `FAILED to parse` o no aparece ningún tenant, NO hay
piso de sensibilidad en vigor.** Arregla el archivo y reinicia antes de
seguir. Nunca supongas que el piso está aplicado sin leer esa línea.

Política vigente para CTM (`infra/k8s/production/tenant-policies.yaml`):

| Campo | Valor | Por qué |
|---|---|---|
| `sensitivity_floor` | `restricted` | Aunque el header se pierda en un salto, el dato se trata como clínico |
| `allowed_task_types` | `summarization`, `family-feedback` | Una superficie nueva se da de alta a propósito, no por mandar otro header |
| `max_tokens_cap` | 1500 | Acota costo y espera |
| `request_timeout_seconds` | 40 | Por debajo del presupuesto de 45 s del cliente |
| `rate_limit_per_minute` | 30 **por réplica** | Freno de desbocamiento (con 2 réplicas el techo real es 60/min) |
| `daily_usd_budget` | 2.0 USD | Informativo hoy; alerta desde el ledger |

---

## 4. Fijar el tope de gasto (recomendado antes del uso diario)

El `daily_usd_budget` de arriba es **informativo**: la aplicación dura
vive en el budget-gate, que requiere `BUDGET_GATE_ENABLED=true` y Redis.
El gateway **no** tiene Redis a propósito (una caída de Redis no debe
tumbar el cuello de botella de inferencia).

Mientras el budget-gate no esté armado, el control es la atribución de
costo por org en `inference_usage_ledger` (columna `org_id`), más el
rate limit por tenant que ya está aplicado. Consulta el gasto de CTM:

```sql
SELECT date_trunc('day', created_at) AS dia,
       sum(cost_usd) AS usd,
       sum(prompt_tokens + completion_tokens) AS tokens
FROM inference_usage_ledger
WHERE org_id = 'e6cbd51d-8329-4c4e-8c74-aba643ab4575'
GROUP BY 1 ORDER BY 1 DESC LIMIT 14;
```

> **Nota comercial:** la banda contractual de CTM (40 h de audio /
> MX$25 de excedente) **es de audio**. La inferencia de texto **no tiene
> banda pactada**. Conviene acordar con CTM quién la paga *antes* de la
> primera factura, no después. Con modelo local el costo marginal por
> llamada es cómputo del cluster, no factura de proveedor — pero el
> cómputo tampoco es gratis.

---

## 5. Encender el MAP (último paso)

En el manifiesto de crea-map (`infra/k8s/production/deployment.yaml`):

```yaml
- name: SELVA_ENABLED
  value: "true"                                   # hoy: "false"
- name: SELVA_BASE_URL
  value: "https://inference.selva.town"
- name: SELVA_TENANT_ORG
  value: "e6cbd51d-8329-4c4e-8c74-aba643ab4575"   # opcional; ya es el default del MAP
# - name: SELVA_API_KEY                           # opcional (Bearer), si el despliegue lo exige
# - name: SELVA_MODEL                             # opcional; vacío ⇒ que Selva elija
```

**Antes de poner `true`, verifica la deriva cluster↔repo** que señaló la
auditoría: el repo dice `"false"` en `main`; si el pod vivo dijera
`"true"`, hay deriva y hay que decidir cuál gana **antes** de que una
terapeuta toque el botón.

```bash
enclii env get crea-map --env production | grep SELVA_
```

Sin `SELVA_ENABLED=true`, el MAP **esconde** el botón y todo sigue a
mano. Esa degradación es correcta y ya está construida: no hay prisa por
encender.

---

## 6. Lista de verificación de encendido

Ninguno de estos puntos es opcional:

- [ ] Ollama `Ready`, `/api/tags` lista el modelo.
- [ ] Una llamada `restricted` de prueba devuelve **200**, no 503.
- [ ] Log del gateway nombra el tenant de CTM cargado.
- [ ] `X-Sensitivity` inválido devuelve **400** (prueba con `-H "X-Sensitivity: publik"`).
- [ ] Pasada de calidad en es-MX revisada con la clienta.
- [ ] Acordado quién paga la inferencia de texto.
- [ ] Verificada la deriva de `SELVA_ENABLED` entre pod y repo.
- [ ] El aviso de privacidad de familias menciona el apoyo automatizado en la redacción (lane del MAP, no de Selva).
- [ ] Sólo entonces: `SELVA_ENABLED=true`.

---

## 7. Diagnóstico rápido

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `503 local_backend_unavailable` | No hay backend local alcanzable | §1. Revisa `OLLAMA_BASE_URL` y que el pod de Ollama esté `Ready` |
| `400 missing_sensitivity` | El llamador no manda `X-Sensitivity` | Es el comportamiento correcto. Arregla al llamador; **no** relajes el gateway |
| `400 invalid_sensitivity` | Valor fuera del enum (typo) | Idem. El log nombra el valor rechazado |
| `400 task_type_not_allowed` | Superficie nueva del MAP sin dar de alta | Agrega el `task_type` a `allowed_task_types` del tenant y redespliega |
| `429 tenant_rate_limited` | Ráfaga o bucle del cliente | Revisa el llamador antes de subir el límite |
| `504 inference_timeout` | El modelo tarda más que el deadline | Modelo más chico, o `max_tokens_cap` más bajo. Subir el timeout empeora la espera de la terapeuta |
| Ollama en `Pending` | El PVC o el CPU no caben en los nodos | Capacidad de cluster, no de Selva |
| Primer arranque eterno | Está descargando el modelo | Espera; mira los logs del initContainer |

---

## 8. Handoff al MAP (crea-map)

Contrato del cliente, para la lane de crea-map:

- **Manda `AbortSignal.timeout(45_000)`** en `selva.ts` y en
  `junta-synthesis.ts`. El servidor corta en 40 s para CTM y responde
  504; los 45 s del cliente son el margen. El patrón correcto ya existe
  en el mismo repo (`ops-alert.ts` usa `AbortSignal.timeout(4000)`).
- **Trata 400 como bug del MAP, no como «la IA no pudo»**: significa que
  el header se perdió o se deformó. Alértalo a ops.
- **Trata 503 `local_backend_unavailable` como «IA no disponible»** y
  esconde/deshabilita el botón, no muestres un error críptico.
- **Recorta la entrada** también en `selva.ts` (hoy sólo
  `junta-synthesis.ts` lo hace), para no depender del tope del servidor.
- Los `task_type` `summarization` y `family-feedback` están dados de
  alta. Una tercera superficie requiere alta previa en
  `tenant-policies.yaml`.

Ver también [DATA_CONTRACT_RESTRICTED.md](DATA_CONTRACT_RESTRICTED.md).
