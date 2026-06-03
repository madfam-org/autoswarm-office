---
name: mcp-builder
description: Desarrollo de servidores de Model Context Protocol para construir extensiones de plataforma e integraciones de herramientas.
allowed_tools:
  - file_read
  - file_write
  - bash_execute
metadata:
  category: development
  complexity: high
  locale: es-MX
---

# Habilidad de Construccion MCP

Usted construye servidores de Model Context Protocol (MCP) para extender la plataforma MADFAM.

## Estructura de un Servidor MCP

Un servidor MCP expone herramientas, recursos y prompts a los agentes LLM:

```
mi-servidor-mcp/
  src/
    index.ts          # Punto de entrada del servidor
    tools/            # Implementaciones de herramientas
    resources/        # Proveedores de recursos
    prompts/          # Plantillas de prompts
  package.json
  tsconfig.json
```

## Desarrollo de Herramientas

Cada herramienta debe definir:
- **name**: Identificador unico (kebab-case).
- **description**: Explicacion clara de lo que hace la herramienta.
- **inputSchema**: JSON Schema para los parametros.
- **handler**: Funcion asincrona que implementa la logica de la herramienta.

## Mejores Practicas

- Mantenga las herramientas enfocadas y con un solo proposito.
- Valide todas las entradas contra el esquema antes de procesar.
- Devuelva resultados estructurados (no solo cadenas de texto).
- Maneje los errores de forma controlada con mensajes descriptivos.
- Registre (log) las invocaciones de herramientas para depuracion.
- Limite la frecuencia de llamadas a APIs externas (rate limiting).

## Integracion con Selva

Los servidores MCP en la plataforma MADFAM se registran a traves de la configuracion de nexus-api.
Cada agente puede acceder a las herramientas MCP segun los permisos de sus habilidades.
El motor de permisos evalua las llamadas a herramientas a traves de la matriz HITL estandar.
