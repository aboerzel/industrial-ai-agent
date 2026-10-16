const labels = new Set(["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]);

export function sanitizedHttpBody(body) {
  const code = body?.code ?? body?.error?.code;
  return {
    error_code: typeof code === "string" && /^[a-z_]{1,80}$/i.test(code) ? code : null,
    terminal_status: ["running", "waiting_for_approval", "success", "failed", "limit_reached"].includes(body?.status) ? body.status : null,
    data_classification: labels.has(body?.data_classification) ? body.data_classification : null,
    username: /^demo-(public|internal|confidential|restricted|admin)$/.test(body?.username ?? "") ? body.username : null,
  };
}

export function classifyHttpResponse(status, code) {
  if (status === 401) return "AUTHENTICATION_FAILURE";
  if (status === 404 && ["requested_data_unavailable", "diagnostic_target_unavailable"].includes(code)) return "AUTHORIZATION_NEUTRAL_DENIAL";
  if (status === 404) return "MISSING_RESOURCE";
  return null;
}

export function createJourneyHttpTrace(context) {
  const rows = [], pending = [];
  async function capture(method, url, headers, status, body, redirected, source) {
    const parsed = new URL(url);
    const metadata = sanitizedHttpBody(body);
    rows.push({ method, path: parsed.pathname, origin: parsed.origin, source,
      expected_auth: parsed.pathname === "/api/v1/auth/bootstrap" ? "demo bootstrap" : parsed.pathname.startsWith("/api/") ? "demo session cookie" : "static",
      cookies_present: Boolean(new Headers(headers).get("cookie")),
      authorization_present: Boolean(new Headers(headers).get("authorization")),
      status, redirected, ...metadata, classification: classifyHttpResponse(status, metadata.error_code) });
  }
  context.on("response", response => {
    const operation = (async () => {
      const request = response.request();
      const body = new URL(response.url()).pathname.startsWith("/api/") ? await response.json().catch(() => null) : null;
      await capture(request.method(), request.url(), await request.allHeaders(), response.status(), body, Boolean(request.redirectedFrom()), "browser");
    })().catch(() => undefined);
    pending.push(operation);
  });
  const original = context.request.fetch.bind(context.request);
  context.request.fetch = async (url, options = {}) => {
    const cookies = await context.cookies(String(url));
    const response = await original(url, options);
    const headers = new Headers(options.headers);
    if (cookies.length) headers.set("cookie", "present");
    await capture(options.method ?? "GET", String(url), headers, response.status(), await response.json().catch(() => null), response.url() !== String(url), "browser-request-context");
    return response;
  };
  return { rows, async flush() { await Promise.all(pending); }, close() { context.request.fetch = original; } };
}
