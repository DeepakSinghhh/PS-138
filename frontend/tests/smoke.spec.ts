import { expect, test } from "@playwright/test";

const shots = "../reports/screenshots";

test("overview renders the India network", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("India");
  await expect(page.locator(".leaflet-container")).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${shots}/01_overview.png`, fullPage: true });
});

test("optimizer streams a Pareto front and shows the recommended plan", async ({ page }) => {
  await page.goto("/optimize");
  await page.getByRole("button", { name: "Run optimization" }).click();
  await expect(page.getByText("Pareto-optimal plans ·")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole("heading", { name: "Recommended (balanced)" })).toBeVisible();
  await expect(page.getByText("Download decision report")).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${shots}/02_optimizer.png`, fullPage: true });
});

test("prediction page shows the speed-fuel curve", async ({ page }) => {
  await page.goto("/predict");
  await expect(page.getByText("Speed-fuel curve at these conditions")).toBeVisible();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${shots}/03_predict.png`, fullPage: true });
});

test("lab, compliance, benchmarks and methodology render", async ({ page }) => {
  await page.goto("/lab");
  await page.getByRole("button", { name: "Compute" }).click();
  await expect(page.getByText("saves money")).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: `${shots}/04_lab.png`, fullPage: true });
  await page.goto("/compliance");
  await expect(page.getByRole("heading", { name: "Regulatory compliance" })).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${shots}/05_compliance.png`, fullPage: true });
  await page.goto("/about");
  await expect(page.getByText("How the platform meets the delivery table")).toBeVisible();
  await page.goto("/benchmarks");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${shots}/06_benchmarks.png`, fullPage: true });
});

test("guided tour visits every step and runs the optimizer", async ({ page }) => {
  test.setTimeout(300_000);
  await page.goto("/");
  await page.getByRole("button", { name: "Take the 2-minute tour" }).click();
  const callout = page.locator(".tour-callout");
  for (let i = 1; i <= 10; i++) {
    await expect(callout).toContainText(`${i} / 10`);
    const next = callout.getByRole("button", { name: i === 10 ? "Finish" : "Next" });
    await expect(next).toBeEnabled({ timeout: 180_000 });
    await expect(page.locator(".tour-highlight")).toBeVisible();
    if (i === 5) await expect(page.getByText("Pareto-optimal plans ·")).toBeVisible();
    await next.click();
  }
  await expect(callout).toHaveCount(0);
});

test("QAOA circuit trains and offers the OpenQASM download", async ({ page }) => {
  await page.goto("/lab");
  await page.getByRole("button", { name: "Run QAOA" }).click();
  await expect(page.getByText("Best plan measured")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole("button", { name: "Download OpenQASM" })).toBeVisible();
});

test("a shared link opens the dashboard with its scenario", async ({ page }) => {
  const param = Buffer.from(JSON.stringify({ year: 2040, bogus: 1 })).toString("base64url");
  await page.goto(`/?s=${param}`);
  await expect(page.getByText("Scenario overview · 2040")).toBeVisible();
});

test("two saved plans can be compared side by side", async ({ page }) => {
  await page.goto("/optimize");
  await page.getByRole("button", { name: "Run optimization" }).click();
  await expect(page.getByText("Pareto-optimal plans ·")).toBeVisible({ timeout: 120_000 });
  await page.getByRole("button", { name: "Save plan" }).click();
  await page.getByRole("button", { name: "Minimum cost", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Minimum cost" })).toBeVisible();
  await page.getByRole("button", { name: "Save plan" }).click();
  await page.getByRole("link", { name: "Compare plans", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Side by side" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Route by route" })).toBeVisible();
  await expect(page.getByText(/services differ/)).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${shots}/07_compare.png`, fullPage: true });
});
