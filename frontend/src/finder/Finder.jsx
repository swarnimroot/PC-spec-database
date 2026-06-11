import { useState, useEffect, useMemo, useRef } from "react";
import { getCatalog, find as apiFind } from "../api.js";
import {
  latestYear,
  earliestYear,
  resolve,
  lead,
  changedInfo,
  weightKg,
  modelTail,
} from "../shared/data.js";
import { buildFacets } from "./facets.js";
import { ADVANCED_FIELDS, OPERATORS } from "./advancedFields.js";
import ResultRow from "./ResultRow.jsx";
import Detail from "./Detail.jsx";
import Palette from "./Palette.jsx";
import "./finder.css";

const WEIGHT_MAX = 4.4; // live max ≈ 4.34 kg

export default function Finder({ initialDetailId, onConsumeInitialDetail } = {}) {
  const [models, setModels] = useState(null);
  const [loadErr, setLoadErr] = useState(null);

  const [selKeys, setSelKeys] = useState(new Set());
  const [maxW, setMaxW] = useState(WEIGHT_MAX);
  const [sort, setSort] = useState("name");
  const [showState, setShowState] = useState(false);
  const [detailId, setDetailId] = useState(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const [mode, setMode] = useState("facets"); // "facets" | "advanced"
  const [advField, setAdvField] = useState(ADVANCED_FIELDS[0].path);
  const [advOp, setAdvOp] = useState("is_empty");
  const [advValue, setAdvValue] = useState("");
  const [advResult, setAdvResult] = useState(null); // {matches, count} | null
  const [advBusy, setAdvBusy] = useState(false);
  const [advErr, setAdvErr] = useState(null);

  useEffect(() => {
    getCatalog()
      .then(setModels)
      .catch((e) => setLoadErr(String(e)));
  }, []);

  // Open a product detail requested by another screen (e.g. Add product →
  // "View product"), then clear it so it fires once.
  useEffect(() => {
    if (initialDetailId != null) {
      setDetailId(initialDetailId);
      onConsumeInitialDetail?.();
    }
  }, [initialDetailId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const h = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const facets = useMemo(
    () => (models ? buildFacets(models) : []),
    [models]
  );
  const facetByGroup = useMemo(() => {
    const o = {};
    facets.forEach((g) => (o[g.id] = g));
    return o;
  }, [facets]);

  const optByKey = (key) => {
    const [g, o] = key.split(":");
    const grp = facetByGroup[g];
    if (!grp) return null;
    return { grp, opt: grp.options.find((x) => x.id === o) };
  };

  const toggle = (key) =>
    setSelKeys((s) => {
      const n = new Set(s);
      n.has(key) ? n.delete(key) : n.add(key);
      return n;
    });
  const clearAll = () => {
    setSelKeys(new Set());
    setMaxW(WEIGHT_MAX);
  };

  const passes = (m) => {
    const sp = resolve(m, latestYear(m));
    for (const grp of facets) {
      const sel = grp.options.filter((o) => selKeys.has(grp.id + ":" + o.id));
      if (sel.length && !sel.some((o) => o.pred(sp, m))) return false;
    }
    if (maxW < WEIGHT_MAX) {
      const w = weightKg(sp.weight);
      if (w != null && w > maxW) return false;
    }
    return true;
  };

  const baseFor = (groupId) => {
    if (!models) return [];
    return models.filter((m) => {
      const sp = resolve(m, latestYear(m));
      for (const grp of facets) {
        if (grp.id === groupId) continue;
        const sel = grp.options.filter((o) => selKeys.has(grp.id + ":" + o.id));
        if (sel.length && !sel.some((o) => o.pred(sp, m))) return false;
      }
      if (maxW < WEIGHT_MAX) {
        const w = weightKg(sp.weight);
        if (w != null && w > maxW) return false;
      }
      return true;
    });
  };

  const results = useMemo(() => {
    if (!models) return [];
    let r = models.filter(passes);
    const wt = (m) => weightKg(resolve(m, latestYear(m)).weight) ?? 99;
    if (sort === "name")
      r = [...r].sort((a, b) =>
        (a.brand + a.series + a.model).localeCompare(b.brand + b.series + b.model)
      );
    else if (sort === "weight") r = [...r].sort((a, b) => wt(a) - wt(b));
    else if (sort === "brand")
      r = [...r].sort(
        (a, b) =>
          a.brand.localeCompare(b.brand) ||
          (a.series || "").localeCompare(b.series || "")
      );
    else if (sort === "updated")
      r = [...r].sort((a, b) =>
        (b.updated || "").localeCompare(a.updated || "")
      );
    return r;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [models, selKeys, maxW, sort]);

  const activeGroups = useMemo(() => {
    const g = new Set();
    selKeys.forEach((k) => g.add(k.split(":")[0]));
    if (maxW < WEIGHT_MAX) g.add("weight");
    return g;
  }, [selKeys, maxW]);

  const activeChips = [...selKeys]
    .map((k) => {
      const r = optByKey(k);
      if (!r || !r.opt) return null;
      return { key: k, grp: r.grp.label, label: r.opt.label };
    })
    .filter(Boolean);

  const runAdvanced = () => {
    setAdvBusy(true);
    setAdvErr(null);
    apiFind({ field_path: advField, operator: advOp, value: advValue })
      .then((res) => setAdvResult(res))
      .catch((e) => {
        setAdvErr(String(e));
        setAdvResult(null);
      })
      .finally(() => setAdvBusy(false));
  };

  const opNeedsValue =
    OPERATORS.find((o) => o.op === advOp)?.needsValue ?? false;

  // Map advanced result model_codes -> catalog model objects (by id, else
  // fall back to showing the raw id when the row isn't the latest-year head).
  const advModels = useMemo(() => {
    if (!advResult || !models) return [];
    const byId = new Map(models.map((m) => [m.id, m]));
    return advResult.matches.map((mt) => ({
      match: mt,
      model: byId.get(mt.id) || null,
    }));
  }, [advResult, models]);

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
  if (!models) {
    return <div className="loadstate">Loading catalog…</div>;
  }

  return (
    <>
      <div className="topbar">
        <div className="brandmark">
          <span className="sq" />
          <span className="t">Comp Database</span>
          <span className="verb">Spec Finder</span>
        </div>
        <div className="modeswitch">
          <button
            className={mode === "facets" ? "on" : ""}
            onClick={() => setMode("facets")}
          >
            Facets
          </button>
          <button
            className={mode === "advanced" ? "on" : ""}
            onClick={() => setMode("advanced")}
          >
            Advanced
          </button>
        </div>
        <div className="spacer" />
        <div
          className={"statetoggle" + (showState ? " on" : "")}
          onClick={() => setShowState((v) => !v)}
        >
          <span className="box">{showState ? "✓" : ""}</span> Show data state
        </div>
        <div className="kbtn" onClick={() => setPaletteOpen(true)}>
          <span className="mag">⌕</span> Jump to anything{" "}
          <span className="kbd">⌘K</span>
        </div>
      </div>

      {mode === "facets" ? (
        <div className="body">
          <div className="rail">
            <div className="rail-head">
              <h2>Filter the catalog</h2>
              {selKeys.size || maxW < WEIGHT_MAX ? (
                <span className="clearall" onClick={clearAll}>
                  Clear all
                </span>
              ) : null}
            </div>
            {facets.map((grp) => {
              const base = baseFor(grp.id);
              return (
                <div className="facet" key={grp.id}>
                  <div className="facet-h">{grp.label}</div>
                  {grp.options.map((o) => {
                    const sel = selKeys.has(grp.id + ":" + o.id);
                    const cnt = base.filter((m) =>
                      o.pred(resolve(m, latestYear(m)), m)
                    ).length;
                    return (
                      <div
                        key={o.id}
                        className={
                          "opt" +
                          (sel ? " sel" : "") +
                          (cnt === 0 && !sel ? " zero" : "")
                        }
                        onClick={() => toggle(grp.id + ":" + o.id)}
                      >
                        <span className="box" />
                        <span className="lbl">{o.label}</span>
                        <span className="cnt">{cnt}</span>
                      </div>
                    );
                  })}
                </div>
              );
            })}
            <div className="facet">
              <div className="facet-h">Weight</div>
              <div className="slider-wrap">
                <div className="slider-val">
                  {maxW >= WEIGHT_MAX ? (
                    "Any weight"
                  ) : (
                    <span>
                      Up to <b>{maxW.toFixed(2)} kg</b>
                    </span>
                  )}
                </div>
                <input
                  type="range"
                  min="1.0"
                  max={WEIGHT_MAX}
                  step="0.05"
                  value={maxW}
                  onChange={(e) => setMaxW(parseFloat(e.target.value))}
                />
              </div>
            </div>
          </div>

          <div className="results">
            <div className="querybar">
              <div className="count">
                {results.length} <span>of {models.length} models</span>
              </div>
              <div className="chips">
                {activeChips.map((c) => (
                  <span className="qchip" key={c.key}>
                    <span className="grp">{c.grp}</span>
                    {c.label}
                    <button onClick={() => toggle(c.key)}>×</button>
                  </span>
                ))}
                {maxW < WEIGHT_MAX ? (
                  <span className="qchip">
                    <span className="grp">Weight</span>≤ {maxW.toFixed(2)} kg
                    <button onClick={() => setMaxW(WEIGHT_MAX)}>×</button>
                  </span>
                ) : null}
              </div>
              <select
                className="sortsel"
                value={sort}
                onChange={(e) => setSort(e.target.value)}
              >
                <option value="name">Sort: Name</option>
                <option value="weight">Sort: Lightest</option>
                <option value="brand">Sort: Brand</option>
                <option value="updated">Sort: Recently updated</option>
              </select>
            </div>
            <div className="reslist">
              {results.length === 0 ? (
                <div className="noresults">
                  <h3>No models match</h3>
                  <p>
                    Loosen a filter — the counts in the rail show what's
                    reachable.
                  </p>
                </div>
              ) : (
                results.map((m) => (
                  <ResultRow
                    key={m.id}
                    m={m}
                    activeGroups={activeGroups}
                    showState={showState}
                    onOpen={setDetailId}
                  />
                ))
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="advbody">
          <div className="advquery">
            <h2>Advanced query</h2>
            <p className="advhint">
              The power path: any field, any operator. Runs against{" "}
              <code>POST /api/find</code> on the live DB — including{" "}
              <b>is empty</b>, <b>vendor doesn't publish</b>, and numeric{" "}
              <b>≥ / ≤</b> on any field.
            </p>
            <div className="advrow">
              <label>Field</label>
              <select
                value={advField}
                onChange={(e) => setAdvField(e.target.value)}
              >
                {ADVANCED_FIELDS.map((f) => (
                  <option key={f.path} value={f.path}>
                    {f.section} · {f.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="advrow">
              <label>Operator</label>
              <select
                value={advOp}
                onChange={(e) => setAdvOp(e.target.value)}
              >
                {OPERATORS.map((o) => (
                  <option key={o.op} value={o.op}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="advrow">
              <label>Value</label>
              <input
                value={advValue}
                disabled={!opNeedsValue}
                placeholder={opNeedsValue ? "e.g. 64" : "— not needed —"}
                onChange={(e) => setAdvValue(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runAdvanced()}
              />
            </div>
            <button className="advrun" onClick={runAdvanced} disabled={advBusy}>
              {advBusy ? "Running…" : "Run query"}
            </button>
            {advErr ? <div className="adverr">{advErr}</div> : null}
          </div>
          <div className="advresults">
            {advResult == null ? (
              <div className="noresults">
                <h3>Run a query to see matches</h3>
                <p>
                  Try <b>Weight min (kg)</b> · <b>vendor doesn't publish</b>, or{" "}
                  <b>Memory max (GB)</b> · <b>≥</b> · <b>64</b>.
                </p>
              </div>
            ) : (
              <>
                <div className="advcount">
                  {advResult.count} match
                  {advResult.count !== 1 ? "es" : ""}{" "}
                  <span>(product-year rows)</span>
                </div>
                <div className="advlist">
                  {advResult.matches.map((mt, i) => {
                    const m = advModels[i].model;
                    return (
                      <div
                        className={"advcard" + (m ? " clickable" : "")}
                        key={mt.id + ":" + i}
                        onClick={() => m && setDetailId(m.id)}
                      >
                        <div className="advcard-id">
                          {m ? (
                            <>
                              <span className="ser">{m.series || m.brand}</span>{" "}
                              {modelTail(m.series, m.model)}
                              <span className="seg">
                                {m.brand} · {m.segment || "—"}
                              </span>
                            </>
                          ) : (
                            <span className="rawid">{mt.id}</span>
                          )}
                        </div>
                        <div className="advcard-val">
                          <span className="mk">{mt.marker}</span>
                          {mt.value}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {detailId ? (
        <Detail id={detailId} onClose={() => setDetailId(null)} />
      ) : null}
      {paletteOpen ? (
        <Palette
          models={models}
          facets={facets}
          selKeys={selKeys}
          onClose={() => setPaletteOpen(false)}
          onOpenModel={setDetailId}
          onToggleFacet={toggle}
        />
      ) : null}
    </>
  );
}

export { WEIGHT_MAX };
