import { el, clear } from "../dom.js";
import { formatDate, formatMoney, parseAmount } from "../format.js";
import * as api from "../api.js";

const PAGE_SIZE = 100;

function accountLabel(accountsById, accountId) {
  const account = accountsById.get(accountId);
  if (!account) return `Account #${accountId}`;
  return account.label || account.account_name || `${account.issuer} •${account.account_last4 ?? ""}`;
}

function matchesSearch(tx, term) {
  if (!term) return true;
  return tx.description.toLowerCase().includes(term.toLowerCase());
}

function renderTotals(container, rows) {
  clear(container);
  let out = 0;
  let inn = 0;
  for (const tx of rows) {
    const value = parseAmount(tx.amount);
    if (value == null) continue;
    if (value >= 0) out += value;
    else inn += Math.abs(value);
  }
  const currency = rows[0]?.currency || "CAD";
  const net = out - inn;
  const item = (label, value, cls) =>
    el("div", { class: "total-item" }, [
      el("span", { text: label }),
      el("strong", { class: cls, text: value }),
    ]);
  container.appendChild(item("Money out", formatMoney(String(out), currency), "amount-out"));
  container.appendChild(item("Money in", formatMoney(String(inn), currency), "amount-in"));
  container.appendChild(item("Net", `${net < 0 ? "-" : ""}${formatMoney(String(net), currency)}`, ""));
}

function renderTable(container, rows, accountsById) {
  clear(container);
  if (!rows.length) {
    container.appendChild(el("p", { class: "empty-state", text: "No transactions match these filters." }));
    return;
  }
  const wrap = el("div", { class: "table-scroll" });
  const table = el("table");
  table.appendChild(
    el("thead", {}, [
      el("tr", {}, [
        el("th", { text: "Date" }),
        el("th", { text: "Description" }),
        el("th", { text: "Account" }),
        el("th", { text: "Amount" }),
      ]),
    ])
  );
  const tbody = el("tbody");
  for (const tx of rows) {
    const value = parseAmount(tx.amount);
    const isIn = value != null && value < 0;
    const amountCell = isIn
      ? el("td", {}, [
          el("span", { class: "amount-in", text: formatMoney(tx.amount, tx.currency) }),
          el("span", { class: "money-in-label", text: "In" }),
        ])
      : el("td", {}, [el("span", { class: "amount-out", text: formatMoney(tx.amount, tx.currency) })]);
    tbody.appendChild(
      el("tr", {}, [
        el("td", { text: formatDate(tx.posted_date || tx.transaction_date) }),
        el("td", { class: "description-cell", text: tx.description }),
        el("td", { text: accountLabel(accountsById, tx.account_id) }),
        amountCell,
      ])
    );
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  container.appendChild(wrap);
}

export async function render(root) {
  const view = el("div", { class: "view view-transactions" });
  view.appendChild(el("div", { class: "view-heading" }, [el("h1", { text: "Transactions" })]));
  const loadingNote = el("p", { class: "empty-state", text: "Loading transactions…" });
  view.appendChild(loadingNote);
  root.appendChild(view);

  let accounts = [];
  try {
    accounts = await api.listAccounts();
  } catch (err) {
    loadingNote.replaceWith(el("p", { class: "form-error", role: "alert", text: err.message }));
    return;
  }
  loadingNote.remove();
  const accountsById = new Map(accounts.map((a) => [a.id, a]));

  const accountSelect = el("select", { id: "filter-account" }, [
    el("option", { value: "", text: "All accounts" }),
    ...accounts.map((a) => el("option", { value: String(a.id), text: a.label || a.account_name || `Account #${a.id}` })),
  ]);
  const dateFromInput = el("input", { type: "date", id: "filter-date-from" });
  const dateToInput = el("input", { type: "date", id: "filter-date-to" });
  const searchInput = el("input", { type: "search", id: "filter-search", placeholder: "Search description…" });

  const filters = el("div", { class: "filters card" }, [
    el("div", { class: "field" }, [el("label", { for: "filter-account", text: "Account" }), accountSelect]),
    el("div", { class: "field" }, [el("label", { for: "filter-date-from", text: "From" }), dateFromInput]),
    el("div", { class: "field" }, [el("label", { for: "filter-date-to", text: "To" }), dateToInput]),
    el("div", { class: "field" }, [el("label", { for: "filter-search", text: "Search" }), searchInput]),
  ]);

  const totalsBar = el("div", { class: "totals-bar" });
  const tableContainer = el("div");
  const loadMoreBtn = el("button", { type: "button", class: "btn", text: "Load more" });
  const statusLine = el("p", { class: "empty-state" });

  view.appendChild(filters);
  view.appendChild(totalsBar);
  view.appendChild(tableContainer);
  view.appendChild(statusLine);
  view.appendChild(loadMoreBtn);

  let allRows = [];
  let offset = 0;
  let exhausted = false;
  let loading = false;

  function currentFilters() {
    return {
      account_id: accountSelect.value || undefined,
      date_from: dateFromInput.value || undefined,
      date_to: dateToInput.value || undefined,
    };
  }

  function applyClientFilters() {
    const term = searchInput.value.trim();
    return allRows.filter((tx) => matchesSearch(tx, term));
  }

  function redraw() {
    const filtered = applyClientFilters();
    renderTable(tableContainer, filtered, accountsById);
    renderTotals(totalsBar, filtered);
  }

  async function loadPage({ reset }) {
    if (loading) return;
    loading = true;
    loadMoreBtn.disabled = true;
    if (reset) {
      allRows = [];
      offset = 0;
      exhausted = false;
    }
    statusLine.hidden = false;
    statusLine.textContent = "Loading…";
    try {
      const rows = await api.listTransactions({
        ...currentFilters(),
        limit: PAGE_SIZE,
        offset,
      });
      allRows = reset ? rows : allRows.concat(rows);
      offset += rows.length;
      exhausted = rows.length < PAGE_SIZE;
      statusLine.hidden = true;
      statusLine.textContent = "";
    } catch (err) {
      statusLine.hidden = false;
      statusLine.textContent = err.message;
    } finally {
      loading = false;
      loadMoreBtn.disabled = exhausted;
      loadMoreBtn.hidden = exhausted;
      redraw();
    }
  }

  accountSelect.addEventListener("change", () => loadPage({ reset: true }));
  dateFromInput.addEventListener("change", () => loadPage({ reset: true }));
  dateToInput.addEventListener("change", () => loadPage({ reset: true }));
  searchInput.addEventListener("input", () => redraw());
  loadMoreBtn.addEventListener("click", () => loadPage({ reset: false }));

  await loadPage({ reset: true });
}
