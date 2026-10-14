import http from "node:http";
import { readFile } from "node:fs/promises";
import { test, expect } from "../../../frontend/node_modules/@playwright/test/index.mjs";

test("active HTML document is published as an inert Blob before browser navigation", async ({ page }) => {
  const source = await readFile(new URL("../../../frontend/js/api.js", import.meta.url), "utf8");
  const server = http.createServer((request, response) => {
    if (request.url === "/api.js") {
      response.setHeader("Content-Type", "text/javascript");
      response.end(source);
    } else if (request.url.startsWith("/api/v1/documents/")) {
      response.setHeader("Content-Type", "text/html");
      response.end("<script>document.body.dataset.executed='synthetic';</script>");
    } else {
      response.setHeader("Content-Type", "text/html");
      response.end('<button id="open">Open</button><script type="module">import {openDocument} from "/api.js"; document.querySelector("#open").onclick=()=>openDocument("synthetic", "CONFIDENTIAL");</script>');
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    // Record the actual Blob MIME independently of browser download/popup behavior.
    await page.evaluate(() => {
      const original = URL.createObjectURL;
      URL.createObjectURL = (blob) => { window.publishedType = blob.type; return original(blob); };
      const originalOpen = window.open.bind(window);
      window.open = (url, ...args) => { window.publishedUrl = url; return originalOpen(url, ...args); };
    });
    await page.click("#open");
    await expect.poll(() => page.evaluate(() => window.publishedType)).toBe("application/octet-stream");
    expect(await page.evaluate(async () => (await fetch(window.publishedUrl)).headers.get("Content-Type"))).toBe("application/octet-stream");
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
