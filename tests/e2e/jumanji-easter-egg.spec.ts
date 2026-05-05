import { test, expect } from "./fixtures";

/**
 * E2E for the Jumanji easter egg.
 *
 * Assumes `make dev` is running and `/status` is reachable. The
 * /status page is server-rendered and unauthenticated, so this spec
 * doesn't need login fixtures — it just visits the page and drives
 * the keyboard sequence.
 *
 * Skipped when E2E_RUN_JUMANJI is unset to keep the default CI run
 * fast; flip on locally with E2E_RUN_JUMANJI=1.
 */
const RUN = process.env.E2E_RUN_JUMANJI === "1";

test.describe("Jumanji easter egg", () => {
  test.skip(!RUN, "Set E2E_RUN_JUMANJI=1 to run");

  test("discovery -> activation -> portal", async ({ page }) => {
    // Mock PostHog before navigation so the events show up in window.
    await page.addInitScript(() => {
      const events: { name: string; props: unknown }[] = [];
      // @ts-expect-error attaching to window for the test
      window.__jumanjiEvents = events;
      // @ts-expect-error stub posthog
      window.posthog = {
        __loaded: true,
        capture: (name: string, props: unknown) => events.push({ name, props }),
        identify: () => {},
        reset: () => {},
        people: { set_once: () => {} },
      };
    });

    // Reset prior state.
    await page.goto("/status?reset_jumanji=1");

    const button = page.getByRole("button", {
      name: /mysterious device/i,
    });
    await expect(button).toBeVisible({ timeout: 10000 });

    // Snapshot resting state for design review.
    await page.screenshot({
      path: "test-results/jumanji-01-resting.png",
      clip: await button.boundingBox().then((b) => b ?? undefined),
    });

    // Focus + type the magic word.
    await button.focus();
    for (const k of "JUMANJI") {
      await page.keyboard.press(k);
    }

    await expect(button).toHaveAttribute("data-jumanji-state", "portal", {
      timeout: 3000,
    });

    // Step in.
    await button.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5000 });
    await expect(dialog).toContainText(/play\.rondel\.io/i);

    // Snapshot portal state.
    await page.screenshot({ path: "test-results/jumanji-04-portal.png" });

    // Verify analytics fired.
    const events = await page.evaluate(
      // @ts-expect-error reading test-only window field
      () => window.__jumanjiEvents as { name: string }[],
    );
    const names = events.map((e) => e.name);
    expect(names).toContain("jumanji_egg_seen");
    expect(names).toContain("jumanji_egg_activated");
    expect(names).toContain("jumanji_egg_portaled");
  });
});
