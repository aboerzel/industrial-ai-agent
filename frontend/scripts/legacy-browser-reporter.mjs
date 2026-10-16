import { writeFile } from "node:fs/promises";
import path from "node:path";
import { legacyJourneyNames, summarizeLegacyJourneys } from "./legacy-browser-contract.mjs";

export default class LegacyBrowserReporter {
  constructor(options) { this.directory = options.directory; this.journeys = new Map(); }
  onBegin(_config, suite) {
    for (const title of legacyJourneyNames) this.journeys.set(title, { journey: title, result: "NOT_RUN", assertions: [], steps: [] });
    for (const test of suite.allTests()) this.journeys.set(test.title, { journey: test.title, result: "NOT_RUN", assertions: [], steps: [] });
  }
  onTestEnd(test, result) {
    const attachment = result.attachments.find(item => item.name === "legacy-journey");
    const evidence = attachment?.body ? JSON.parse(attachment.body.toString()) : null;
    this.journeys.set(test.title, evidence ?? {
      journey: test.title, result: result.status === "skipped" ? "BLOCKED" : "HARNESS_ERROR", assertions: [], steps: [],
    });
  }
  async onEnd(result) {
    const report = summarizeLegacyJourneys([...this.journeys.values()]);
    if (result.status !== "passed") report.execution_status = "FAIL";
    await writeFile(path.join(this.directory, "journeys.json"), `${JSON.stringify(report, null, 2)}\n`, { flag: "wx" });
  }
}
