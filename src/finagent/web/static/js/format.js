// Formatting helpers. Amount strings from the API are parsed only for
// display; all arithmetic that matters happens server-side.

export function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(bytes)) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const decimals = unitIndex === 0 ? 0 : 1;
  return `${value.toFixed(decimals)} ${units[unitIndex]}`;
}

export function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

// Parses a decimal amount string safely. Returns null if it isn't parseable.
export function parseAmount(amountString) {
  if (amountString == null) return null;
  const value = Number.parseFloat(amountString);
  return Number.isNaN(value) ? null : value;
}

// Formats a signed amount string (positive = money out, negative = money in)
// as a magnitude in the given currency. Direction is conveyed by the caller
// via text/labels, not by this function.
export function formatMoney(amountString, currency) {
  const value = parseAmount(amountString);
  if (value == null) return amountString ?? "—";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency || "CAD",
    }).format(Math.abs(value));
  } catch {
    return Math.abs(value).toFixed(2);
  }
}
