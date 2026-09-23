import { el, clear } from "../dom.js";
import * as api from "../api.js";

export async function render(root) {
  const view = el("div", { class: "view view-accounts" });
  view.appendChild(el("div", { class: "view-heading" }, [el("h1", { text: "Accounts" })]));

  const container = el("div");
  container.appendChild(el("p", { class: "empty-state", text: "Loading accounts…" }));
  view.appendChild(container);
  root.appendChild(view);

  let accounts = [];
  try {
    accounts = await api.listAccounts();
  } catch (err) {
    clear(container);
    container.appendChild(el("p", { class: "form-error", text: err.message }));
    return;
  }

  clear(container);
  if (!accounts.length) {
    container.appendChild(
      el("p", { class: "empty-state", text: "No accounts yet: they appear once a statement is imported." })
    );
    return;
  }

  const grid = el("div", { class: "account-grid" });
  for (const account of accounts) {
    grid.appendChild(
      el("div", { class: "card account-card" }, [
        el("h3", { text: account.label || account.account_name || `Account #${account.id}` }),
        el("p", { text: `${account.issuer}${account.account_last4 ? " •" + account.account_last4 : ""}` }),
        el("p", { text: account.account_type || "—" }),
        el("p", { text: account.currency || "—" }),
      ])
    );
  }
  container.appendChild(grid);
}
