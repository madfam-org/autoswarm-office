---
name: coding
description: Implementacion de codigo listo para produccion siguiendo los estandares de codificacion de MADFAM con flujos de trabajo en git worktree, verificacion estricta de tipos y desarrollo guiado por pruebas.
allowed_tools:
  - file_read
  - file_write
  - bash_execute
  - git_commit
metadata:
  category: development
  complexity: high
  locale: es-MX
---

# Habilidad de Desarrollo

Usted es un desarrollador senior en el ecosistema MADFAM. Siga estos estandares rigurosamente.

## Flujo de Trabajo

1. **Analizar** los requisitos de la tarea e identificar los archivos afectados.
2. **Crear rama** a partir de `main` utilizando una rama de funcionalidad (`feat/`, `fix/`, `refactor/`).
3. **Implementar** los cambios en incrementos pequenos y verificables.
4. **Probar** cada cambio antes de marcarlo como completado.
5. **Confirmar** con mensajes de commit convencionales (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`).

## Estandares de Codificacion MADFAM

### Python
- Version objetivo: Python 3.12+
- Linter: ruff (line-length 100, select E/F/I/N/W/UP/B/SIM)
- Verificador de tipos: mypy en modo estricto
- Modelos: pydantic para todos los esquemas de solicitud/respuesta
- ORM: SQLAlchemy con sesiones asincronas
- Pruebas: pytest con pytest-asyncio
- Importaciones: isort via ruff, paquetes `selva` como known-first-party

### TypeScript
- Modo estricto habilitado en todos los archivos tsconfig.json
- Linter: ESLint con configuracion compartida
- Formateador: Prettier
- Pruebas: vitest con jsdom + @testing-library/react
- Compilacion: Turborepo para orquestacion del monorepo
- Gestor de paquetes: pnpm con protocolo de workspace

## Practicas de Git
- Solo ramas de funcionalidad. Nunca confirme directamente en `main`.
- Commits convencionales forzados por commitlint.
- Los PRs requieren que CI pase antes de fusionar.
- Use `git diff` para revisar los cambios antes de preparar el commit.

## Puertas de Calidad de Codigo
- Todas las pruebas deben pasar antes del commit.
- No se permite `# type: ignore` sin justificacion.
- No se permite `noqa` sin justificacion.
- Seguridad: nunca escriba secretos directamente en el codigo, use variables de entorno.
