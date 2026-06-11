import { useState, useEffect, useMemo } from "react";
import { getCatalog, postRefresh } from "../api.js";
import AddProduct from "./AddProduct.jsx";
import "./refresh.css";

const SUPPORTED = ["dell", "hp", "lenovo", "asus"];

const TOTAL_LABELS = [
  ["inserted_fields", "New fields"],
  ["refreshed_fields", "Refreshed"],
  ["conflicts", "Conflicts"],
  ["low_confidence", "Low confidence"],
  ["year_inferred", "Year inferred"],
  ["new_cpus", "New CPUs"],
  ["new_gpus", "New GPUs"],
];

export default function Refresh({ onNavigate } = {}) {
  const [catalog, setCatalog] = useState([]);
  const [catalogErr, setCatalogErr] = useState("");
  const [mode, setMode] = useState("all"); // "all" | "one"
  const [selectedId, setSelectedId] = useState("");
  const [selectedYear, setSelectedYear] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => {
    getCatalog()
      .then((rows) => setCatalog(rows))
      .catch((e) => setCatalogErr(String(e.message || e)));
  }, []);

  // Only products from a supported vendor can be re-scraped.
  const eligible = useMemo(
    () =>
      catalog
        .filter((p) => p.brand && SUPPORTED.includes(p.brand.toLowerCase()))
        .sort((a, b) => (a.model || "").localeCompare(b.model || "")),
    [catalog]
  );

  const selected = eligible.find((p) => p.id === selectedId) || null;
  const years = selected?.years || [];

  // Keep the year selector valid whenever the product changes.
  useEffect(() => {
    if (!selected) return;
    if (!years.includes(Number(selectedYear))) {
      setSelectedYear(years.length ? String(Math.max(...years)) : "");
    }
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  const canRun =
    mode === "all" || (mode === "one" && selectedId && selectedYear);

  function ask() {
    setError("");
    setResult(null);
    setConfirming(true);
  }

  async function run() {
    setConfirming(false);
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const payload =
        mode === "all"
          ? { all: true }
          : {
              brand: selected.brand.toLowerCase(),
              model: selected.id,
              from_db: true,
              year: Number(selectedYear),
            };
      const res = await postRefresh(payload);
      setResult(res);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="refresh">
      <div className="rf-head">
        <div className="rf-head-top">
          <h1>Refresh</h1>
          <button className="ap-primary" onClick={() => setShowAdd(true)}>
            + Add new
          </button>
        </div>
        <p>
          Re-fetch the latest specs from vendor sites (Dell, HP, Lenovo, ASUS)
          and update the database. Changed values are not overwritten — they go
          to the <strong>Curation</strong> queue for you to review.
        </p>
        <p className="rf-warn">
          This reaches out to live vendor websites and can take several minutes
          for a full refresh. Leave the tab open while it runs.
        </p>
      </div>

      <div className="rf-card">
        <div className="rf-modes">
          <label className={mode === "all" ? "on" : ""}>
            <input
              type="radio"
              name="mode"
              checked={mode === "all"}
              onChange={() => setMode("all")}
              disabled={running}
            />
            <span className="rf-mode-t">All eligible products</span>
            <span className="rf-mode-d">
              Every Dell / HP / Lenovo / ASUS product with a stored source link
              ({eligible.length})
            </span>
          </label>
          <label className={mode === "one" ? "on" : ""}>
            <input
              type="radio"
              name="mode"
              checked={mode === "one"}
              onChange={() => setMode("one")}
              disabled={running}
            />
            <span className="rf-mode-t">One product</span>
            <span className="rf-mode-d">Pick a single product to re-fetch</span>
          </label>
        </div>

        {mode === "one" && (
          <div className="rf-pickers">
            <label>
              Product
              <select
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
                disabled={running}
              >
                <option value="">Select a product…</option>
                {eligible.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.brand} — {p.model}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Year
              <select
                value={selectedYear}
                onChange={(e) => setSelectedYear(e.target.value)}
                disabled={running || !selected}
              >
                {!selected && <option value="">—</option>}
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {catalogErr && <div className="rf-err">Couldn’t load catalog: {catalogErr}</div>}

        {!running && (
          <button className="rf-run" onClick={ask} disabled={!canRun}>
            Run refresh
          </button>
        )}

        {running && (
          <div className="rf-running">
            <span className="rf-spinner" />
            Fetching from vendor sites… this can take a while.
          </div>
        )}
      </div>

      {confirming && (
        <div className="rf-modal-backdrop" onClick={() => setConfirming(false)}>
          <div className="rf-modal" onClick={(e) => e.stopPropagation()}>
            <h2 className="rf-modal-title">Run refresh?</h2>
            <p className="rf-modal-msg">
              {mode === "all"
                ? `This reaches out to live vendor websites and re-fetches specs for all ${eligible.length} eligible products. It can take several minutes.`
                : `This reaches out to the live vendor website and re-fetches specs for ${selected?.brand} — ${selected?.model} (${selectedYear}).`}
            </p>
            <div className="rf-modal-btns">
              <button className="rf-cancel" onClick={() => setConfirming(false)}>
                Cancel
              </button>
              <button className="rf-run" onClick={run}>
                Yes, fetch now
              </button>
            </div>
          </div>
        </div>
      )}

      {error && <div className="rf-err rf-err-block">Refresh failed: {error}</div>}

      {result && <Results result={result} />}

      {showAdd && (
        <AddProduct
          onClose={() => setShowAdd(false)}
          onViewProduct={(modelCode) => {
            setShowAdd(false);
            // Reuse the Finder's product Detail slide-over: navigate to the
            // Finder and ask it to open this product (catalog id = model_code).
            onNavigate?.("finder", modelCode);
          }}
        />
      )}
    </div>
  );
}

function totalsOf(result) {
  return result.totals || {};
}

function Results({ result }) {
  const totals = totalsOf(result);
  const isAll = Array.isArray(result.per_product);
  const conflicts = Number(totals.conflicts || 0);

  return (
    <div className="rf-results">
      <h2>Done</h2>

      {isAll && (
        <div className="rf-rollup">
          <span className="ok">{result.refreshed_count ?? 0} refreshed</span>
          <span className="muted">{result.skipped_count ?? 0} skipped</span>
          <span className={result.error_count ? "bad" : "muted"}>
            {result.error_count ?? 0} errors
          </span>
        </div>
      )}

      <div className="rf-stats">
        {TOTAL_LABELS.map(([k, label]) => (
          <div className="rf-stat" key={k}>
            <span className="n">{totals[k] ?? 0}</span>
            <span className="l">{label}</span>
          </div>
        ))}
      </div>

      {conflicts > 0 && (
        <div className="rf-note">
          {conflicts} conflict{conflicts === 1 ? "" : "s"} found — open the{" "}
          <strong>Curation</strong> screen to review them.
        </div>
      )}

      {isAll && result.errors?.length > 0 && (
        <div className="rf-block">
          <h3>Errors ({result.errors.length})</h3>
          <ul className="rf-list">
            {result.errors.map((e, i) => (
              <li key={i}>
                <span className="rf-pk">
                  {e.brand} {e.model_code} ({e.year})
                </span>
                <span className="rf-emsg">{e.error}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {isAll && result.skipped?.length > 0 && (
        <details className="rf-block">
          <summary>Skipped ({result.skipped.length})</summary>
          <ul className="rf-list">
            {result.skipped.map((s, i) => (
              <li key={i}>
                <span className="rf-pk">
                  {s.brand || "no brand"} {s.model_code} ({s.year})
                </span>
                <span className="rf-emsg">{s.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
