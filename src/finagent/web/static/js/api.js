// Minimal fetch wrapper for the FinDash API. Same-origin only, no third-party
// requests. Every call except /health and /api-info sends the bearer token.

import { getToken } from "./auth.js";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// Thrown specifically for a 401, so callers can trigger the Connect screen.
export class AuthError extends ApiError {
  constructor(message) {
    super(401, message);
  }
}

// Thrown for the server-has-no-token-configured 503.
export class ServerNotConfiguredError extends ApiError {
  constructor(message) {
    super(503, message);
  }
}

async function parseErrorMessage(response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.message === "string") return body.message;
  } catch {
    // body wasn't JSON, or was empty
  }
  return `Request failed (${response.status})`;
}

async function request(path, { method = "GET", body, isForm = false } = {}) {
  const headers = {};
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  if (body && !isForm) {
    headers["Content-Type"] = "application/json";
  }

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: isForm ? body : body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Network error: could not reach the server.");
  }

  if (response.status === 401) {
    throw new AuthError(await parseErrorMessage(response));
  }
  if (response.status === 503) {
    const message = await parseErrorMessage(response);
    if (/token not configured/i.test(message)) {
      throw new ServerNotConfiguredError(message);
    }
    throw new ApiError(503, message);
  }
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorMessage(response));
  }
  if (response.status === 204) return null;

  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

export function getApiInfo() {
  return request("/api-info");
}

export function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/uploads", { method: "POST", body: form, isForm: true });
}

export function listUploads(limit = 50) {
  return request(`/uploads?limit=${encodeURIComponent(limit)}`);
}

export function getUpload(id) {
  return request(`/uploads/${encodeURIComponent(id)}`);
}

export function listStatements(limit = 50, offset = 0) {
  return request(`/statements?limit=${limit}&offset=${offset}`);
}

export function getStatement(id) {
  return request(`/statements/${encodeURIComponent(id)}`);
}

export function listAccounts() {
  return request("/accounts");
}

export function listTransactions(filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, value);
    }
  }
  return request(`/transactions?${params.toString()}`);
}

export function listCategories() {
  return request("/categories");
}

export function updateTransactionCategory(id, categoryId) {
  return request(`/transactions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: { category_id: categoryId },
  });
}

export function categorizeNow() {
  return request("/transactions/categorize", { method: "POST" });
}

export function getCategorySummary(filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, value);
    }
  }
  return request(`/categories/summary?${params.toString()}`);
}
