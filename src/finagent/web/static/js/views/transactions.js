import { el, clear, badge } from "../dom.js";
import { formatDate, formatMoney, parseAmount } from "../format.js";
import * as api from "../api.js";

const PAGE_SIZE = 100;
const UNCATEGORIZED_VALUE = "uncategorized";
const CONFIRM_CHUNK_SIZE = 500;

function accountLabel(accountsById, accountId) {
  const account = accountsById.get(accountId);
  if (!account) return `Account #${accountId}`;
  return account.label || account.account_name || `${account.issuer} •${account.account_last4 ?? ""}`;
}

function matchesSearch(tx, term) {
  if (!term) return true;
  return tx.description.toLowerCase().includes(term.toLowerCase());
}

function formatConfidence(confidence) {
  if (confidence == null || confidence === "") return null;
  const value = Number.parseFloat(confidence);
  if (Number.isNaN(value)) return confidence;
  return new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 0 }).format(value);
}

// Renders the Status cell for one transaction into `cell` (cleared first).
// Called both at initial row build and after any update (category change,
// single confirm, bulk confirm), so every path shows the same states:
//   - uncategorized: nothing to confirm
//   - needs review (AI, low confidence or otherwise flagged): a badge plus
//     a compact Confirm button that marks the AI's guess correct in place
//   - AI, confident: muted "AI · NN%"
//   - set or confirmed by the owner: muted "✓ You"
function renderStatusCell(cell, tx, onChanged) {
  clear(cell);
  if (tx.category_id == null) {
    cell.appendChild(el("span", { class: "status-muted", text: "Not categorized" }));
    return;
  }
  if (tx.category_source === "user") {
    cell.appendChild(
      el("span", { class: "status-muted", title: "Set or confirmed by you", text: "✓ You" })
    );
    return;
  }
  if (tx.needs_review) {
    const errorNote = el("span", { class: "status-error", role: "alert" });
    const confirmBtn = el("button", {
      type: "button",
      class: "btn btn--small",
      text: "✓ Confirm",
      "aria-label": `Confirm category ${tx.category_name ?? ""} for ${tx.description}`,
    });
    confirmBtn.addEventListener("click", async () => {
      confirmBtn.disabled = true;
      errorNote.textContent = "";
      try {
        await api.confirmCategories([tx.id]);
        tx.category_source = "user";
        tx.category_confidence = null;
        tx.needs_review = false;
        renderStatusCell(cell, tx, onChanged);
        onChanged(tx);
      } catch (err) {
        errorNote.textContent = err.message || "Could not confirm.";
        confirmBtn.disabled = false;
      }
    });
    cell.appendChild(
      el("div", { class: "status-review" }, [badge("Review", "warn"), confirmBtn, errorNote])
    );
    return;
  }
  const pct = formatConfidence(tx.category_confidence);
  const label = pct ? `AI · ${pct}` : "AI";
  const full = pct ? `Categorized by AI, ${pct} confidence` : "Categorized by AI";
  cell.appendChild(
    el("span", { class: "status-muted", title: full }, [
      label,
      el("span", { class: "visually-hidden", text: ` (${full})` }),
    ])
  );
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

function buildCategorySelect(tx, categories) {
  // No "Uncategorized" choice: the worker re-categorizes uncategorized rows
  // with AI, so clearing a category wouldn't stick. A row that has no
  // category yet shows a placeholder that can't be picked back.
  const options = categories.map((c) => el("option", { value: String(c.id), text: c.name }));
  if (tx.category_id == null) {
    const placeholder = el("option", { value: "", text: "Choose a category…" });
    placeholder.disabled = true;
    options.unshift(placeholder);
  }
  const select = el("select", { "aria-label": `Category for ${tx.description}` }, options);
  select.value = tx.category_id != null ? String(tx.category_id) : "";
  return select;
}

function buildRow(tx, accountsById, categories, onCategoryChange) {
  const value = parseAmount(tx.amount);
  const isIn = value != null && value < 0;
  const amountCell = isIn
    ? el("td", {}, [
        el("span", { class: "amount-in", text: formatMoney(tx.amount, tx.currency) }),
        el("span", { class: "money-in-label", text: "In" }),
      ])
    : el("td", {}, [el("span", { class: "amount-out", text: formatMoney(tx.amount, tx.currency) })]);

  const select = buildCategorySelect(tx, categories);
  const savedNote = el("span", { class: "save-note", role: "status" });
  const statusCell = el("td", { class: "status-cell" });
  renderStatusCell(statusCell, tx, onCategoryChange);

  select.addEventListener("change", async () => {
    const previousValue = tx.category_id != null ? String(tx.category_id) : "";
    const chosen = select.value;
    if (chosen === "") return;
    select.disabled = true;
    savedNote.textContent = "";
    savedNote.classList.remove("form-error");
    try {
      const updated = await api.updateTransactionCategory(tx.id, Number(chosen));
      tx.category_id = updated.category_id;
      tx.category_name = updated.category_name;
      tx.category_source = "user";
      tx.category_confidence = updated.category_confidence;
      tx.needs_review = updated.needs_review;
      savedNote.textContent = "Saved";
      renderStatusCell(statusCell, tx, onCategoryChange);
      onCategoryChange(tx);
    } catch (err) {
      select.value = previousValue;
      savedNote.textContent = err.message || "Could not save.";
      savedNote.classList.add("form-error");
    } finally {
      select.disabled = false;
    }
  });

  const categoryCell = el("td", { class: "category-cell" }, [
    select,
    el("div", { class: "category-cell__meta" }, [savedNote]),
  ]);

  return el("tr", {}, [
    el("td", { text: formatDate(tx.posted_date || tx.transaction_date) }),
    el("td", { class: "description-cell", text: tx.description }),
    el("td", { text: accountLabel(accountsById, tx.account_id) }),
    categoryCell,
    statusCell,
    amountCell,
  ]);
}

function renderTable(container, rows, accountsById, categories, onCategoryChange) {
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
        el("th", { text: "Category" }),
        el("th", { text: "Status" }),
        el("th", { text: "Amount" }),
      ]),
    ])
  );
  const tbody = el("tbody");
  for (const tx of rows) {
    tbody.appendChild(buildRow(tx, accountsById, categories, onCategoryChange));
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  container.appendChild(wrap);
}

export async function render(root, { params } = {}) {
  const view = el("div", { class: "view view-transactions" });
  view.appendChild(el("div", { class: "view-heading" }, [el("h1", { text: "Transactions" })]));
  const loadingNote = el("p", { class: "empty-state", text: "Loading transactions…" });
  view.appendChild(loadingNote);
  root.appendChild(view);

  let accounts = [];
  let categories = [];
  try {
    [accounts, categories] = await Promise.all([api.listAccounts(), api.listCategories()]);
  } catch (err) {
    loadingNote.replaceWith(el("p", { class: "form-error", role: "alert", text: err.message }));
    return;
  }
  loadingNote.remove();
  const accountsById = new Map(accounts.map((a) => [a.id, a]));

  const initialCategoryId = params?.get("category_id") || "";
  const initialUncategorized = params?.get("uncategorized") === "true";
  const initialAccountId = params?.get("account_id") || "";
  const initialDateFrom = params?.get("date_from") || "";
  const initialDateTo = params?.get("date_to") || "";
  const initialNeedsReview = params?.get("needs_review") === "true";

  const accountSelect = el("select", { id: "filter-account" }, [
    el("option", { value: "", text: "All accounts" }),
    ...accounts.map((a) => el("option", { value: String(a.id), text: a.label || a.account_name || `Account #${a.id}` })),
  ]);
  accountSelect.value = initialAccountId;

  const categorySelect = el("select", { id: "filter-category" }, [
    el("option", { value: "", text: "All categories" }),
    el("option", { value: UNCATEGORIZED_VALUE, text: "Uncategorized" }),
    ...categories.map((c) => el("option", { value: String(c.id), text: c.name })),
  ]);
  categorySelect.value = initialUncategorized ? UNCATEGORIZED_VALUE : initialCategoryId;

  const dateFromInput = el("input", { type: "date", id: "filter-date-from", value: initialDateFrom || undefined });
  const dateToInput = el("input", { type: "date", id: "filter-date-to", value: initialDateTo || undefined });
  const searchInput = el("input", { type: "search", id: "filter-search", placeholder: "Search description…" });
  const reviewCheckbox = el("input", { type: "checkbox", id: "filter-needs-review" });
  reviewCheckbox.checked = initialNeedsReview;

  const filters = el("div", { class: "filters card" }, [
    el("div", { class: "field" }, [el("label", { for: "filter-account", text: "Account" }), accountSelect]),
    el("div", { class: "field" }, [el("label", { for: "filter-category", text: "Category" }), categorySelect]),
    el("div", { class: "field" }, [el("label", { for: "filter-date-from", text: "From" }), dateFromInput]),
    el("div", { class: "field" }, [el("label", { for: "filter-date-to", text: "To" }), dateToInput]),
    el("div", { class: "field" }, [el("label", { for: "filter-search", text: "Search" }), searchInput]),
    el("div", { class: "field field--checkbox" }, [
      el("label", { for: "filter-needs-review", class: "checkbox-label" }, [
        reviewCheckbox,
        el("span", { text: "Needs review only" }),
      ]),
    ]),
  ]);

  const categorizeBtn = el("button", { type: "button", class: "btn btn--primary", text: "Categorize now" });
  const rerunAiBtn = el("button", { type: "button", class: "btn", text: "Re-run AI on all" });
  const categorizeStatus = el("p", { class: "empty-state", role: "status" });
  categorizeStatus.hidden = true;
  const actionsBar = el("div", { class: "actions-bar" }, [categorizeBtn, rerunAiBtn, categorizeStatus]);

  const totalsBar = el("div", { class: "totals-bar" });
  const bulkConfirmBtn = el("button", { type: "button", class: "btn", text: "Confirm all shown" });
  bulkConfirmBtn.hidden = true;
  const bulkBar = el("div", { class: "bulk-bar" }, [bulkConfirmBtn]);
  const tableContainer = el("div");
  const loadMoreBtn = el("button", { type: "button", class: "btn", text: "Load more" });
  const statusLine = el("p", { class: "empty-state" });

  view.appendChild(actionsBar);
  view.appendChild(filters);
  view.appendChild(totalsBar);
  view.appendChild(bulkBar);
  view.appendChild(tableContainer);
  view.appendChild(statusLine);
  view.appendChild(loadMoreBtn);

  let allRows = [];
  let offset = 0;
  let exhausted = false;
  let loading = false;

  function currentFilters() {
    const catValue = categorySelect.value;
    return {
      account_id: accountSelect.value || undefined,
      date_from: dateFromInput.value || undefined,
      date_to: dateToInput.value || undefined,
      category_id: catValue && catValue !== UNCATEGORIZED_VALUE ? catValue : undefined,
      uncategorized: catValue === UNCATEGORIZED_VALUE ? "true" : undefined,
      needs_review: reviewCheckbox.checked ? "true" : undefined,
    };
  }

  function applyClientFilters() {
    const term = searchInput.value.trim();
    return allRows.filter((tx) => matchesSearch(tx, term));
  }

  function confirmableRows(rows) {
    return rows.filter((tx) => tx.needs_review && tx.category_id != null);
  }

  function updateBulkButton(filtered) {
    const rows = filtered ?? applyClientFilters();
    const candidates = confirmableRows(rows);
    bulkConfirmBtn.hidden = candidates.length === 0;
    bulkConfirmBtn.textContent = `Confirm all ${candidates.length} shown`;
  }

  function redraw() {
    const filtered = applyClientFilters();
    renderTable(tableContainer, filtered, accountsById, categories, () => redrawTotalsOnly());
    renderTotals(totalsBar, filtered);
    updateBulkButton(filtered);
  }

  function redrawTotalsOnly() {
    const filtered = applyClientFilters();
    renderTotals(totalsBar, filtered);
    updateBulkButton(filtered);
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
  categorySelect.addEventListener("change", () => loadPage({ reset: true }));
  reviewCheckbox.addEventListener("change", () => loadPage({ reset: true }));
  dateFromInput.addEventListener("change", () => loadPage({ reset: true }));
  dateToInput.addEventListener("change", () => loadPage({ reset: true }));
  searchInput.addEventListener("input", () => redraw());
  loadMoreBtn.addEventListener("click", () => loadPage({ reset: false }));

  categorizeBtn.addEventListener("click", async () => {
    categorizeBtn.disabled = true;
    rerunAiBtn.disabled = true;
    categorizeBtn.textContent = "Categorizing…";
    categorizeStatus.hidden = false;
    categorizeStatus.classList.remove("form-error");
    categorizeStatus.textContent = "";
    try {
      const result = await api.categorizeNow();
      categorizeStatus.textContent = `${result.categorized} transaction${result.categorized === 1 ? "" : "s"} categorized`;
      await loadPage({ reset: true });
    } catch (err) {
      categorizeStatus.classList.add("form-error");
      categorizeStatus.textContent = err.message || "Categorization failed.";
    } finally {
      categorizeBtn.disabled = false;
      rerunAiBtn.disabled = false;
      categorizeBtn.textContent = "Categorize now";
    }
  });

  rerunAiBtn.addEventListener("click", async () => {
    if (!window.confirm("Re-check every AI-assigned category? Your own corrections are kept.")) {
      return;
    }
    categorizeBtn.disabled = true;
    rerunAiBtn.disabled = true;
    rerunAiBtn.textContent = "Re-categorizing…";
    categorizeStatus.hidden = false;
    categorizeStatus.classList.remove("form-error");
    categorizeStatus.textContent = "Re-categorizing…";
    let afterId;
    let totalDone = 0;
    try {
      for (;;) {
        const result = await api.categorizeNow({ include_ai: true, after_id: afterId });
        totalDone += result.categorized;
        categorizeStatus.textContent = `Re-categorizing… ${totalDone} done`;
        if (!result.remaining || result.last_id == null || result.last_id === afterId) {
          break;
        }
        afterId = result.last_id;
      }
      categorizeStatus.textContent = `${totalDone} transaction${totalDone === 1 ? "" : "s"} re-categorized`;
      await loadPage({ reset: true });
    } catch (err) {
      categorizeStatus.classList.add("form-error");
      categorizeStatus.textContent = err.message || "Re-categorization failed.";
    } finally {
      categorizeBtn.disabled = false;
      rerunAiBtn.disabled = false;
      rerunAiBtn.textContent = "Re-run AI on all";
    }
  });

  bulkConfirmBtn.addEventListener("click", async () => {
    const candidates = confirmableRows(applyClientFilters());
    if (!candidates.length) return;
    if (!window.confirm(`Mark ${candidates.length} AI categories as correct?`)) return;
    bulkConfirmBtn.disabled = true;
    statusLine.hidden = false;
    statusLine.textContent = "Confirming…";
    try {
      let confirmed = 0;
      for (let i = 0; i < candidates.length; i += CONFIRM_CHUNK_SIZE) {
        const chunk = candidates.slice(i, i + CONFIRM_CHUNK_SIZE);
        const result = await api.confirmCategories(chunk.map((tx) => tx.id));
        confirmed += result.confirmed;
        for (const tx of chunk) {
          tx.category_source = "user";
          tx.category_confidence = null;
          tx.needs_review = false;
        }
      }
      statusLine.textContent = `${confirmed} confirmed`;
      redraw();
    } catch (err) {
      statusLine.textContent = err.message || "Could not confirm.";
    } finally {
      bulkConfirmBtn.disabled = false;
    }
  });

  await loadPage({ reset: true });
}
