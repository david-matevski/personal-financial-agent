import { el, clear, badge } from "../dom.js";
import { formatDate, formatDateTime, formatMoney } from "../format.js";
import * as api from "../api.js";

function statusBadge(status) {
  if (status === "VERIFIED") return badge("Verified", "ok");
  if (status === "UNVERIFIED") return badge("Unverified", "warn");
  if (status === "FAILED") return badge("Failed", "danger");
  return badge(status || "Unknown", "neutral");
}

function accountLabel(accountsById, accountId) {
  const account = accountsById.get(accountId);
  if (!account) return `Account #${accountId}`;
  return account.label || account.account_name || `${account.issuer} •${account.account_last4 ?? ""}`;
}

function renderDetail(container, statement, accountsById) {
  clear(container);
  const panel = el("div", { class: "card detail-panel" });
  const closeBtn = el("button", { type: "button", class: "btn btn--ghost close-detail", text: "Close" });
  closeBtn.addEventListener("click", () => {
    container.hidden = true;
    clear(container);
  });
  panel.appendChild(closeBtn);
  panel.appendChild(el("h2", { text: statement.filename }));

  const dl = el("dl");
  const rows = [
    ["Account", accountLabel(accountsById, statement.account_id)],
    ["Status", statement.status],
    ["Attempts", String(statement.attempts ?? 0)],
    ["Period", `${formatDate(statement.period_start)} – ${formatDate(statement.period_end)}`],
    ["Opening balance", statement.opening_balance != null ? formatMoney(statement.opening_balance, "CAD") : "—"],
    ["Closing balance", statement.closing_balance != null ? formatMoney(statement.closing_balance, "CAD") : "—"],
    ["Total money out", statement.total_money_out != null ? formatMoney(statement.total_money_out, "CAD") : "—"],
    ["Total money in", statement.total_money_in != null ? formatMoney(statement.total_money_in, "CAD") : "—"],
    ["Transactions inserted", String(statement.transactions_inserted ?? 0)],
    ["Model", statement.model || "—"],
    ["Uploaded", formatDateTime(statement.created_at)],
  ];
  for (const [term, value] of rows) {
    dl.appendChild(el("dt", { text: term }));
    dl.appendChild(el("dd", { text: value }));
  }
  panel.appendChild(dl);

  if (statement.problems && statement.problems.length) {
    panel.appendChild(el("h3", { text: "Problems" }));
    const list = el("ul", { class: "problems-list" });
    for (const problem of statement.problems) {
      list.appendChild(el("li", { text: problem }));
    }
    panel.appendChild(list);
  }

  container.hidden = false;
  container.appendChild(panel);
  container.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

export async function render(root, { statementId } = {}) {
  const view = el("div", { class: "view view-statements" });
  view.appendChild(el("div", { class: "view-heading" }, [el("h1", { text: "Statements" })]));

  const detailContainer = el("div");
  detailContainer.hidden = true;
  const tableContainer = el("div");

  view.appendChild(detailContainer);
  view.appendChild(tableContainer);
  root.appendChild(view);

  clear(tableContainer);
  tableContainer.appendChild(el("p", { class: "empty-state", text: "Loading statements…" }));

  let statements = [];
  let accounts = [];
  try {
    [statements, accounts] = await Promise.all([api.listStatements(50, 0), api.listAccounts()]);
  } catch (err) {
    clear(tableContainer);
    tableContainer.appendChild(el("p", { class: "form-error", text: err.message }));
    return;
  }

  const accountsById = new Map(accounts.map((a) => [a.id, a]));

  clear(tableContainer);
  if (!statements.length) {
    tableContainer.appendChild(
      el("p", { class: "empty-state", text: "No statements yet: upload one on the Upload tab." })
    );
    return;
  }

  const wrap = el("div", { class: "table-scroll" });
  const table = el("table");
  const thead = el("thead", {}, [
    el("tr", {}, [
      el("th", { text: "Filename" }),
      el("th", { text: "Account" }),
      el("th", { text: "Period" }),
      el("th", { text: "Status" }),
      el("th", { text: "Transactions" }),
      el("th", { text: "Uploaded" }),
    ]),
  ]);
  const tbody = el("tbody");
  for (const statement of statements) {
    const row = el("tr", { class: "is-clickable", tabindex: "0", role: "button" }, [
      el("td", { class: "filename-cell", text: statement.filename }),
      el("td", { text: accountLabel(accountsById, statement.account_id) }),
      el("td", { text: `${formatDate(statement.period_start)} – ${formatDate(statement.period_end)}` }),
      el("td", {}, [statusBadge(statement.status)]),
      el("td", { text: String(statement.transactions_inserted ?? 0) }),
      el("td", { text: formatDateTime(statement.created_at) }),
    ]);
    const open = async () => {
      try {
        const full = await api.getStatement(statement.id);
        renderDetail(detailContainer, full, accountsById);
      } catch (err) {
        renderDetail(detailContainer, { ...statement, problems: [err.message] }, accountsById);
      }
    };
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
    tbody.appendChild(row);
  }
  table.appendChild(thead);
  table.appendChild(tbody);
  wrap.appendChild(table);
  tableContainer.appendChild(wrap);

  if (statementId != null) {
    try {
      const full = await api.getStatement(statementId);
      renderDetail(detailContainer, full, accountsById);
    } catch (err) {
      renderDetail(detailContainer, { filename: `Statement #${statementId}`, problems: [err.message] }, accountsById);
    }
  }
}
