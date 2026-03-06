---
name: webapp-testing
description: End-to-end testing with Playwright patterns for office-ui, Phaser scene testing, and comprehensive test coverage.
allowed_tools:
  - file_read
  - file_write
  - bash_execute
metadata:
  category: testing
  complexity: medium
---

# Web App Testing Skill

You test the AutoSwarm Office web application (office-ui) and its Phaser game scenes.

## Testing Stack

- **Unit tests**: vitest with jsdom + @testing-library/react
- **E2E tests**: Playwright for browser automation
- **Game tests**: Phaser scene testing with mocked game objects

## Playwright Patterns

### Page Object Model
Organize tests around page objects for maintainability:
- `LoginPage`: Janua auth flow
- `OfficePage`: Main game canvas and UI overlays
- `AdminPage`: Admin dashboard interactions

### Test Structure
```typescript
test('agent approval flow', async ({ page }) => {
  await page.goto('/');
  // Wait for Phaser canvas to load
  await page.waitForSelector('canvas');
  // Interact with approval dialog
  await page.click('[data-testid="approve-btn"]');
  await expect(page.locator('[data-testid="status"]')).toHaveText('approved');
});
```

## Phaser Scene Testing

- Mock `Phaser.Game` and scene lifecycle methods.
- Test animation state transitions (idle -> working -> waiting_approval).
- Verify sprite creation and positioning within department zones.
- Test keyboard/gamepad input handling.

## Coverage Requirements

- Minimum 80% line coverage for new code.
- All API endpoints must have request/response tests.
- All Colyseus message handlers must have unit tests.
