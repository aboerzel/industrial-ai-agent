import { defineConfig } from "@playwright/test";
import { browserCredentials, modelAdminHeaders } from "./scripts/e2e-http.mjs";

await modelAdminHeaders();
const frontendUrl = process.env.E2E_FRONTEND_URL ?? "http://127.0.0.1:8080";

export default defineConfig({
  testDir: "../tests/e2e",
  testIgnore: "**/fixtures/**",
  fullyParallel: false,
  timeout: 180_000,
  expect: { timeout: 180_000 },
  use: {
    baseURL: frontendUrl,
    httpCredentials: await browserCredentials(frontendUrl),
    trace: "off",
  },
  reporter: [["list"], ["json", { outputFile: "../evals/results/browser-e2e-results.json" }]],
});
