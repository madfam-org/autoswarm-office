---
name: webapp-testing
description: Pruebas de extremo a extremo con patrones de Playwright para office-ui, pruebas de escenas Phaser y cobertura integral de pruebas.
allowed_tools:
  - file_read
  - file_write
  - bash_execute
metadata:
  category: testing
  complexity: medium
  locale: es-MX
---

# Habilidad de Pruebas de Aplicacion Web

Usted realiza pruebas de la aplicacion web Selva Office (office-ui) y sus escenas de juego Phaser.

## Stack de Pruebas

- **Pruebas unitarias**: vitest con jsdom + @testing-library/react
- **Pruebas E2E**: Playwright para automatizacion de navegador
- **Pruebas de juego**: Pruebas de escenas Phaser con objetos de juego simulados (mocks)

## Patrones de Playwright

### Modelo de Objetos de Pagina (Page Object Model)
Organice las pruebas alrededor de objetos de pagina para mantenibilidad:
- `LoginPage`: Flujo de autenticacion con Janua
- `OfficePage`: Canvas principal del juego y superposiciones de UI
- `AdminPage`: Interacciones del tablero de administracion

### Estructura de Pruebas
```typescript
test('flujo de aprobacion de agente', async ({ page }) => {
  await page.goto('/');
  // Esperar a que el canvas de Phaser cargue
  await page.waitForSelector('canvas');
  // Interactuar con el dialogo de aprobacion
  await page.click('[data-testid="approve-btn"]');
  await expect(page.locator('[data-testid="status"]')).toHaveText('approved');
});
```

## Pruebas de Escenas Phaser

- Simule (mock) `Phaser.Game` y los metodos del ciclo de vida de la escena.
- Pruebe las transiciones de estado de animacion (idle -> working -> waiting_approval).
- Verifique la creacion y posicionamiento de sprites dentro de las zonas de departamento.
- Pruebe el manejo de entrada por teclado/gamepad.

## Requisitos de Cobertura

- Minimo 80% de cobertura de lineas para codigo nuevo.
- Todos los endpoints de API deben tener pruebas de solicitud/respuesta.
- Todos los manejadores de mensajes de Colyseus deben tener pruebas unitarias.
