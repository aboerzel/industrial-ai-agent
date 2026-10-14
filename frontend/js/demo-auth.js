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
  if (!response.ok) throw new Error(response.status === 401 ? "Demo login required or credentials incorrect." : "Demo session request failed.");
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
    indicator.textContent = demoEnabled === null || busy ? text.connecting : currentUser?.username
      ?? (demoEnabled ? text.loggedOut : text.disabled);
    account.disabled = busy || demoEnabled !== true;
    account.setAttribute("aria-label", `Account: ${indicator.textContent}`);
    document.querySelector("#account-username").textContent = currentUser?.username ?? text.selectUser;
    document.querySelector("#account-clearance").textContent = currentUser?.clearance ?? "";
    document.querySelector("#account-roles").textContent = currentUser?.roles.join(", ") || text.none;
    document.querySelector("#account-permissions").hidden = !currentUser;
    logout.hidden = !currentUser;
    logout.disabled = busy;
    switchButton.hidden = !currentUser;
    switchButton.disabled = busy;
    chooser.replaceChildren(...users.map((user) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button demo-user-option";
      button.dataset.demoUsername = user.username;
      button.setAttribute("aria-current", String(currentUser?.username === user.username));
      button.disabled = busy;
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
    showUsers(demoEnabled === true && !currentUser && !busy);
    openPanel(demoEnabled === true && !currentUser && !busy);
    onChanged(currentUser);
  }

  async function transition(path, payload) {
    if (busy || demoEnabled !== true) return;
    busy = true;
    // Purge before the server mutation; failed switching never restores old data.
    invalidateSecurityContext("identity");
    display(null);
    try {
      await authRequest(path, payload);
      display(path === "logout" ? null : await authRequest("me"));
      sessionNotifications?.postMessage("demo-session-changed");
    }
    catch (error) { if (!(error instanceof SecurityContextChangedError)) onError(error); }
    finally {
      busy = false;
      display(currentUser);
    }
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
    display(null);
  });

  async function initialize(restore = false) {
    try {
      const config = await authRequest("config");
      demoEnabled = config.demo_mode === true;
      if (!config.demo_mode) {
        users = [];
        display(null);
        return;
      }
      if (!Array.isArray(config.users) || !config.users.every(validUser)) throw new Error("Invalid demo identity metadata.");
      users = config.users;
      display(await authRequest(restore ? "me" : "bootstrap", restore ? undefined : {}));
    } catch (error) {
      display(null);
      if (!(error instanceof SecurityContextChangedError)) onError(error);
    }
  }
  display(null);
  function connectNotifications() {
    if (!window.BroadcastChannel || sessionNotifications) return;
    sessionNotifications = new window.BroadcastChannel("industrial-demo-session");
    sessionNotifications.onmessage = () => {
      invalidateSecurityContext("identity");
      void initialize(true);
    };
  }
  connectNotifications();
  window.addEventListener("pagehide", () => {
    sessionNotifications?.close();
    sessionNotifications = null;
  });
  window.addEventListener("pageshow", connectNotifications);
  return { initialize, refreshLabels: render };
}
