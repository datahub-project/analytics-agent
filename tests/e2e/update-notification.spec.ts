/**
 * E2E tests for the update-notification feature.
 *
 * Covers:
 * - Amber dot appears on Settings button when update is available
 * - Settings opens directly to About when an update is available
 * - Settings opens to Connections when up to date
 * - About tab renders version info, update CTA, and release cards
 * - Release card expands/collapses with chevron rotation
 * - Refresh button re-fetches version info
 * - Airgapped / no releases: graceful empty state
 *
 * Uses page.route() to mock /api/version and /api/releases so tests run
 * independently of the real GitHub API and the installed package version.
 */

import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FAKE_RELEASES = [
  {
    tag_name: "v0.3.0",
    name: "v0.3.0",
    published_at: "2025-04-01T00:00:00Z",
    body: "## What's Changed\n- New feature A\n- Bug fix B",
    html_url: "https://github.com/datahub-project/analytics-agent/releases/tag/v0.3.0",
    prerelease: false,
  },
  {
    tag_name: "v0.2.2",
    name: "v0.2.2",
    published_at: "2025-03-01T00:00:00Z",
    body: "## What's Changed\n- Stability improvements",
    html_url: "https://github.com/datahub-project/analytics-agent/releases/tag/v0.2.2",
    prerelease: false,
  },
];

async function mockVersionEndpoint(
  page: Page,
  opts: { currentVersion: string; latestVersion: string; updateAvailable: boolean }
) {
  await page.route("/api/version", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        current_version: opts.currentVersion,
        latest_version: opts.latestVersion,
        update_available: opts.updateAvailable,
      }),
    })
  );
}

async function mockReleasesEndpoint(page: Page, releases = FAKE_RELEASES) {
  await page.route("/api/releases", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(releases),
    })
  );
}

async function gotoApp(page: Page) {
  await page.goto("/");
  await expect(page.locator("textarea").first()).toBeVisible({ timeout: 10_000 });
}

// ---------------------------------------------------------------------------
// Settings button — notification dot
// ---------------------------------------------------------------------------

test("Settings button shows amber dot when update is available", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.3.0",
    updateAvailable: true,
  });
  await gotoApp(page);

  // The dot renders as a bg-amber-500 span inside the Settings button
  const settingsBtn = page.locator("button[title='Settings — update available']");
  await expect(settingsBtn).toBeVisible({ timeout: 5_000 });
  await expect(settingsBtn.locator(".bg-amber-500")).toBeVisible();
});

test("Settings button has no dot when up to date", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.2.2",
    updateAvailable: false,
  });
  await gotoApp(page);

  await expect(page.locator("button[title='Settings']")).toBeVisible({ timeout: 5_000 });
  await expect(page.locator("button[title='Settings — update available']")).not.toBeVisible();
});

// ---------------------------------------------------------------------------
// Settings modal — initial tab selection
// ---------------------------------------------------------------------------

test("clicking Settings opens About tab when update is available", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.3.0",
    updateAvailable: true,
  });
  await mockReleasesEndpoint(page);
  await gotoApp(page);

  await page.locator("button[title='Settings — update available']").click();

  // About section header should be visible
  await expect(page.locator("h2", { hasText: "About" })).toBeVisible({ timeout: 5_000 });
  // Connections section should NOT be the active view
  await expect(page.locator("h2", { hasText: "Connections" })).not.toBeVisible();
});

test("clicking Settings opens Connections tab when up to date", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.2.2",
    updateAvailable: false,
  });
  await gotoApp(page);

  await page.locator("button[title='Settings']").click();

  await expect(page.locator("h2", { hasText: "Connections" })).toBeVisible({ timeout: 5_000 });
});

// ---------------------------------------------------------------------------
// About tab — content
// ---------------------------------------------------------------------------

test("About tab shows installed and latest version", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.3.0",
    updateAvailable: true,
  });
  await mockReleasesEndpoint(page);
  await gotoApp(page);

  await page.locator("button[title='Settings — update available']").click();

  await expect(page.locator("code", { hasText: "0.2.2" })).toBeVisible({ timeout: 5_000 });
  await expect(page.locator("code", { hasText: "0.3.0" })).toBeVisible();
});

test("About tab shows update CTA button when update is available", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.3.0",
    updateAvailable: true,
  });
  await mockReleasesEndpoint(page);
  await gotoApp(page);

  await page.locator("button[title='Settings — update available']").click();

  await expect(page.getByRole("link", { name: /Release notes/ })).toBeVisible({ timeout: 5_000 });
});

test("About tab shows up-to-date indicator when current", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.2.2",
    updateAvailable: false,
  });
  await mockReleasesEndpoint(page);
  await gotoApp(page);

  await page.locator("button[title='Settings']").click();
  await page.locator("button", { hasText: "About" }).click();

  await expect(page.locator("text=You're up to date")).toBeVisible({ timeout: 5_000 });
  await expect(page.getByRole("link", { name: /Release notes/ })).not.toBeVisible();
});

// ---------------------------------------------------------------------------
// About tab — release cards
// ---------------------------------------------------------------------------

test("About tab renders release cards from /api/releases", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.3.0",
    updateAvailable: true,
  });
  await mockReleasesEndpoint(page);
  await gotoApp(page);

  await page.locator("button[title='Settings — update available']").click();

  await expect(page.locator("text=v0.3.0")).toBeVisible({ timeout: 5_000 });
  await expect(page.locator("text=v0.2.2")).toBeVisible();
});

test("installed release card is badged and auto-expanded", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.3.0",
    updateAvailable: true,
  });
  await mockReleasesEndpoint(page);
  await gotoApp(page);

  await page.locator("button[title='Settings — update available']").click();

  // The v0.2.2 card (installed) should show the "installed" badge
  await expect(page.locator("span.font-medium", { hasText: /^installed$/ })).toBeVisible({ timeout: 5_000 });

  // And its body should already be expanded (auto-expanded for installed release)
  await expect(page.locator("text=Stability improvements")).toBeVisible();
});

test("release card expands on click and chevron rotates", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.3.0",
    updateAvailable: true,
  });
  await mockReleasesEndpoint(page);
  await gotoApp(page);

  await page.locator("button[title='Settings — update available']").click();
  await expect(page.locator("text=v0.3.0")).toBeVisible({ timeout: 5_000 });

  // v0.3.0 is not the installed version so it starts collapsed
  const card = page.locator("button", { hasText: "v0.3.0" }).first();
  await expect(card).toHaveAttribute("aria-expanded", "false");

  // Click to expand
  await card.click();
  await expect(card).toHaveAttribute("aria-expanded", "true", { timeout: 3_000 });

  // Click again to collapse
  await card.click();
  await expect(card).toHaveAttribute("aria-expanded", "false", { timeout: 3_000 });
});

// ---------------------------------------------------------------------------
// Airgapped / empty releases
// ---------------------------------------------------------------------------

test("About tab shows empty-state message when releases unavailable", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.2.2",
    updateAvailable: false,
  });
  await mockReleasesEndpoint(page, []); // empty — simulates airgapped / GitHub down
  await gotoApp(page);

  await page.locator("button[title='Settings']").click();
  await page.locator("button", { hasText: "About" }).click();

  await expect(
    page.locator("text=Could not load release notes")
  ).toBeVisible({ timeout: 5_000 });
});

test("About tab shows latest_version unavailable when airgapped", async ({ page }) => {
  // Simulate airgapped: version endpoint returns null latest
  await page.route("/api/version", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        current_version: "0.2.2",
        latest_version: null,
        update_available: false,
      }),
    })
  );
  await mockReleasesEndpoint(page, []);
  await gotoApp(page);

  await page.locator("button[title='Settings']").click();
  await page.locator("button", { hasText: "About" }).click();

  await expect(page.locator("text=unavailable")).toBeVisible({ timeout: 5_000 });
});

// ---------------------------------------------------------------------------
// Refresh button
// ---------------------------------------------------------------------------

test("refresh button re-fetches version info", async ({ page }) => {
  let callCount = 0;
  await page.route("/api/version", (route) => {
    callCount++;
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        current_version: "0.2.2",
        latest_version: "0.2.2",
        update_available: false,
      }),
    });
  });
  await mockReleasesEndpoint(page);
  await gotoApp(page);

  await page.locator("button[title='Settings']").click();
  await page.locator("button", { hasText: "About" }).click();

  const countBefore = callCount;
  await page.locator("button[title='Check for updates']").click();

  // Wait for the re-fetch to complete
  await page.waitForResponse("/api/version");
  expect(callCount).toBeGreaterThan(countBefore);
});

// ---------------------------------------------------------------------------
// About is the first nav item
// ---------------------------------------------------------------------------

test("About is the first item in the Settings nav", async ({ page }) => {
  await mockVersionEndpoint(page, {
    currentVersion: "0.2.2",
    latestVersion: "0.2.2",
    updateAvailable: false,
  });
  await gotoApp(page);

  await page.locator("button[title='Settings']").click();

  // Get all nav buttons inside the Settings nav
  const navButtons = page.locator("nav button");
  await expect(navButtons.first()).toContainText("About", { timeout: 5_000 });
});
