import { withRuntimeWorker, REAL_MODEL_WORKERS, REAL_MODEL_RETRIES } from "./local-runtime-lock.mjs";

export default async function runtimeSetup(config) {
  const real = config.configFile.endsWith("playwright.config.mjs") || Boolean(process.env.REFERENCE_LIVE_URL);
  if (!real) return;
  if (config.workers !== REAL_MODEL_WORKERS || config.projects.some(project => project.retries !== REAL_MODEL_RETRIES)) {
    throw new Error("Real-model qualification requires workers=1 and retries=0");
  }
  let release, entered;
  const active = new Promise(resolve => { entered = resolve; });
  const done = new Promise(resolve => { release = resolve; });
  const running = withRuntimeWorker(async () => { entered(); await done; });
  await Promise.race([active, running]);
  return async () => { release(); await running; };
}
