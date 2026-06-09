import { useState, useEffect } from "react";
import { getModel, getSchema } from "../api.js";
import {
  latestYear,
  earliestYear,
  resolve,
  changedKeys,
  STATE_LABEL,
  modelTail,
} from "../shared/data.js";
import ValueCell from "../shared/ValueCell.jsx";

let _schemaCache = null;

// Per-model detail slide-over. Fetches the full model object + schema fresh so
// it always reflects live data (and confirms /api/model wiring).
export default function Detail({ id, onClose }) {
  const [m, setM] = useState(null);
  const [schema, setSchema] = useState(_schemaCache);
  const [err, setErr] = useState(null);
  const [year, setYear] = useState(null);

  useEffect(() => {
    let alive = true;
    Promise.all([
      getModel(id),
      _schemaCache ? Promise.resolve(_schemaCache) : getSchema(),
    ])
      .then(([model, sch]) => {
        if (!alive) return;
        _schemaCache = sch;
        setM(model);
        setSchema(sch);
        setYear(latestYear(model));
      })
      .catch((e) => alive && setErr(String(e)));
    return () => {
      alive = false;
    };
  }, [id]);

  return (
    <>
      <div className="dscrim" onClick={onClose} />
      <div className="detail">
        {err ? (
          <div className="detail-head">
            <button className="close" onClick={onClose}>
              ×
            </button>
            <p className="adverr">{err}</p>
          </div>
        ) : !m || !schema ? (
          <div className="detail-head">
            <button className="close" onClick={onClose}>
              ×
            </button>
            <p>Loading…</p>
          </div>
        ) : (
          <DetailBody
            m={m}
            schema={schema}
            year={year}
            setYear={setYear}
            onClose={onClose}
          />
        )}
      </div>
    </>
  );
}

function DetailBody({ m, schema, year, setYear, onClose }) {
  const sp = resolve(m, year);
  const changed =
    m.years.length > 1
      ? new Set(changedKeys(m, earliestYear(m), latestYear(m)))
      : new Set();
  return (
    <>
      <div className="detail-head">
        <button className="close" onClick={onClose}>
          ×
        </button>
        <div className="seg">
          {m.brand} · {m.segment || "—"} · updated {m.updated || "—"}
        </div>
        <h2>
          <span className="ser">{m.series ? m.series + " " : ""}</span>
          {modelTail(m.series, m.model)}
        </h2>
        <div className="yrs">
          {m.years.map((y) => (
            <button
              key={y}
              className={y === year ? "active" : ""}
              onClick={() => setYear(y)}
            >
              {y}
            </button>
          ))}
        </div>
        {m.years.length > 1 ? (
          <span className="changecount">
            {changed.size} field{changed.size !== 1 ? "s" : ""} change across
            years
          </span>
        ) : null}
      </div>
      <div className="detail-body">
        {schema.categories.map((cat) => (
          <div className="dcat" key={cat.id}>
            <div className="dcat-h">{cat.label}</div>
            {cat.fields.map((f) => {
              const cell = sp[f.key];
              const prov = cell
                ? cell.v != null
                  ? STATE_LABEL[cell.s]
                  : cell.s === "not_published"
                  ? "Vendor doesn't publish this"
                  : "No value captured yet"
                : "No value captured yet";
              return (
                <div className="drow" key={f.key}>
                  <div className="dk">{f.label}</div>
                  <div className="dv" title={prov}>
                    <ValueCell cell={cell} />
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </>
  );
}
