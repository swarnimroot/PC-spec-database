// API client for the Competitive Spec DB FastAPI backend.
// By default the API is reached on the app's OWN origin under its base path
// (e.g. /competitive-database/api/...), which the Vite dev server proxies to
// the backend. This keeps it same-origin so it works locally and through the
// Tailscale Funnel with no hardcoded host. Override with VITE_API_BASE.

const BASE =
  import.meta.env.VITE_API_BASE || import.meta.env.BASE_URL.replace(/\/$/, "");

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

// GET /api/model/{id}/detail?year= -> {id, year, sections:{key:[{key,label,value}]}}
// Raw per-leaf detail (actual CPU/GPU names, display specs) for the accordion.
export function getModelDetail(id, year) {
  return getJSON(`/api/model/${encodeURIComponent(id)}/detail?year=${year}`);
}

// GET /api/schema/detail -> {sections:{key:[{key,label}]}} — every detail leaf
// per compare section, for the field-visibility panel.
export function getDetailSchema() {
  return getJSON("/api/schema/detail");
}

// POST /api/find — canonical Op string in {eq,gte,lte,contains,is_set,is_empty,vendor_unavailable}
export function find({ field_path, operator, value = "", narrow_by = {} }) {
  return getJSON("/api/find", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field_path, operator, value, narrow_by }),
  });
}

// ---- Curation Cockpit (queue + write endpoints) ----

// GET /api/queue/counts -> {conflicts, review, missing, hand}
export function getQueueCounts() {
  return getJSON("/api/queue/counts");
}

// GET /api/queue?tab=conflicts|review|missing|hand -> {tab, items[], count}
export function getQueue(tab) {
  return getJSON(`/api/queue?tab=${encodeURIComponent(tab)}`);
}

// GET /api/value/history -> {model_code, year, field_path, value, provenance{...}}
export function getValueHistory({ model_code, field_path, year }) {
  const q = new URLSearchParams({ model_code, field_path });
  if (year != null) q.set("year", year);
  return getJSON(`/api/value/history?${q.toString()}`);
}

// POST /api/value — field-state edit via manual_edit_cell.
// Body: {model_code, year?, field_path, value, status?, note?, entered_by?, source_url?}
export function postValue(payload) {
  return getJSON("/api/value", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// POST /api/resolve — conflict resolution via resolve_row.
// Body: {id|row_id, action, value?, note?, entered_by?}
export function postResolve(payload) {
  return getJSON("/api/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// POST /api/refresh — HEAVY / EXTERNAL re-scrape. Do not call casually.
// Body: {all:true} or {brand, model|url, from_db?, year?}
export function postRefresh(payload) {
  return getJSON("/api/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
