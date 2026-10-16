import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";

export async function referenceCases({ extended = false } = {}) {
  const cases = JSON.parse(await readFile(new URL("./fixtures/reference-actions-review.json", import.meta.url), "utf8"));
  if (extended) {
    for (const language of ["DE", "EN"]) {
      for (const [username, value] of [["demo-public", "P4101"], ["demo-confidential", "P4711"], ["demo-restricted", "P9001"]]) {
        for (const label of language === "DE" ? ["Produkt untersuchen", "Produkthistorie anzeigen"] : ["Investigate product", "Show product history"]) {
          cases.push({ username, value, type: "product", language, label });
        }
      }
      cases.push({ username: "demo-confidential", value: "MT-S02-20260117", type: "maintenance_ticket", language, label: language === "DE" ? "Ticket prüfen" : "Inspect ticket" });
    }
  }
  const source = await readFile(new URL("../frontend/js/app.js", import.meta.url), "utf8");
  const start = source.indexOf("function identifierActions(");
  const end = source.indexOf("\nasync function copyIdentifier", start);
  if (start < 0 || end < 0) throw new Error("Reference action implementation is missing");
  const actions = vm.runInNewContext(`(${source.slice(start, end)})`);
  return cases.map((item, index) => {
    const action = actions(item, item.language).find(a => a.label === item.label);
    if (!action?.prompt) throw new Error(`Missing supported reference action: ${item.label}`);
    const tool = item.type === "station" ? (item.username === "demo-public" ? "get_station_overview" : "get_machine_status")
      : item.type === "product" ? (/histor/i.test(item.label) ? "get_product_history" : "get_product_overview")
        : item.type === "error_code" ? "search_documentation" : "get_maintenance_ticket";
    const argument = { station: "station_id", product: "product_id", error_code: "query", maintenance_ticket: "ticket_id" }[item.type];
    return { ...item, index: index + 1, original_prompt: item.prompt ?? null, prompt: action.prompt, tool, argument };
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(JSON.stringify(await referenceCases({ extended: process.argv.includes("--extended") })));
}
