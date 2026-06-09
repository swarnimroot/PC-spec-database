import { useState, useEffect, useMemo, useRef, Fragment } from "react";
import { getCatalog, getSchema } from "../api.js";
import { latestYear, resolve, valArray } from "../shared/data.js";
import ValueCell from "../shared/ValueCell.jsx";
import "./compare.css";

const MAX = 4;

// Normalize a resolved cell to a comparable token for the diff test.
function norm(cell) {
  if (!cell || cell.v == null) return "∅";
  return JSON.stringify(cell.v);
}

const nameOf = (m) => `${m.brand} ${m.series} ${m.model}`;

/* ====================== typeahead (add a model) ====================== */
function Typeahead({ models, onPick, exclude }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [cur, setCur] = useState(0);
  const boxRef = useRef(null);

  const opts = useMemo(() => {
    const t = q.trim().toLowerCase();
    return models
      .filter((m) => !exclude.includes(m.id))
      .map((m) => ({ m, s: nameOf(m).toLowerCase() }))
      .filter((o) => !t || t.split(/\s+/).every((w) => o.s.includes(w)))
      .slice(0, 8);
  }, [q, models, exclude]);

  useEffect(() => {
    setCur(0);
  }, [q]);
  useEffect(() => {
    const h = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const pick = (m) => {
    onPick(m.id);
    setQ("");
    setOpen(false);
  };

  return (
    <div className="add-search" ref={boxRef}>
      <span className="mag">⌕</span>
      <input
        value={q}
        placeholder="Add a model…"
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setCur((c) => Math.min(c + 1, opts.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setCur((c) => Math.max(c - 1, 0));
          } else if (e.key === "Enter" && opts[cur]) {
            pick(opts[cur].m);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {open && (
        <div className="ta-pop">
          {opts.length === 0 ? (
            <div className="ta-empty">No match in catalog</div>
          ) : (
            opts.map((o, i) => (
              <div
                key={o.m.id}
                className={"ta-opt" + (i === cur ? " cursor" : "")}
                onMouseEnter={() => setCur(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(o.m);
                }}
              >
                <span className="bs">
                  {o.m.brand} · {o.m.series}
                </span>
                <span className="md">{o.m.model}</span>
                <span className="seg">{o.m.segment}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/* ====================== column header ====================== */
function ColHead({ model, year, onYear, onRemove }) {
  const single = model.years.length < 2;
  return (
    <div className="colhead">
      <button className="remove" title="Remove" onClick={onRemove}>
        ×
      </button>
      <div className="seg">
        {model.brand} · {model.segment || "—"}
      </div>
      <div className="name">
        <span className="ser">{model.series} </span>
        {model.model}
      </div>
      <div className="updated">Updated {model.updated}</div>
      <div className={"yrs" + (single ? " single" : "")}>
        {model.years.map((y) => (
          <button
            key={y}
            className={y === year ? "active" : ""}
            onClick={() => !single && onYear(y)}
          >
            {y}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ====================== main screen ====================== */
export default function Compare() {
  const [models, setModels] = useState(null);
  const [schema, setSchema] = useState(null);
  const [loadErr, setLoadErr] = useState(null);

  const [cols, setCols] = useState([]); // [{ modelId, year }]
  const [diffOnly, setDiffOnly] = useState(false);
  const [dropping, setDropping] = useState(false);
  const [draggingId, setDraggingId] = useState(null);

  useEffect(() => {
    Promise.all([getCatalog(), getSchema()])
      .then(([cat, sch]) => {
        setModels(cat);
        setSchema(sch);
      })
      .catch((e) => setLoadErr(String(e)));
  }, []);

  const modelById = useMemo(() => {
    const o = new Map();
    (models || []).forEach((m) => o.set(m.id, m));
    return o;
  }, [models]);

  // Seed two columns once the catalog loads, so the screen reads as a matrix.
  useEffect(() => {
    if (models && models.length && cols.length === 0) {
      setCols(
        models.slice(0, 2).map((m) => ({ modelId: m.id, year: latestYear(m) }))
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [models]);

  const used = cols.map((c) => c.modelId);
  const resolved = cols.map((c) => resolve(modelById.get(c.modelId), c.year));

  const addModel = (id) =>
    setCols((cs) => {
      if (cs.length >= MAX || cs.find((c) => c.modelId === id)) return cs;
      const m = modelById.get(id);
      if (!m) return cs;
      return [...cs, { modelId: id, year: latestYear(m) }];
    });
  const removeCol = (i) => setCols((cs) => cs.filter((_, k) => k !== i));
  const setYear = (i, y) =>
    setCols((cs) => cs.map((c, k) => (k === i ? { ...c, year: y } : c)));

  // A field differs when its resolved value isn't identical across all columns.
  const fieldDiff = (key) => {
    if (cols.length < 2) return false;
    const set = new Set(resolved.map((sp) => norm(sp[key])));
    return set.size > 1;
  };

  const cats = schema ? schema.categories : [];
  const totalFields = cats.reduce((n, c) => n + c.fields.length, 0);
  const diffCount = useMemo(
    () =>
      cats.reduce(
        (n, cat) => n + cat.fields.filter((f) => fieldDiff(f.key)).length,
        0
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cats, cols, models]
  );

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
  if (!models || !schema) {
    return <div className="loadstate">Loading catalog…</div>;
  }

  const nCols = cols.length;
  const showAdd = nCols < MAX;

  return (
    <div className="compare-root">
      {/* control bar */}
      <div className="cmp-bar">
        <span className="diffcount">
          <b>{diffCount}</b> of {totalFields} specs differ
        </span>
        <div
          className={"toggle" + (diffOnly ? " on" : "")}
          onClick={() => setDiffOnly((v) => !v)}
        >
          <span className="switch" /> Differences only
        </div>
      </div>

      {/* drag shelf */}
      <div className="shelf">
        <span className="shelf-label">Catalog · drag in</span>
        {models.map((m) => (
          <div
            key={m.id}
            className={
              "chip" +
              (used.includes(m.id) ? " used" : "") +
              (draggingId === m.id ? " dragging" : "")
            }
            draggable={!used.includes(m.id)}
            onDragStart={(e) => {
              e.dataTransfer.setData("text/plain", m.id);
              e.dataTransfer.effectAllowed = "copy";
              setDraggingId(m.id);
            }}
            onDragEnd={() => {
              setDraggingId(null);
              setDropping(false);
            }}
            onClick={() => addModel(m.id)}
            title={
              used.includes(m.id)
                ? "Already in comparison"
                : "Click or drag to add"
            }
          >
            <span className="grip">⠿</span>
            <span className="bs">
              {m.brand}·{m.series}{" "}
            </span>
            <span className="md">{m.model}</span>
          </div>
        ))}
      </div>

      {/* matrix */}
      <div className="matrix-wrap">
        {nCols === 0 ? (
          <div className="empty-state">
            <h2>Nothing to compare yet</h2>
            <p>
              Search, click, or drag models from the catalog above. Up to four
              at a time.
            </p>
          </div>
        ) : (
          <table className="mx">
            <colgroup>
              <col className="label-col" />
              {cols.map((c) => (
                <col key={c.modelId} />
              ))}
              {showAdd ? <col style={{ width: "260px" }} /> : null}
            </colgroup>
            <thead>
              <tr>
                <th className="corner">
                  <div className="corner-inner">
                    <div className="t">
                      {nCols} model{nCols > 1 ? "s" : ""}
                    </div>
                  </div>
                </th>
                {cols.map((c, i) => (
                  <th key={c.modelId}>
                    <ColHead
                      model={modelById.get(c.modelId)}
                      year={c.year}
                      onYear={(y) => setYear(i, y)}
                      onRemove={() => removeCol(i)}
                    />
                  </th>
                ))}
                {showAdd ? (
                  <th>
                    <div
                      className={"addcol" + (dropping ? " dropping" : "")}
                      onDragOver={(e) => {
                        e.preventDefault();
                        e.dataTransfer.dropEffect = "copy";
                        setDropping(true);
                      }}
                      onDragLeave={() => setDropping(false)}
                      onDrop={(e) => {
                        e.preventDefault();
                        const id = e.dataTransfer.getData("text/plain");
                        if (id) addModel(id);
                        setDropping(false);
                        setDraggingId(null);
                      }}
                    >
                      <div className="addcol-inner">
                        <Typeahead
                          models={models}
                          onPick={addModel}
                          exclude={used}
                        />
                        <div className="add-hint">
                          or <b>drop a chip</b> here
                        </div>
                      </div>
                    </div>
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {cats.map((cat) => {
                const fields = cat.fields.filter(
                  (f) => !diffOnly || fieldDiff(f.key)
                );
                if (diffOnly && fields.length === 0) return null;
                return (
                  <Fragment key={cat.id}>
                    <tr className="cat-row">
                      <td colSpan={nCols + (showAdd ? 2 : 1)}>
                        <div className="catwrap">{cat.label}</div>
                      </td>
                    </tr>
                    {fields.map((f) => {
                      const diff = fieldDiff(f.key);
                      return (
                        <tr key={f.key} className={"frow" + (diff ? " diff" : "")}>
                          <td className="lab">{f.label}</td>
                          {cols.map((c, i) => (
                            <td key={c.modelId} className="vcell">
                              <ValueCell cell={resolved[i][f.key]} />
                            </td>
                          ))}
                          {showAdd ? (
                            <td>
                              <div className="vcell addslot" />
                            </td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
