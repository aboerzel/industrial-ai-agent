// Test-harness-only machine reservation. The OS owns exclusivity and crash cleanup.
import net from "node:net";
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import path from "node:path";

export const RUNTIME_PORT = 46233;
export const BUSY_EXIT = 5;
export const REAL_MODEL_WORKERS = 1;
export const REAL_MODEL_RETRIES = 0;
const HERE = fileURLToPath(import.meta.url);

export class LocalRuntimeBusy extends Error {
  constructor() { super("LOCAL_RUNTIME_BUSY: another local real-model qualification owns the GPU runtime."); this.code = "LOCAL_RUNTIME_BUSY"; }
}

function line(socket) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => finish(new Error("Runtime reservation handshake failed")), 5000);
    const finish = (error, value) => {
      clearTimeout(timer); socket.off("data", data); socket.off("error", failed); socket.off("close", closed);
      error ? reject(error) : resolve(value);
    };
    const data = chunk => {
      buffer += chunk;
      if (buffer.length > 4096) return finish(new Error("Invalid reservation response"));
      if (buffer.includes("\n")) {
        try { finish(null, JSON.parse(buffer.split("\n")[0])); } catch (error) { finish(error); }
      }
    };
    const failed = error => finish(error);
    const closed = () => finish(new Error("Runtime reservation closed"));
    socket.on("data", data); socket.once("error", failed); socket.once("close", closed);
  });
}

export async function startBroker({ port = RUNTIME_PORT, drainMs = 90_000 } = {}) {
  const token = randomBytes(24).toString("hex");
  let owner = true, worker = null, draining = false;
  const server = net.createServer(socket => {
    let granted = false, released = false, buffer = "";
    socket.setTimeout(5000, () => socket.destroy());
    socket.on("data", chunk => {
      buffer += chunk;
      if (buffer.length > 4096) return socket.destroy();
      while (buffer.includes("\n")) {
        const index = buffer.indexOf("\n"), raw = buffer.slice(0, index);
        buffer = buffer.slice(index + 1);
        let request;
        try { request = JSON.parse(raw); } catch { return socket.destroy(); }
        if (!granted) {
          if (!owner || worker || draining || request.token !== token) {
            socket.end(JSON.stringify({ status: "LOCAL_RUNTIME_BUSY" }) + "\n"); return;
          }
          granted = true; worker = socket; socket.setTimeout(0);
          socket.write(JSON.stringify({ status: "ACQUIRED" }) + "\n");
        } else if (request.release === true) {
          released = true; socket.end();
        }
      }
    });
    socket.on("error", () => {});
    socket.on("close", () => {
      if (worker === socket) {
        worker = null;
        if (!released) {
          // A killed browser may leave an API run active for its existing 90 s
          // deadline. Preserve the reservation through this bounded drain.
          draining = true;
          setTimeout(() => { draining = false; finish(); }, drainMs);
        }
      }
      finish();
    });
  });
  function finish() { if (!owner && !worker && !draining) server.close(); }
  try { server.listen({ host: "127.0.0.1", port, exclusive: true }); await once(server, "listening"); }
  catch (error) { server.close(); if (error.code === "EADDRINUSE") throw new LocalRuntimeBusy(); throw error; }
  return {
    lease: { port: server.address().port, token },
    release() { owner = false; finish(); },
    closed: once(server, "close"),
  };
}

export async function softwareFixture(env = process.env) {
  if (env.E2E_EXECUTION_MODE !== "SOFTWARE_DETERMINISTIC") return false;
  const url = new URL(env.E2E_FRONTEND_URL);
  if (!["127.0.0.1", "localhost"].includes(url.hostname) || !env.RELEASE_SOFTWARE_TOKEN) throw new Error("Unverified software fixture");
  const response = await fetch(new URL("/__release_fixture__", url), {
    headers: { "X-Release-Fixture": env.RELEASE_SOFTWARE_TOKEN }, redirect: "error", signal: AbortSignal.timeout(5000),
  });
  if (!response.ok || (await response.json()).mode !== "SOFTWARE_DETERMINISTIC") throw new Error("Unverified software fixture");
  return true;
}

export async function withReservation(operation, { env = process.env, port = RUNTIME_PORT } = {}) {
  if (await softwareFixture(env)) return operation(env);
  if (env.LOCAL_RUNTIME_LEASE) return operation(env);
  const broker = spawn(process.execPath, [HERE, "--broker", String(port)], { stdio: ["pipe", "pipe", "inherit"] });
  broker.stdin.on("error", () => {});
  let result;
  try {
    const status = await line(broker.stdout);
    if (status.status === "LOCAL_RUNTIME_BUSY") throw new LocalRuntimeBusy();
    if (status.status !== "READY") throw new Error("Runtime reservation failed");
    result = await operation({ ...env, LOCAL_RUNTIME_LEASE: JSON.stringify(status.lease) });
  } finally {
    const exited = broker.exitCode === null ? once(broker, "exit") : null;
    broker.stdin.end();
    if (exited) await exited;
  }
  return result;
}

export async function withRuntimeWorker(operation, options = {}) {
  return withReservation(async env => {
    if (await softwareFixture(env)) return operation(env);
    const lease = JSON.parse(env.LOCAL_RUNTIME_LEASE);
    if (lease.port !== RUNTIME_PORT && !options.port) throw new Error("Invalid runtime reservation port");
    const socket = net.createConnection({ host: "127.0.0.1", port: lease.port });
    socket.on("error", () => {});
    let acquired = false, completed = false;
    try {
      const ready = line(socket);
      socket.write(JSON.stringify({ token: lease.token }) + "\n");
      if ((await ready).status !== "ACQUIRED") throw new LocalRuntimeBusy();
      acquired = true;
      const result = await operation(env);
      completed = true;
      return result;
    } finally {
      if (!socket.destroyed) {
        const closed = once(socket, "close");
        if (acquired && completed) socket.end(JSON.stringify({ release: true }) + "\n");
        else socket.destroy();
        await closed;
      }
    }
  }, options);
}

if (process.argv[1] && path.resolve(process.argv[1]) === HERE && process.argv[2] === "--broker") {
  try {
    const broker = await startBroker({ port: Number(process.argv[3]) });
    // Console cancellation may reach the entire process group. Keep the broker
    // alive until inherited workers and their existing API deadline have drained.
    process.on("SIGINT", () => broker.release());
    process.on("SIGTERM", () => broker.release());
    process.stdin.resume(); process.stdin.once("end", () => broker.release());
    console.log(JSON.stringify({ status: "READY", lease: broker.lease }));
    await broker.closed;
    process.stdin.destroy();
  } catch (error) {
    if (!(error instanceof LocalRuntimeBusy)) throw error;
    console.log(JSON.stringify({ status: "LOCAL_RUNTIME_BUSY" })); process.exitCode = BUSY_EXIT;
  }
}
