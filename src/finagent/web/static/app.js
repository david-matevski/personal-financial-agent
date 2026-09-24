import { getToken, setToken, clearToken } from "./js/auth.js";
import { getApiInfo, AuthError, ServerNotConfiguredError } from "./js/api.js";
import { el, clear } from "./js/dom.js";
import * as uploadView from "./js/views/upload.js";
import * as statementsView from "./js/views/statements.js";
import * as transactionsView from "./js/views/transactions.js";
import * as accountsView from "./js/views/accounts.js";

const header = document.querySelector(".app-header");
const main = document.getElementById("main");
const signOutBtn = document.getElementById("sign-out-btn");
const versionLabel = document.getElementById("api-version-label");
const connectTemplate = document.getElementById("tpl-connect");

const ROUTES = {
  upload: { title: "Upload", mount: (root) => uploadView.render(root) },
  statements: { title: "Statements", mount: (root, params) => statementsView.render(root, params) },
  transactions: { title: "Transactions", mount: (root) => transactionsView.render(root) },
  accounts: { title: "Accounts", mount: (root) => accountsView.render(root) },
};

function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [routeName, idPart] = raw.split("/").filter(Boolean);
  return { routeName: routeName || "upload", idPart };
}

function setActiveNav(routeName) {
  for (const link of header.querySelectorAll(".app-nav a")) {
    link.classList.toggle("is-active", link.dataset.route === routeName);
  }
}

function showServerNotConfigured(message) {
  header.hidden = true;
  clear(main);
  main.appendChild(
    el("div", { class: "banner banner--danger", role: "alert" }, [
      el("strong", { text: "Server has no API token configured. " }),
      el("span", { text: message || "Set the API token on the server and reload." }),
    ])
  );
}

function showConnectScreen(message) {
  header.hidden = true;
  clear(main);
  const fragment = connectTemplate.content.cloneNode(true);
  main.appendChild(fragment);
  const form = document.getElementById("connect-form");
  const input = document.getElementById("token-input");
  const errorBox = document.getElementById("connect-error");
  if (message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = input.value.trim();
    if (!value) return;
    setToken(value);
    startApp();
  });
  input.focus();
}

// Each navigation renders into its own container. Views finish async work
// after the user may have navigated away; writing into a detached container
// keeps a stale view from appending itself to the current page.
let currentContainer = null;

async function mountRoute() {
  const { routeName, idPart } = parseHash();
  const route = ROUTES[routeName] || ROUTES.upload;
  setActiveNav(routeName in ROUTES ? routeName : "upload");
  const container = el("div", { class: "route" });
  currentContainer = container;
  clear(main);
  main.appendChild(container);
  try {
    await route.mount(container, { statementId: idPart ? Number(idPart) : undefined });
  } catch (err) {
    if (container !== currentContainer) return;
    if (err instanceof AuthError) {
      clearToken();
      showConnectScreen("That token was rejected. Enter a valid API token.");
      return;
    }
    if (err instanceof ServerNotConfiguredError) {
      showServerNotConfigured(err.message);
      return;
    }
    clear(container);
    container.appendChild(el("p", { class: "form-error", role: "alert", text: err.message || "Something went wrong." }));
  }
}

async function loadFooterVersion() {
  try {
    const info = await getApiInfo();
    versionLabel.textContent = `${info.name} v${info.version}`;
  } catch {
    versionLabel.textContent = "";
  }
}

function startApp() {
  header.hidden = false;
  window.addEventListener("hashchange", mountRoute);
  mountRoute();
}

signOutBtn.addEventListener("click", () => {
  clearToken();
  window.removeEventListener("hashchange", mountRoute);
  showConnectScreen();
});

async function init() {
  header.hidden = true;
  loadFooterVersion();
  const token = getToken();
  if (!token) {
    showConnectScreen();
    return;
  }
  startApp();
}

init();
