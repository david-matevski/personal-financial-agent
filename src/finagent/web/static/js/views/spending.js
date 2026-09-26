import { el, clear } from "../dom.js";
import { formatMoney, parseAmount } from "../format.js";
import * as api from "../api.js";

function toIsoDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function quickRanges() {
  const today = new Date();
  const thisMonthStart = startOfMonth(today);
  const lastMonthStart = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const lastMonthEnd = new Date(today.getFullYear(), today.getMonth(), 0);
  const threeMonthsStart = new Date(today.getFullYear(), today.getMonth() - 2, 1);
  const yearStart = new Date(today.getFullYear(), 0, 1);
  return {
    "This month": [toIsoDate(thisMonthStart), toIsoDate(today)],
    "Last month": [toIsoDate(lastMonthStart), toIsoDate(lastMonthEnd)],
    "Last 3 months": [toIsoDate(threeMonthsStart), toIsoDate(today)],
    "This year": [toIsoDate(yearStart), toIsoDate(today)],
  };
}

function buildTransactionsLink({ categoryId, uncategorized, dateFrom, dateTo, accountId }) {
  const params = new URLSearchParams();
  if (uncategorized) {
    params.set("uncategorized", "true");
  } else if (categoryId != null) {
    params.set("category_id", String(categoryId));
  }
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (accountId) params.set("account_id", accountId);
  return `#/transactions?${params.toString()}`;
}

function renderSummary(container, rows, filterState) {
  clear(container);

  let totalOut = 0;
  let totalIn = 0;
  for (const row of rows) {
    const out = parseAmount(row.money_out) || 0;
    const inn = parseAmount(row.money_in) || 0;
    totalOut += out;
    totalIn += inn;
  }

  const currency = "CAD";
  container.appendChild(
    el("div", { class: "totals-bar" }, [
      el("div", { class: "total-item" }, [
        el("span", { text: "Total spend" }),
        el("strong", { class: "amount-out", text: formatMoney(String(totalOut), currency) }),
      ]),
      el("div", { class: "total-item" }, [
        el("span", { text: "Total in" }),
        el("strong", { class: "amount-in", text: formatMoney(String(totalIn), currency) }),
      ]),
    ])
  );

  if (!rows.length) {
    container.appendChild(el("p", { class: "empty-state", text: "No transactions in this range." }));
    return;
  }

  const maxOut = Math.max(...rows.map((r) => parseAmount(r.money_out) || 0), 0);
  const list = el("div", { class: "spending-list" });
  for (const row of rows) {
    const out = parseAmount(row.money_out) || 0;
    const share = maxOut > 0 ? (out / maxOut) * 100 : 0;
    const shareOfTotal = totalOut > 0 ? (out / totalOut) * 100 : 0;
    const isUncategorized = row.category_id == null;
    const name = isUncategorized ? "Uncategorized" : row.category_name || `Category #${row.category_id}`;
    const href = buildTransactionsLink({
      categoryId: row.category_id,
      uncategorized: isUncategorized,
      dateFrom: filterState.dateFrom,
      dateTo: filterState.dateTo,
      accountId: filterState.accountId,
    });
    const pctText = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(
      shareOfTotal / 100
    );
    list.appendChild(
      el("a", { class: "spending-row", href }, [
        el("div", { class: "spending-row__header" }, [
          el("span", { class: "spending-row__name", text: name }),
          el("span", { class: "spending-row__amount", text: formatMoney(row.money_out, currency) }),
        ]),
        el("div", { class: "spending-row__bar-track" }, [
          el("div", { class: "spending-row__bar", style: `width: ${share}%` }),
        ]),
        el("div", { class: "spending-row__meta" }, [
          el("span", { text: `${pctText} of spend` }),
          el("span", { text: `${row.count} transaction${row.count === 1 ? "" : "s"}` }),
        ]),
      ])
    );
  }
  container.appendChild(list);
}

export async function render(root) {
  const view = el("div", { class: "view view-spending" });
  view.appendChild(el("div", { class: "view-heading" }, [el("h1", { text: "Spending" })]));
  root.appendChild(view);

  const loadingNote = el("p", { class: "empty-state", text: "Loading accounts…" });
  view.appendChild(loadingNote);

  let accounts = [];
  try {
    accounts = await api.listAccounts();
  } catch (err) {
    loadingNote.replaceWith(el("p", { class: "form-error", role: "alert", text: err.message }));
    return;
  }
  loadingNote.remove();

  const ranges = quickRanges();
  const [defaultFrom, defaultTo] = ranges["This month"];

  const accountSelect = el("select", { id: "spending-account" }, [
    el("option", { value: "", text: "All accounts" }),
    ...accounts.map((a) => el("option", { value: String(a.id), text: a.label || a.account_name || `Account #${a.id}` })),
  ]);
  const dateFromInput = el("input", { type: "date", id: "spending-date-from", value: defaultFrom });
  const dateToInput = el("input", { type: "date", id: "spending-date-to", value: defaultTo });

  const quickButtons = el(
    "div",
    { class: "quick-ranges" },
    Object.entries(ranges).map(([label, [from, to]]) =>
      el("button", {
        type: "button",
        class: "btn",
        text: label,
        onclick: () => {
          dateFromInput.value = from;
          dateToInput.value = to;
          load();
        },
      })
    )
  );

  const filters = el("div", { class: "filters card" }, [
    el("div", { class: "field" }, [el("label", { for: "spending-account", text: "Account" }), accountSelect]),
    el("div", { class: "field" }, [el("label", { for: "spending-date-from", text: "From" }), dateFromInput]),
    el("div", { class: "field" }, [el("label", { for: "spending-date-to", text: "To" }), dateToInput]),
  ]);

  const summaryContainer = el("div");
  const statusLine = el("p", { class: "empty-state" });

  view.appendChild(quickButtons);
  view.appendChild(filters);
  view.appendChild(statusLine);
  view.appendChild(summaryContainer);

  async function load() {
    clear(summaryContainer);
    statusLine.hidden = false;
    statusLine.textContent = "Loading…";
    const filterState = {
      dateFrom: dateFromInput.value || undefined,
      dateTo: dateToInput.value || undefined,
      accountId: accountSelect.value || undefined,
    };
    try {
      const rows = await api.getCategorySummary({
        date_from: filterState.dateFrom,
        date_to: filterState.dateTo,
        account_id: filterState.accountId,
      });
      statusLine.hidden = true;
      statusLine.textContent = "";
      renderSummary(summaryContainer, rows, filterState);
    } catch (err) {
      statusLine.hidden = false;
      statusLine.textContent = err.message;
    }
  }

  accountSelect.addEventListener("change", load);
  dateFromInput.addEventListener("change", load);
  dateToInput.addEventListener("change", load);

  await load();
}
