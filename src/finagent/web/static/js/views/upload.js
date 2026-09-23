import { el, clear, badge } from "../dom.js";
import { formatBytes, formatDateTime } from "../format.js";
import * as api from "../api.js";

const MAX_BYTES = 20 * 1024 * 1024;
const ACCEPTED_EXT = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".csv", ".xls", ".xlsx"];
const MAX_PARALLEL = 3;

function statusText(upload) {
  if (upload.status === "QUEUED") return { text: "Queued", tone: "neutral" };
  if (upload.status === "PROCESSING") return { text: "Reading statement…", tone: "neutral" };
  if (upload.status === "ERROR") return { text: upload.error || "Something went wrong", tone: "danger" };
  if (upload.status === "DONE") {
    if (upload.statement_status === "VERIFIED") {
      const n = upload.transactions_inserted ?? 0;
      return { text: `Verified · ${n} transaction${n === 1 ? "" : "s"} added`, tone: "ok" };
    }
    if (upload.statement_status === "UNVERIFIED") {
      return { text: "Imported, unverified (no printed totals to check against)", tone: "warn" };
    }
    if (upload.statement_status === "FAILED") {
      return { text: "Needs review: totals didn't reconcile", tone: "danger", link: upload.statement_id };
    }
    return { text: "Done", tone: "ok" };
  }
  return { text: upload.status, tone: "neutral" };
}

function buildUploadCard(upload) {
  const card = el("div", { class: "upload-card", dataset: { uploadId: upload.id } });
  card.appendChild(
    el("div", { class: "upload-card__row" }, [
      el("span", { class: "upload-card__name", text: upload.filename }),
      el("span", { class: "upload-card__size", text: formatBytes(upload.size_bytes) }),
    ])
  );
  const info = statusText(upload);
  const statusRow = el("div", { class: "upload-card__status" }, [badge(info.text, info.tone)]);
  if (info.link) {
    const link = el("a", { href: `#/statements/${info.link}`, text: "View statement" });
    link.style.marginLeft = "8px";
    statusRow.appendChild(link);
  }
  card.appendChild(statusRow);
  return card;
}

function renderRecentUploads(container, uploads) {
  clear(container);
  if (!uploads.length) {
    container.appendChild(el("p", { class: "empty-state", text: "No uploads yet." }));
    return;
  }
  const list = el("div", { class: "upload-cards" });
  for (const upload of uploads) {
    list.appendChild(buildUploadCard(upload));
  }
  container.appendChild(list);
}

async function pollUpload(uploadId, card) {
  const poll = async () => {
    let upload;
    try {
      upload = await api.getUpload(uploadId);
    } catch (err) {
      const info = { text: err.message || "Could not check status", tone: "danger" };
      clear(card);
      card.appendChild(el("div", { class: "upload-card__status" }, [badge(info.text, info.tone)]));
      return;
    }
    const fresh = buildUploadCard(upload);
    card.replaceWith(fresh);
    card = fresh;
    if (upload.status === "QUEUED" || upload.status === "PROCESSING") {
      setTimeout(poll, 2000);
    }
  };
  setTimeout(poll, 2000);
}

function validateFile(file) {
  if (file.size > MAX_BYTES) {
    return `${file.name} is larger than 20 MB and was not sent.`;
  }
  const lower = file.name.toLowerCase();
  if (!ACCEPTED_EXT.some((ext) => lower.endsWith(ext))) {
    return `${file.name} is not a supported file type.`;
  }
  return null;
}

export function render(root, { onNavigate } = {}) {
  const view = el("div", { class: "view view-upload" });
  view.appendChild(el("div", { class: "view-heading" }, [el("h1", { text: "Upload" })]));

  const errorBox = el("p", { class: "form-error", role: "alert" });
  errorBox.hidden = true;

  const fileInput = el("input", {
    type: "file",
    multiple: true,
    accept: ACCEPTED_EXT.join(","),
    class: "visually-hidden",
    id: "upload-file-input",
  });

  const dropzone = el(
    "button",
    {
      type: "button",
      class: "dropzone",
      "aria-describedby": "upload-hint",
    },
    [
      el("strong", { text: "Drop statements here, or click to choose files" }),
      el("span", { id: "upload-hint", text: "PDF, PNG, JPG, WebP, CSV, XLS, XLSX — up to 20 MB each" }),
    ]
  );

  const uploadCardsContainer = el("div");
  const recentHeading = el("h2", { text: "Recent uploads" });
  const recentContainer = el("div", {}, [el("p", { class: "empty-state", text: "Loading recent uploads…" })]);

  view.appendChild(errorBox);
  view.appendChild(dropzone);
  view.appendChild(fileInput);
  view.appendChild(el("div", { class: "upload-cards", id: "active-uploads" }, [uploadCardsContainer]));
  view.appendChild(recentHeading);
  view.appendChild(recentContainer);

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function clearError() {
    errorBox.hidden = true;
    errorBox.textContent = "";
  }

  async function refreshRecent() {
    try {
      const uploads = await api.listUploads(20);
      renderRecentUploads(recentContainer, uploads);
    } catch (err) {
      clear(recentContainer);
      recentContainer.appendChild(el("p", { class: "form-error", text: err.message }));
    }
  }

  async function uploadOne(file) {
    const card = el("div", { class: "upload-card" }, [
      el("div", { class: "upload-card__row" }, [
        el("span", { class: "upload-card__name", text: file.name }),
        el("span", { class: "upload-card__size", text: formatBytes(file.size) }),
      ]),
      el("div", { class: "upload-card__status" }, [badge("Uploading…", "neutral")]),
    ]);
    uploadCardsContainer.appendChild(card);
    try {
      const result = await api.uploadFile(file);
      const fresh = buildUploadCard(result);
      card.replaceWith(fresh);
      pollUpload(result.id, fresh);
      refreshRecent();
    } catch (err) {
      clear(card);
      card.appendChild(
        el("div", { class: "upload-card__row" }, [el("span", { class: "upload-card__name", text: file.name })])
      );
      card.appendChild(el("div", { class: "upload-card__status" }, [badge(err.message || "Upload failed", "danger")]));
    }
  }

  async function handleFiles(fileList) {
    clearError();
    const files = Array.from(fileList);
    const valid = [];
    const problems = [];
    for (const file of files) {
      const problem = validateFile(file);
      if (problem) problems.push(problem);
      else valid.push(file);
    }
    if (problems.length) showError(problems.join(" "));

    // Upload with at most MAX_PARALLEL in flight at once.
    let index = 0;
    async function worker() {
      while (index < valid.length) {
        const file = valid[index];
        index += 1;
        await uploadOne(file);
      }
    }
    const workers = Array.from({ length: Math.min(MAX_PARALLEL, valid.length) }, () => worker());
    await Promise.all(workers);
  }

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("is-dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("is-dragover");
    if (e.dataTransfer?.files?.length) handleFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files?.length) handleFiles(fileInput.files);
    fileInput.value = "";
  });

  root.appendChild(view);
  refreshRecent();
}
