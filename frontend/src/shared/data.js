// Shared data helpers for the live catalog (model objects from /api/catalog).
//
// Model shape (from the FastAPI serializers):
//   { id, brand, series, model, segment, years, updated, base, byYear }
// Every spec value is { v, s, src, ts, note } where s is one of the 5 states.
// `base` is the LATEST year's spec map; `byYear[year]` holds only the fields
// that differ from base for that year, so resolve(base, byYear, year) merges.

export const STATE_LABEL = {
  confirmed: "Confirmed",
  not_published: "Vendor doesn't publish",
  hand: "Manual",
  review: "Unverified",
  blank: "Missing",
};

export const latestYear = (m) => m.years[m.years.length - 1];
export const earliestYear = (m) => m.years[0];

// The stored `model` (product) name already includes the series word
// (e.g. series "Strix", model "Strix G16"). Strip that redundant leading
// series so a "<dim series> <bold model>" label reads "Strix G16", not
// "Strix Strix G16". Display-only — the underlying data is unchanged.
export function modelTail(series, model) {
  if (!series || !model) return model || "";
  const s = String(series).trim();
  const lower = model.toLowerCase();
  if (lower === s.toLowerCase()) return "";
  if (lower.startsWith(s.toLowerCase() + " ")) {
    return model.slice(s.length).trimStart();
  }
  return model;
}

// Merge base + the override for a given year into a concrete spec map.
export function resolve(m, year) {
  const y = year == null ? latestYear(m) : year;
  const spec = { ...m.base };
  const ov = (m.byYear && m.byYear[String(y)]) || {};
  Object.keys(ov).forEach((k) => {
    spec[k] = ov[k];
  });
  return spec;
}

// Lead value: first element of an array value, or the scalar.
export const lead = (cell) =>
  !cell || cell.v == null ? null : Array.isArray(cell.v) ? cell.v[0] : cell.v;

// All values as an array (or null when empty).
export const valArray = (cell) =>
  !cell || cell.v == null ? null : Array.isArray(cell.v) ? cell.v : [cell.v];

// Substring test against a cell's value(s).
export const cellHas = (cell, sub) => {
  const arr = valArray(cell);
  if (!arr) return false;
  return arr.some((v) => String(v).toLowerCase().includes(sub.toLowerCase()));
};

// Which field keys changed between two resolved years.
export function changedKeys(m, yearA, yearB) {
  const a = resolve(m, yearA);
  const b = resolve(m, yearB);
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  const out = [];
  keys.forEach((k) => {
    const va = a[k] ? JSON.stringify(a[k].v) : null;
    const vb = b[k] ? JSON.stringify(b[k].v) : null;
    if (va !== vb) out.push(k);
  });
  return out;
}

// Info about a per-model spec change across years (for the →YY marker).
export function changedInfo(m, key) {
  if (m.years.length < 2) return null;
  const a = resolve(m, earliestYear(m))[key];
  const b = resolve(m, latestYear(m))[key];
  const na = a && a.v != null ? JSON.stringify(a.v) : null;
  const nb = b && b.v != null ? JSON.stringify(b.v) : null;
  if (na === nb) return null;
  return { year: latestYear(m), oldLead: lead(a), oldYear: earliestYear(m) };
}

// ---- numeric / token parsers over the live joined-string values ----

export const firstNum = (s) => {
  if (s == null) return null;
  const m = String(s).match(/[\d.]+/);
  return m ? parseFloat(m[0]) : null;
};

export const maxHz = (cell) => {
  const v = lead(cell);
  if (v == null) return 0;
  const hz = String(v).match(/(\d+)\s*Hz/gi);
  if (!hz) return 0;
  return Math.max(...hz.map((x) => parseInt(x, 10)));
};

export const weightKg = (cell) => {
  const v = lead(cell);
  if (v == null) return null;
  const m = String(v).match(/([\d.]+)\s*kg/i);
  return m ? parseFloat(m[1]) : null;
};

export const maxMemGb = (cell) => {
  const v = lead(cell);
  if (v == null) return 0;
  const m = String(v).match(/up to (\d+)\s*GB/i);
  return m ? parseInt(m[1], 10) : 0;
};
