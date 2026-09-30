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
