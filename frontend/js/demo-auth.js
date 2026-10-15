import { getSecurityContextGeneration, getSecurityContextSignal, invalidateSecurityContext, isCurrentSecurityContext, SecurityContextChangedError } from "./api.js?v=20261013-2";

let currentUser = null;
export const getCurrentUser = () => currentUser;

export async function authRequest(path, payload) {
  const generation = getSecurityContextGeneration();
  const response = await fetch(`/api/v1/auth/${path}`, {
    method: payload === undefined ? "GET" : "POST",
    credentials: "same-origin", cache: "no-store",
    signal: getSecurityContextSignal(),
    headers: { "Content-Type": "application/json", "X-Demo-Session": "1" },
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  });
  const body = await response.json();
  if (!isCurrentSecurityContext(generation)) throw new SecurityContextChangedError();
  if (!response.ok) {
    const error = new Error(response.status === 401 ? "Demo login required or credentials incorrect." : "Demo session request failed.");
    error.status = response.status;
    throw error;
  }
  return body;
}

function validUser(user) {
  return user && typeof user.username === "string"
    && ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"].includes(user.clearance)
    && Array.isArray(user.roles) && user.roles.every((role) => role === "MODEL_ADMIN")
    && Object.keys(user).every((key) => ["username", "clearance", "roles"].includes(key));
}

export function mountDemoAuth({ onChanged, onError }) {
  const indicator = document.querySelector("#current-user");
  const area = document.querySelector(".account-area");
  const account = document.querySelector("#account-button");
  const panel = document.querySelector("#account-panel");
  const chooser = document.querySelector("#demo-user-list");
  const switchButton = document.querySelector("#switch-user-button");
  const language = document.querySelector("#response-language");
  const logout = document.querySelector("#logout-button");
  const adminButton = document.querySelector("#model-configuration-button");
  let busy = false;
  let demoEnabled = null;
  let sessionNotifications = null;
  let authRevision = 0;
  const pendingMutations = new Set();
  const completedMutations = new Set();
  const blocked = () => busy || pendingMutations.size > 0;
  let users = [];
  currentUser = null;

  const labels = {
    EN: { configuration: "Configuration", clearance: "Clearance", roles: "Roles", language: "Language", switchUser: "Switch user", selectUser: "Select demo user", logout: "Logout", none: "None", loggedOut: "Select demo user", connecting: "Connecting…", disabled: "Demo authentication disabled", permission: "Requires MODEL_ADMIN permission." },
    DE: { configuration: "Konfiguration", clearance: "Freigabestufe", roles: "Rollen", language: "Sprache", switchUser: "Benutzer wechseln", selectUser: "Demo-Benutzer auswählen", logout: "Abmelden", none: "Keine", loggedOut: "Demo-Benutzer auswählen", connecting: "Verbindung…", disabled: "Demo-Anmeldung deaktiviert", permission: "Erfordert die Berechtigung MODEL_ADMIN." },
  };

  function openPanel(open, focus = false) {
    panel.hidden = !open;
    account.setAttribute("aria-expanded", String(open));
    if (open && focus) (currentUser ? switchButton : chooser.querySelector("button"))?.focus();
  }

  function showUsers(show) {
    chooser.hidden = !show;
    document.querySelector("#demo-user-heading").hidden = !show;
    switchButton.setAttribute("aria-expanded", String(show));
  }

  function render() {
    const text = labels[language.value] ?? labels.EN;
    document.querySelectorAll("[data-account-text]").forEach((node) => {
      node.textContent = text[node.dataset.accountText];
    });
    indicator.textContent = demoEnabled === null || blocked() ? text.connecting : currentUser?.username
      ?? (demoEnabled ? text.loggedOut : text.disabled);
    account.disabled = blocked() || demoEnabled !== true;
    account.setAttribute("aria-label", `Account: ${indicator.textContent}`);
    document.querySelector("#account-username").textContent = currentUser?.username ?? text.selectUser;
    document.querySelector("#account-clearance").textContent = currentUser?.clearance ?? "";
    document.querySelector("#account-roles").textContent = currentUser?.roles.join(", ") || text.none;
    document.querySelector("#account-permissions").hidden = !currentUser;
    logout.hidden = !currentUser;
    logout.disabled = blocked();
    switchButton.hidden = !currentUser;
    switchButton.disabled = blocked();
    chooser.replaceChildren(...users.map((user) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button demo-user-option";
      button.dataset.demoUsername = user.username;
      button.setAttribute("aria-current", String(currentUser?.username === user.username));
      button.disabled = blocked();
      const username = document.createElement("span");
      username.textContent = user.username;
      const permissions = document.createElement("small");
      permissions.textContent = `${user.clearance}${user.roles.length ? ` · ${user.roles.join(", ")}` : ""}`;
      button.append(username, permissions);
      button.addEventListener("click", () => {
        if (currentUser?.username === user.username) { openPanel(false); return; }
        void transition("switch", { username: user.username });
      });
      return button;
    }));
    if (adminButton) {
      adminButton.disabled = !currentUser?.roles.includes("MODEL_ADMIN");
      adminButton.title = adminButton.disabled ? text.permission : text.configuration;
      adminButton.closest(".configuration-control")?.setAttribute("title", adminButton.title);
      document.querySelector("#configuration-permission").textContent = adminButton.disabled ? text.permission : "";
    }
  }

  function display(user) {
    currentUser = validUser(user) ? user : null;
    render();
    showUsers(demoEnabled === true && !currentUser && !blocked());
    openPanel(demoEnabled === true && !currentUser && !blocked());
    onChanged(currentUser);
  }

  async function transition(path, payload) {
    if (blocked() || demoEnabled !== true) return;
    if (["switch", "login"].includes(path) && !users.some(user => user.username === payload?.username)) return;
    busy = true;
    const operationId = window.crypto.randomUUID();
    pendingMutations.add(operationId);
    // Invalidation precedes dispatch: an unsuccessful transport may still mutate cookies.
    invalidateSecurityContext("identity");
    notify(operationId, "pending");
    let succeeded = false;
    try {
      await authRequest(path, payload);
      succeeded = true;
    }
    catch (error) { if (!(error instanceof SecurityContextChangedError)) onError(error); }
    finally {
      busy = false;
      finishMutation(operationId);
      // Never put identity refresh or response parsing ahead of shared invalidation.
      notify(operationId, "settled");
      display(null);
    }
    if (succeeded && path !== "logout" && !pendingMutations.size) await initialize(true);
  }

  function notify(operationId, phase) {
    // A dispatched mutation can settle after pagehide closed the owned channel.
    const channel = sessionNotifications ?? (window.BroadcastChannel
      ? new window.BroadcastChannel("industrial-demo-session") : null);
    try {
      channel?.postMessage({ type: "SESSION_INVALIDATED", operation_id: operationId, phase });
    } finally {
      if (channel !== sessionNotifications) channel?.close();
    }
  }

  function finishMutation(operationId) {
    pendingMutations.delete(operationId);
    completedMutations.add(operationId);
    if (completedMutations.size > 256) completedMutations.delete(completedMutations.values().next().value);
  }

  account.addEventListener("click", () => openPanel(panel.hidden));
  account.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") { event.preventDefault(); openPanel(true, true); }
  });
  switchButton.addEventListener("click", () => {
    showUsers(chooser.hidden);
    if (!chooser.hidden) chooser.querySelector("button")?.focus();
  });
  document.addEventListener("click", (event) => { if (!area.contains(event.target)) openPanel(false); });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) { openPanel(false); account.focus(); }
  });
  language.addEventListener("change", render);
  logout.addEventListener("click", () => void transition("logout", {}));

  window.addEventListener("securitycontextchange", () => {
    authRevision += 1;
    display(null);
  });

  async function initialize(restore = false) {
    const revision = ++authRevision;
    display(null);
    try {
      const config = await authRequest("config");
      if (revision !== authRevision) return;
      demoEnabled = config.demo_mode === true;
      if (!config.demo_mode) {
        users = [];
        display(null);
        return;
      }
      if (!Array.isArray(config.users) || !config.users.every(validUser)) throw new Error("Invalid demo identity metadata.");
      users = config.users;
      if (pendingMutations.size) return;
      let user;
      try {
        user = await authRequest("me");
      } catch (error) {
        if (!restore && error.status === 401 && revision === authRevision) {
          await transition("bootstrap", {});
          return;
        }
        throw error;
      }
      if (revision !== authRevision || pendingMutations.size) return;
      if (!validUser(user)) throw new Error("Invalid demo identity metadata.");
      display(user);
    } catch (error) {
      if (revision !== authRevision) return;
      display(null);
      if (!(error instanceof SecurityContextChangedError)) onError(error);
    }
  }
  display(null);
  function connectNotifications() {
    if (!window.BroadcastChannel || sessionNotifications) return;
    sessionNotifications = new window.BroadcastChannel("industrial-demo-session");
    sessionNotifications.onmessage = ({ data }) => {
      if (data?.type !== "SESSION_INVALIDATED" || typeof data.operation_id !== "string"
          || data.operation_id.length > 128 || !["pending", "settled"].includes(data.phase)
          || completedMutations.has(data.operation_id)) return;
      if (data.phase === "pending") {
        if (pendingMutations.has(data.operation_id)) return;
        pendingMutations.add(data.operation_id);
      } else {
        finishMutation(data.operation_id);
      }
      invalidateSecurityContext("identity");
      if (!blocked()) void initialize(true);
    };
  }
  connectNotifications();
  window.addEventListener("pagehide", () => {
    sessionNotifications?.close();
    sessionNotifications = null;
  });
  window.addEventListener("pageshow", (event) => {
    connectNotifications();
    // pagehide already purged protected state; completions may be missed while frozen.
    // The application's pageshow reconciliation reads the authoritative identity again.
    if (event.persisted) pendingMutations.clear();
  });
  return { initialize, refreshLabels: render };
}
