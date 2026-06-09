import { useState, useEffect, useMemo, useRef, useCallback, Fragment } from "react";
import {
  getQueueCounts,
  getQueue,
  getValueHistory,
  postValue,
  postResolve,
} from "../api.js";
import StateDot from "../shared/StateDot.jsx";
import { STATE_LABEL, modelTail } from "../shared/data.js";
import "./curation.css";

// Tab id -> label. Conflicts is the scrape-conflict queue; the rest are
// field-state queues driven by the stored value status.
const TABS = [
  { id: "conflicts", label: "Conflicts", cls: "t-conflict" },
  { id: "review", label: "Unverified", cls: "t-review" },
  { id: "missing", label: "Missing", cls: "t-blank" },
  { id: "hand", label: "Manual", cls: "" },
];

// Value-state control: display-state -> the bundle status the backend expects
// (mirrors api/serializers STATUS_TO_STATE). "blank" clears the value.
const STATE_TO_STATUS = {
  confirmed: "vouched",
  not_published: "vendor-doesn't-publish",
  hand: "manual",
  review: "needs-review",
  blank: "vendor-doesn't-publish",
};
const STATE_ORDER = ["confirmed", "not_published", "hand", "review", "blank"];

const isConflict = (it) => it && it.tab === "conflicts";

// A conflict whose existing value is null (catalog-vouch / new chip) only
// accepts accept_candidate / dropped; otherwise the full action set applies.
const conflictHasExisting = (it) => it && it.existing != null;

function fmtVal(v) {
  if (v == null) return null;
  if (Array.isArray(v)) return v.join(" / ");
  return String(v);
}

// String form of a value for the conflict edit box (and change-detection).
function editableOf(v) {
  if (v == null) return "";
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

// Coerce an edit-box string to a typed value for manual_override (the backend
// resolve_row writes it as-is, no coercion — mirror cli/resolve coerce_value).
function coerceValue(raw) {
  const s = String(raw ?? "").trim();
  if (s === "") return null;
  if (s === "true") return true;
  if (s === "false") return false;
  if (s === "null") return null;
  if (/^-?\d+$/.test(s)) return parseInt(s, 10);
  if (/^-?\d*\.\d+$/.test(s)) return parseFloat(s);
  return s;
}

// manual_override is rejected for catalog-vouch rows (new_chip) — no editing.
const canEditConflict = (it) => it && it.conflict_kind !== "catalog-vouch";

function nameOf(it) {
  if (!it) return "";
  const bits = [it.brand, it.series, modelTail(it.series, it.model)].filter(Boolean);
  return bits.join(" · ");
}

// Category-importance order (user-approved, S57). The Review queue groups by
// high-level spec category — not individual field — so the group count stays
// small (≤17). Order = how much each category tends to drive a buy decision.
const CATEGORY_ORDER = [
  "Graphics", "Processor", "Memory", "Storage", "Display",
  "Thermals", "Battery", "Adapter", "Weight", "Dimensions",
  "I/O", "Network", "Keyboard", "Camera", "Audio", "Design", "Identity",
];
const CATEGORY_RANK = new Map(CATEGORY_ORDER.map((c, i) => [c, i]));

// Field-state items carry `section` (the category). Conflict items don't, so
// we map the field path's root token to its category. Mirrors the backend
// _SECTION_REGISTRY grouping in views/orchestrator.py.
const ROOT_CATEGORY = {
  vendor: "Identity", vendor_full_name: "Identity", brand: "Identity",
  sub_brand: "Identity", series: "Identity", status: "Identity", segment: "Identity",
  cpu_offerings: "Processor", cpu_tdp_max: "Processor",
  boards: "Graphics",
  display_offerings: "Display",
  memory_type: "Memory", memory_max_gb: "Memory", memory_speed_mts: "Memory",
  memory_slots: "Memory", memory_overclocking: "Memory",
  storage_slots: "Storage", storage_max_gb: "Storage",
  keyboard_offerings: "Keyboard",
  camera_offerings: "Camera",
  speaker_count: "Audio", tuning_brand: "Audio", has_subwoofer: "Audio",
  wifi_standard: "Network", ethernet: "Network", bluetooth_version: "Network",
  usbc_thunderbolt_count: "I/O", usbc_thunderbolt_version: "I/O",
  usbc_non_thunderbolt_count: "I/O", usbc_non_thunderbolt_version: "I/O",
  usba_count: "I/O", usba_version: "I/O", hdmi_count: "I/O", hdmi_version: "I/O",
  sd_card: "I/O", sd_card_speed: "I/O", audio_jack: "I/O",
  battery_offerings: "Battery",
  adapter_offerings: "Adapter", adapter_connector: "Adapter",
  thermal_design: "Thermals", thermal_material: "Thermals", tim: "Thermals", fan_count: "Thermals",
  width_mm: "Dimensions", depth_mm: "Dimensions", height_mm_min: "Dimensions", height_mm_max: "Dimensions",
  weight_kg_min: "Weight", weight_kg_max: "Weight",
  a_cover_material: "Design", c_cover_material: "Design", d_cover_material: "Design",
  thermal_shelf: "Design", lighting: "Design",
};

function categoryOf(it) {
  if (it.section) return it.section;
  const root = String(it.field_path || "").split(".")[0];
  return ROOT_CATEGORY[root] || "Other";
}
function categoryRank(cat) {
  const r = CATEGORY_RANK.get(cat);
  return r == null ? 9999 : r;
}

// The field's own label, without the redundant "Category · " prefix.
function fieldLabel(it) {
  if (it.section && it.label && it.label.startsWith(it.section + " · ")) {
    return it.label.slice(it.section.length + 3);
  }
  return it.label || it.field_path;
}

// Group queue items by category, ordered by importance; products nested.
function buildGroups(items) {
  const map = new Map();
  for (const it of items) {
    const cat = categoryOf(it);
    let g = map.get(cat);
    if (!g) {
      g = { key: cat, label: cat, rank: categoryRank(cat), items: [] };
      map.set(cat, g);
    }
    g.items.push(it);
  }
  return [...map.values()].sort(
    (a, b) => a.rank - b.rank || a.label.localeCompare(b.label)
  );
}

// Flatten the items inside currently-expanded groups, in display order.
function visibleItems(groups, expanded) {
  return groups.filter((g) => expanded.has(g.key)).flatMap((g) => g.items);
}

export default function Curation() {
  const [counts, setCounts] = useState(null);
  const [tab, setTab] = useState("conflicts");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState(null);
  const [selId, setSelId] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set()); // open field groups

  // Editor draft (for the currently selected item).
  const [draft, setDraft] = useState(null);
  const [history, setHistory] = useState(null);
  const [historyErr, setHistoryErr] = useState(null);
  const [flash, setFlash] = useState("");
  const [busy, setBusy] = useState(false);
  const [resolvedCount, setResolvedCount] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false); // narrow-width provenance drawer
  const flashTimer = useRef(null);

  const showFlash = useCallback((msg) => {
    setFlash(msg);
    clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(""), 2000);
  }, []);

  const refreshCounts = useCallback(() => {
    getQueueCounts().then(setCounts).catch(() => {});
  }, []);

  const loadTab = useCallback(
    (t) => {
      setLoading(true);
      setLoadErr(null);
      getQueue(t)
        .then((res) => {
          setItems(res.items);
          const groups = buildGroups(res.items);
          // Top (most-important) field open, the rest collapsed.
          setExpanded(groups.length ? new Set([groups[0].key]) : new Set());
          setSelId(groups.length ? groups[0].items[0].id : null);
        })
        .catch((e) => {
          setLoadErr(String(e));
          setItems([]);
          setExpanded(new Set());
          setSelId(null);
        })
        .finally(() => setLoading(false));
    },
    []
  );

  useEffect(() => {
    refreshCounts();
  }, [refreshCounts]);

  useEffect(() => {
    loadTab(tab);
  }, [tab, loadTab]);

  const sel = useMemo(
    () => items.find((it) => it.id === selId) || null,
    [items, selId]
  );

  // Field groups (importance order) + the flat list of items in open groups.
  const groups = useMemo(() => buildGroups(items), [items]);
  const visible = useMemo(() => visibleItems(groups, expanded), [groups, expanded]);

  const toggle = useCallback(
    (key) => {
      const isOpen = expanded.has(key);
      const next = new Set(expanded);
      if (isOpen) next.delete(key);
      else next.add(key);
      setExpanded(next);
      // Collapsing the group that holds the selection — move selection to the
      // next still-visible item (or clear it if nothing is open).
      if (isOpen) {
        const vis = visibleItems(groups, next);
        if (!vis.some((it) => it.id === selId)) {
          setSelId(vis.length ? vis[0].id : null);
        }
      }
    },
    [expanded, groups, selId]
  );

  // Rebuild the draft whenever selection changes.
  useEffect(() => {
    if (!sel) {
      setDraft(null);
      return;
    }
    if (isConflict(sel)) {
      setDraft({
        kind: "conflict",
        // which side wins for a value-mismatch: "candidate" | "existing"
        pick: "candidate",
        // edit box, seeded with the candidate; if changed it drives a
        // manual_override (write your value) instead of accept/keep.
        editValue: editableOf(sel.candidate),
        note: "",
      });
    } else {
      setDraft({
        kind: "field",
        value: sel.value == null ? "" : Array.isArray(sel.value) ? sel.value.join(", ") : String(sel.value),
        state: sel.state,
        source: "",
        note: "",
      });
    }
  }, [sel]);

  // Load provenance/history for the selected cell.
  useEffect(() => {
    if (!sel) {
      setHistory(null);
      setHistoryErr(null);
      return;
    }
    let live = true;
    setHistory(null);
    setHistoryErr(null);
    getValueHistory({
      model_code: sel.model_code,
      field_path: sel.field_path,
      year: sel.year,
    })
      .then((h) => live && setHistory(h))
      .catch((e) => live && setHistoryErr(String(e)));
    return () => {
      live = false;
    };
  }, [sel]);

  // Advance selection within the current list after a commit (or removal).
  const advanceAfter = useCallback(
    (removedId) => {
      const idx = visible.findIndex((it) => it.id === removedId);
      const next = items.filter((it) => it.id !== removedId);
      setItems(next);
      const remVis = visible.filter((it) => it.id !== removedId);
      if (remVis.length) {
        // Stay within the open group(s); advance to the next visible item.
        setSelId(remVis[Math.min(idx, remVis.length - 1)].id);
      } else {
        // Open group is now empty — jump to the next most-important field.
        const ng = buildGroups(next);
        if (ng.length) {
          setExpanded(new Set([ng[0].key]));
          setSelId(ng[0].items[0].id);
        } else {
          setSelId(null);
        }
      }
    },
    [items, visible]
  );

  // ---- commit: field-state item ----
  const commitField = useCallback(
    (forceState) => {
      if (!sel || !draft || draft.kind !== "field") return;
      const state = forceState || draft.state;
      const status = STATE_TO_STATUS[state];
      const clearsValue = state === "not_published" || state === "blank";
      const value = clearsValue ? null : draft.value.trim() || null;
      setBusy(true);
      postValue({
        model_code: sel.model_code,
        year: sel.year,
        field_path: sel.field_path,
        value,
        status,
        note: draft.note || null,
        source_url: draft.source || null,
      })
        .then(() => {
          setResolvedCount((n) => n + 1);
          showFlash(`${STATE_LABEL[state]} · saved`);
          refreshCounts();
          advanceAfter(sel.id);
        })
        .catch((e) => showFlash(`Save failed: ${e}`))
        .finally(() => setBusy(false));
    },
    [sel, draft, showFlash, refreshCounts, advanceAfter]
  );

  // ---- commit: conflict item ----
  const commitConflict = useCallback(
    (overrideAction) => {
      if (!sel || !draft || draft.kind !== "conflict") return;
      const hasExisting = conflictHasExisting(sel);
      const edited =
        canEditConflict(sel) &&
        (draft.editValue ?? "").trim() !== editableOf(sel.candidate);
      let action = overrideAction;
      if (!action) {
        // Box changed from the candidate → write your value; else pick a side.
        action = edited
          ? "manual_override"
          : draft.pick === "existing"
          ? "kept_existing"
          : "accept_candidate";
      }
      // catalog-vouch / no-existing rows can't keep_existing.
      if (action === "kept_existing" && !hasExisting) action = "dropped";
      const body = { id: sel.id, action, note: draft.note || null };
      if (action === "manual_override") body.value = coerceValue(draft.editValue);
      setBusy(true);
      postResolve(body)
        .then(() => {
          setResolvedCount((n) => n + 1);
          const lbl =
            action === "manual_override"
              ? "Corrected value saved"
              : action === "accept_candidate"
              ? "Candidate accepted"
              : action === "kept_existing"
              ? "Existing kept"
              : "Conflict dropped";
          showFlash(`${lbl} · resolved`);
          refreshCounts();
          advanceAfter(sel.id);
        })
        .catch((e) => showFlash(`Resolve failed: ${e}`))
        .finally(() => setBusy(false));
    },
    [sel, draft, showFlash, refreshCounts, advanceAfter]
  );

  // ---- keyboard: j/k + arrows nav, C/N/R state, Enter save&advance ----
  useEffect(() => {
    const h = (e) => {
      const tag = (document.activeElement && document.activeElement.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA") {
        if (e.key === "Escape") document.activeElement.blur();
        return;
      }
      if (!visible.length) return;
      const idx = visible.findIndex((it) => it.id === selId);
      if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault();
        setSelId(visible[Math.min(idx + 1, visible.length - 1)].id);
      } else if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        setSelId(visible[Math.max(idx - 1, 0)].id);
      } else if (busy) {
        return;
      } else if (isConflict(sel)) {
        if (e.key === "Enter") commitConflict();
      } else {
        if (e.key === "c") commitField("confirmed");
        else if (e.key === "n") commitField("not_published");
        else if (e.key === "r") commitField("review");
        else if (e.key === "Enter") commitField();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [visible, selId, sel, busy, commitField, commitConflict]);

  if (loadErr) {
    return (
      <div className="loadstate err">
        <h2>Could not reach the backend</h2>
        <p>{loadErr}</p>
        <p>
          Is uvicorn running on <code>{import.meta.env.VITE_API_BASE}</code>?
        </p>
      </div>
    );
  }

  return (
    <div className="cur-root">
      {/* ===== queue rail (LEFT) ===== */}
      <div className="cur-queue">
        <div className="cur-tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={"cur-tab " + t.cls + (tab === t.id ? " active" : "")}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              <span className="n">{counts ? counts[t.id] : "·"}</span>
            </button>
          ))}
        </div>
        <div className="cur-qhead">
          <span>
            {loading ? "Loading…" : `${items.length} item${items.length !== 1 ? "s" : ""}`}
          </span>
          <span className="hint">j/k or ↑↓ to move</span>
        </div>
        <div className="cur-qlist">
          {!loading && items.length === 0 ? (
            <div className="cur-qempty">
              <div className="big">✓</div>
              Nothing in this queue.
              <br />
              Clean.
            </div>
          ) : (
            groups.map((g) => {
              const open = expanded.has(g.key);
              return (
                <div key={g.key} className="cur-group">
                  <button
                    className={"cur-ghead" + (open ? " open" : "")}
                    onClick={() => toggle(g.key)}
                  >
                    <span className="cur-gcaret">{open ? "▼" : "▶"}</span>
                    <span className="cur-glabel">{g.label}</span>
                    <span className="cur-gn">{g.items.length}</span>
                  </button>
                  {open &&
                    g.items.map((it) => {
                      const conf = isConflict(it);
                      const valTxt = conf ? fmtVal(it.candidate) : fmtVal(it.value);
                      return (
                        <div
                          key={it.id}
                          className={"cur-qitem" + (it.id === selId ? " sel" : "")}
                          onClick={() => setSelId(it.id)}
                        >
                          <div className="qi-top">
                            <span className="qi-model">{nameOf(it)}</span>
                            {conf ? (
                              <span className={"qi-kind k-" + it.conflict_kind}>
                                {it.conflict_type_label}
                              </span>
                            ) : (
                              <StateDot s={it.state} />
                            )}
                          </div>
                          <div className="qi-field">{fieldLabel(it)} · {it.year}</div>
                          {valTxt ? (
                            <div className="qi-val">{valTxt}</div>
                          ) : (
                            <div className="qi-val empty">
                              {conf ? "(no candidate)" : it.state === "not_published" ? "vendor doesn't publish" : "no value yet"}
                            </div>
                          )}
                        </div>
                      );
                    })}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ===== focus editor (MIDDLE) ===== */}
      <div className="cur-focus">
        {!sel || !draft ? (
          <div className="cur-empty">
            <div>
              <h2>Queue clear</h2>
              <p>Pick another tab, or refresh to surface new work.</p>
            </div>
          </div>
        ) : (
          <Fragment>
            <div className="cur-focus-inner">
              <div className="cur-crumb">
                <span>{nameOf(sel)}</span>
                <span className="sep">›</span>
                <span>{sel.year}</span>
                <span className="sep">›</span>
                <span className="now">{isConflict(sel) ? sel.field_path : sel.label}</span>
              </div>

              {isConflict(sel) ? (
                <ConflictEditor
                  item={sel}
                  draft={draft}
                  setDraft={setDraft}
                />
              ) : (
                <FieldEditor item={sel} draft={draft} setDraft={setDraft} />
              )}
            </div>

            {/* action bar */}
            <div className="cur-actions">
              {isConflict(sel) ? (
                <Fragment>
                  <button
                    className="btn btn-confirm"
                    disabled={busy}
                    onClick={() => commitConflict("accept_candidate")}
                  >
                    ✓ Accept candidate
                  </button>
                  {conflictHasExisting(sel) ? (
                    <button
                      className="btn btn-ghost"
                      disabled={busy}
                      onClick={() => commitConflict("kept_existing")}
                    >
                      Keep existing
                    </button>
                  ) : null}
                  <button
                    className="btn btn-ghost"
                    disabled={busy}
                    onClick={() => commitConflict("dropped")}
                  >
                    Drop
                  </button>
                  <div className="spacer" />
                  {flash ? <span className="saved-flash">{flash}</span> : null}
                  <button
                    className="btn btn-dark"
                    disabled={busy}
                    onClick={() => commitConflict()}
                  >
                    Approve &amp; next <span className="k">↵</span>
                  </button>
                </Fragment>
              ) : (
                <Fragment>
                  <button
                    className="btn btn-confirm"
                    disabled={busy}
                    onClick={() => commitField("confirmed")}
                  >
                    ✓ Confirm <span className="k">C</span>
                  </button>
                  <button
                    className="btn btn-ghost"
                    disabled={busy}
                    onClick={() => commitField("not_published")}
                  >
                    Not published <span className="k">N</span>
                  </button>
                  <button
                    className="btn btn-ghost"
                    disabled={busy}
                    onClick={() => commitField("review")}
                  >
                    Flag <span className="k">R</span>
                  </button>
                  <div className="spacer" />
                  {flash ? <span className="saved-flash">{flash}</span> : null}
                  <button
                    className="btn btn-dark"
                    disabled={busy}
                    onClick={() => commitField()}
                  >
                    Save &amp; next <span className="k">↵</span>
                  </button>
                </Fragment>
              )}
            </div>
          </Fragment>
        )}

        {/* drawer toggle — only meaningful at narrow widths (CSS-gated) */}
        <button
          className="cur-drawer-toggle"
          onClick={() => setDrawerOpen((v) => !v)}
        >
          {drawerOpen ? "Hide context ›" : "‹ Context"}
        </button>
      </div>

      {/* ===== provenance / context (RIGHT, collapses to drawer) ===== */}
      <div className={"cur-context" + (drawerOpen ? " open" : "")}>
        <ProvenancePane
          item={sel}
          history={history}
          historyErr={historyErr}
          resolvedCount={resolvedCount}
          onClose={() => setDrawerOpen(false)}
        />
      </div>
      {drawerOpen ? (
        <div className="cur-scrim" onClick={() => setDrawerOpen(false)} />
      ) : null}
    </div>
  );
}

/* ===================== conflict editor ===================== */
function ConflictEditor({ item, draft, setDraft }) {
  const hasExisting = conflictHasExisting(item);
  return (
    <Fragment>
      <h1>{item.field_path}</h1>
      <div className="cur-unit">
        <span className={"qi-kind k-" + item.conflict_kind}>
          {item.conflict_type_label}
        </span>{" "}
        detected {item.detected_at ? item.detected_at.slice(0, 10) : "—"}
      </div>

      <div className="cur-conflict">
        {hasExisting ? (
          <div
            className={"cur-side" + (draft.pick === "existing" ? " on" : "")}
            onClick={() => setDraft({ ...draft, pick: "existing" })}
          >
            <div className="side-h">Existing (in DB)</div>
            <div className="side-v">{fmtVal(item.existing) ?? "—"}</div>
            <div className="side-pick">{draft.pick === "existing" ? "✓ keep this" : "keep this"}</div>
          </div>
        ) : (
          <div className="cur-side empty-side">
            <div className="side-h">Existing (in DB)</div>
            <div className="side-v empty">no current value</div>
          </div>
        )}
        <div className="cur-vs">vs</div>
        <div
          className={"cur-side cand" + (draft.pick === "candidate" ? " on" : "")}
          onClick={() => setDraft({ ...draft, pick: "candidate" })}
        >
          <div className="side-h">Candidate (scraped)</div>
          <div className="side-v">{fmtVal(item.candidate) ?? "—"}</div>
          <div className="side-pick">{draft.pick === "candidate" ? "✓ accept this" : "accept this"}</div>
        </div>
      </div>

      <div className="cur-editor">
        {canEditConflict(item) ? (
          <div className="field-row">
            <div className="el">Correct value</div>
            <input
              className="vinput"
              value={draft.editValue ?? ""}
              placeholder="Type the right value to override both sides…"
              onChange={(e) => setDraft({ ...draft, editValue: e.target.value })}
            />
          </div>
        ) : null}
        <div className="field-row">
          <div className="el">Resolver note</div>
          <input
            className="vinput"
            value={draft.note ?? ""}
            placeholder="Optional — why this resolution?"
            onChange={(e) => setDraft({ ...draft, note: e.target.value })}
          />
        </div>
      </div>
    </Fragment>
  );
}

/* ===================== field-state editor ===================== */
function FieldEditor({ item, draft, setDraft }) {
  const byYear = item.byYearDiff;
  return (
    <Fragment>
      <h1>{item.label}</h1>
      <div className="cur-unit">Field path · {item.field_path}</div>

      {/* hero current value */}
      <div className="cur-hero">
        <div className="hl">
          Current value · <span>{STATE_LABEL[draft.state]}</span>
        </div>
        <div className="hv">
          {!draft.value || draft.state === "not_published" || draft.state === "blank" ? (
            <div className="vbig empty">
              {draft.state === "not_published" ? "Vendor doesn't publish this" : "No value yet"}
            </div>
          ) : (
            <div className="vbig">{draft.value}</div>
          )}
          <span className="st-chip">
            <StateDot s={draft.state} /> {STATE_LABEL[draft.state]}
          </span>
        </div>
      </div>

      {/* across-model-years diff strip */}
      {byYear && Object.keys(byYear).length ? (
        <div className="cur-ydiff">
          <div className="yh">Across model years</div>
          <div className="ytrack">
            <div className="ynode">
              <div className="yy">{item.year}</div>
              <div className="yv">{fmtVal(item.value) ?? "—"}</div>
              <div className="ytag this">this</div>
            </div>
            {Object.keys(byYear)
              .sort()
              .map((y) => (
                <div key={y} className="ynode changed">
                  <div className="yy">{y}</div>
                  <div className="yv">{fmtVal(byYear[y]) ?? "—"}</div>
                  <div className="ytag">changed</div>
                </div>
              ))}
          </div>
        </div>
      ) : null}

      {/* editor */}
      <div className="cur-editor">
        <div className="field-row">
          <div className="el">Value</div>
          <input
            className="vinput"
            value={draft.value ?? ""}
            placeholder={
              draft.state === "not_published"
                ? "Vendor doesn't publish — leave empty"
                : "Enter a value…"
            }
            onChange={(e) => setDraft({ ...draft, value: e.target.value })}
          />
        </div>

        <div className="field-row">
          <div className="el">Value state</div>
          <div className="states">
            {STATE_ORDER.map((s) => (
              <button
                key={s}
                className={"sbtn s-" + s + (draft.state === s ? " on" : "")}
                onClick={() => setDraft({ ...draft, state: s })}
              >
                <StateDot s={s} />
                {STATE_LABEL[s]}
              </button>
            ))}
          </div>
        </div>

        <div className="meta-grid">
          <div>
            <label className="mini-label">Source</label>
            <input
              className="vinput sm"
              value={draft.source ?? ""}
              placeholder="e.g. vendor spec sheet URL"
              onChange={(e) => setDraft({ ...draft, source: e.target.value })}
            />
          </div>
          <div>
            <label className="mini-label">
              Note {draft.state !== "review" ? "(review only)" : ""}
            </label>
            <input
              className="vinput sm"
              value={draft.note ?? ""}
              disabled={draft.state !== "review"}
              placeholder="What needs checking?"
              onChange={(e) => setDraft({ ...draft, note: e.target.value })}
            />
          </div>
        </div>
      </div>
    </Fragment>
  );
}

/* ===================== provenance pane ===================== */
function ProvenancePane({ item, history, historyErr, resolvedCount, onClose }) {
  const [pulling] = useState(false);
  if (!item) {
    return (
      <div className="ctx-empty">
        Select an item to see its source, provenance, and history.
      </div>
    );
  }
  const prov = history ? history.provenance : null;
  return (
    <Fragment>
      <div className="ctx-bar">
        <span className="ctx-title">Provenance</span>
        <button className="ctx-close" onClick={onClose}>
          ×
        </button>
      </div>

      <div className="ctx-sec">
        <div className="ctx-h">Source</div>
        <div className="source-card">
          {historyErr ? (
            <div className="prov-err">No provenance: {historyErr}</div>
          ) : !history ? (
            <div className="prov-loading">Loading provenance…</div>
          ) : (
            <Fragment>
              <div className="url">{prov.source_url || "— no source URL —"}</div>
              <dl className="prov-list">
                <dt>Captured</dt>
                <dd>{prov.captured_at ? prov.captured_at.slice(0, 19).replace("T", " ") : "—"}</dd>
                <dt>Scraper</dt>
                <dd>{prov.scraper_id || "—"}</dd>
                <dt>Status</dt>
                <dd>{prov.status || "—"}</dd>
                <dt>Entered by</dt>
                <dd>{prov.entered_by || "—"}</dd>
                <dt>Entered</dt>
                <dd>{prov.entered_at ? prov.entered_at.slice(0, 19).replace("T", " ") : "—"}</dd>
                {prov.source_note ? (
                  <Fragment>
                    <dt>Source note</dt>
                    <dd>{prov.source_note}</dd>
                  </Fragment>
                ) : null}
                {prov.note ? (
                  <Fragment>
                    <dt>Note</dt>
                    <dd>{prov.note}</dd>
                  </Fragment>
                ) : null}
              </dl>
            </Fragment>
          )}
          <button className={"btn btn-ghost pull-btn" + (pulling ? " loading" : "")} disabled>
            ↻ Pull fresh data
          </button>
          <div className="pull-note">
            Re-scrapes the vendor page (heavy / network). Disabled in this build.
          </div>
        </div>
      </div>

      <div className="ctx-sec">
        <div className="ctx-h">This session</div>
        <div className="session-stat">
          <b>{resolvedCount}</b> resolved
        </div>
      </div>
    </Fragment>
  );
}
