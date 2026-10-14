import { demoUsers } from "./demo-auth-fake.mjs";
let demoUser = demoUsers[0];
// No requests leave this process. Only readiness/configuration reads are supported.
globalThis.fetch = async (url, options = {}) => {
  const parsed = new URL(url);
  const authorization = new Headers(options.headers).get("Authorization");
  if (parsed.port === "8080") {
    if (parsed.pathname === "/api/v1/auth/switch") {
      const status = Number(process.env.FINDING9_DEMO_AUTH_STATUS ?? 200);
      if (status !== 200) return Response.json({ detail: "Demo session unavailable." }, { status });
      demoUser = demoUsers.find((user) => user.username === JSON.parse(options.body).username);
      return Response.json(demoUser, { headers: { "set-cookie": "industrial_demo_session=synthetic; HttpOnly; SameSite=Strict; Path=/api/" } });
    }
    if (parsed.pathname === "/api/v1/auth/me") return Response.json(demoUser);
    if (parsed.pathname === "/api/v1/auth/logout") return Response.json({ logged_out: true });
    return new Response("fixture frontend", { status: 200 });
  }  if (parsed.pathname.startsWith("/api/v1/")) {
    const status = authorization === "Bearer fixture-admin-token"
      ? Number(process.env.FINDING9_API_STATUS ?? 200) : 401;
    if (status !== 200) return new Response("not JSON; credentials must not be reported", { status });
    const payload = parsed.pathname === "/api/v1/models"
      ? [{ model_id: "local_quality", provider: "ollama", provider_model: "qwen3.5:9b", execution_zone: "LOCAL" }]
      : ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].map((classification) => ({
        consumer_id: "agent", data_classification: classification, model_id: "local_quality",
      }));
    return Response.json(payload);
  }
  if (parsed.pathname === "/api/tags") return Response.json({ models: [{ name: "qwen3.5:9b" }] });
  if (parsed.pathname === "/mcp") {
    const payload = JSON.parse(options.body);
    if (!payload.id) return new Response(null, { status: 202 });
    return Response.json({ jsonrpc: "2.0", id: payload.id, result: payload.method === "initialize"
      ? { protocolVersion: "2025-06-18" }
      : { tools: ["get_machine_status", "get_product_history", "search_documentation"].map((name) => ({ name })) },
    }, { headers: { "mcp-session-id": "fixture-session" } });
  }
  throw new Error("Unexpected fixture request; network disabled.");
};
