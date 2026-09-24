// Token storage: localStorage when available, in-memory fallback otherwise.
// Never log the token and never place it in a URL.

const STORAGE_KEY = "findash.apiToken";

let memoryToken = null;
let usingMemoryFallback = false;

function storageAvailable() {
  try {
    const testKey = "__findash_storage_test__";
    window.localStorage.setItem(testKey, "1");
    window.localStorage.removeItem(testKey);
    return true;
  } catch {
    return false;
  }
}

export function getToken() {
  if (usingMemoryFallback || !storageAvailable()) {
    usingMemoryFallback = true;
    return memoryToken;
  }
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    usingMemoryFallback = true;
    return memoryToken;
  }
}

export function setToken(token) {
  if (!usingMemoryFallback && storageAvailable()) {
    try {
      window.localStorage.setItem(STORAGE_KEY, token);
      return;
    } catch {
      usingMemoryFallback = true;
    }
  }
  memoryToken = token;
}

export function clearToken() {
  memoryToken = null;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore: nothing persisted, or storage unavailable
  }
}
