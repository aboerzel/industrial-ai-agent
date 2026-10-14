import { readFileSync } from "node:fs";

// Test-only projection of the canonical config, never an independent role mapping.
export const demoUsers = readFileSync(new URL("../../../config/demo-users.toml", import.meta.url), "utf8")
  .split("[[users]]").slice(1).map((block) => ({
    username: /username = "([^"]+)"/.exec(block)[1],
    clearance: /clearance = "([^"]+)"/.exec(block)[1],
    roles: /roles = \[(.*?)\]/.exec(block)[1].match(/\w+/g) ?? [],
  }));

export function demoAuthFetch(fallback, username = "demo-public") {
  let user = demoUsers.find((entry) => entry.username === username);
  return async (url, options = {}) => {
    if (!String(url).startsWith("/api/v1/auth/")) return fallback(url, options);
    const route = String(url).split("/").at(-1);
    const data = options.body ? JSON.parse(options.body) : {};
    let result;
    let status = 200;
    if (route === "config") result = { demo_mode: true, users: demoUsers };
    else if (route === "logout") { user = null; result = { logged_out: true }; }
    else if (route === "switch" || route === "login") {
      const next = demoUsers.find((entry) => entry.username === data.username);
      if (!next || (route === "login" && data.password !== next.username)) status = 401;
      else user = next;
      result = user;
    } else result = user;
    if (!result) status = 401;
    return new Response(JSON.stringify(result ?? { detail: "Demo session required." }), {
      status, headers: { "Content-Type": "application/json" },
    });
  };
}

const sessions = new Map();
let nextSession = 0;

export function demoHttpUser(request) {
  const token = /industrial_demo_session=([^;]+)/.exec(request.headers.cookie ?? "")?.[1];
  return sessions.get(token);
}

export async function demoHttpAuth(request, response, url) {
  if (!url.pathname.startsWith("/api/v1/auth/")) return false;
  const route = url.pathname.split("/").at(-1);
  let payload = {};
  if (request.method === "POST") {
    let raw = "";
    for await (const chunk of request) raw += chunk;
    payload = JSON.parse(raw || "{}");
  }
  let user = demoHttpUser(request);
  let result;
  let status = 200;
  if (route === "config") result = { demo_mode: true, users: demoUsers };
  else if (route === "me") { result = user; if (!user) status = 401; }
  else if (route === "logout") {
    user = null;
    result = { logged_out: true };
    response.setHeader("Set-Cookie", "industrial_demo_session=logged-out; HttpOnly; SameSite=Strict; Path=/api/");
  } else {
    const username = route === "bootstrap" ? user?.username ?? "demo-public" : payload.username;
    user = demoUsers.find((entry) => entry.username === username);
    if (!user || (route === "login" && payload.password !== user.username)) { status = 401; result = { detail: "Demo login failed." }; }
    else {
      const token = `synthetic-session-${++nextSession}`;
      sessions.set(token, user);
      response.setHeader("Set-Cookie", `industrial_demo_session=${token}; HttpOnly; SameSite=Strict; Path=/api/`);
      result = user;
    }
  }
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(result ?? { detail: "Demo session required." }));
  return true;
}
