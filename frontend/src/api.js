// API client for the Competitive Spec DB FastAPI backend.
// Base URL is configurable via VITE_API_BASE (default http://localhost:8011).

const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8011";

async function getJSON(path, opts) {
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    let detail = "";
    try {
      detail = JSON.stringify(await res.json());
    } catch {
      detail = res.statusText;
    }
    throw new Error(`${path} -> ${res.status} ${detail}`);
  }
  return res.json();
}

export function health() {
  return getJSON("/api/health");
}

export function getSchema() {
  return getJSON("/api/schema");
}

export function getCatalog() {
  return getJSON("/api/catalog");
}

export function getModel(id, year) {
  const q = year != null ? `?year=${year}` : "";
  return getJSON(`/api/model/${encodeURIComponent(id)}${q}`);
}

// POST /api/find — canonical Op string in {eq,gte,lte,contains,is_set,is_empty,vendor_unavailable}
export function find({ field_path, operator, value = "", narrow_by = {} }) {
  return getJSON("/api/find", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field_path, operator, value, narrow_by }),
  });
}
