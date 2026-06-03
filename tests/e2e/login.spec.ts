import { test, expect } from "./fixtures";

test.describe("Login Flow", () => {
  test("dev auth bypass loads the office", async ({ page }) => {
    // Navigate to /office which redirects to /login when unauthenticated
    await page.goto("/office");
    // Should see either login form or go straight to game
    await page.waitForSelector(
      "canvas, [data-testid='office-main'], input",
      { timeout: 10000 },
    );

    // If login form, fill it
    const loginInput = page.locator(
      'input[name="displayName"], input[placeholder*="name" i]',
    );
    if (await loginInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await loginInput.fill("Test Player");
      await page.click('button[type="submit"]');
    }

    // Verify game canvas loaded
    await expect(page.locator("canvas")).toBeVisible({ timeout: 15000 });
  });

  test("landing page title contains Selva", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/selva|office/i);
  });

  test("landing page shows demo and sign-in CTAs", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator('a[href="/demo"]')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('a[href="/login"]')).toBeVisible({ timeout: 5000 });
  });
});
