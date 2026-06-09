import { useState, useEffect, useRef } from "react";
import { latestYear } from "../shared/data.js";

// ⌘K command palette — jump to a model or toggle a facet. Lifted from the
// prototype, now driven by live models + facets.
export default function Palette({
  models,
  facets,
  selKeys,
  onClose,
  onOpenModel,
  onToggleFacet,
}) {
  const [q, setQ] = useState("");
  const [cur, setCur] = useState(0);
  const inputRef = useRef(null);
  useEffect(() => {
    inputRef.current && inputRef.current.focus();
  }, []);

  const t = q.trim().toLowerCase();
  const modelItems = models
    .map((m) => ({
      type: "model",
      id: m.id,
      title: (m.series ? m.series + " " : "") + m.model,
      sub: m.brand + " · " + (m.segment || "—"),
      s: (m.brand + " " + (m.series || "") + " " + m.model).toLowerCase(),
    }))
    .filter((x) => !t || t.split(/\s+/).every((w) => x.s.includes(w)));

  const filterItems = [];
  facets.forEach((g) =>
    g.options.forEach((o) =>
      filterItems.push({
        type: "filter",
        key: g.id + ":" + o.id,
        title: o.label,
        sub: g.label,
        s: (g.label + " " + o.label).toLowerCase(),
        active: selKeys.has(g.id + ":" + o.id),
      })
    )
  );
  const fFilter = filterItems.filter((x) => !t || x.s.includes(t));

  const flat = [
    ...modelItems.map((x) => ({ ...x, grp: "Models" })),
    ...fFilter.map((x) => ({ ...x, grp: "Add filter" })),
  ];
  useEffect(() => {
    setCur(0);
  }, [q]);

  const choose = (it) => {
    if (!it) return;
    if (it.type === "model") onOpenModel(it.id);
    else onToggleFacet(it.key);
    onClose();
  };

  let idx = -1;
  const groups = ["Models", "Add filter"];
  return (
    <div className="palette-scrim" onMouseDown={onClose}>
      <div className="palette" onMouseDown={(e) => e.stopPropagation()}>
        <div className="palette-in">
          <span className="mag">⌕</span>
          <input
            ref={inputRef}
            value={q}
            placeholder="Search models or jump to a spec filter…"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCur((c) => Math.min(c + 1, flat.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCur((c) => Math.max(c - 1, 0));
              } else if (e.key === "Enter") {
                choose(flat[cur]);
              } else if (e.key === "Escape") {
                onClose();
              }
            }}
          />
        </div>
        <div className="palette-list">
          {flat.length === 0 ? (
            <div className="pgroup-h">No matches</div>
          ) : (
            groups.map((gname) => {
              const items = flat.filter((x) => x.grp === gname);
              if (!items.length) return null;
              return (
                <div key={gname}>
                  <div className="pgroup-h">{gname}</div>
                  {items.map((it) => {
                    idx++;
                    const myIdx = idx;
                    return (
                      <div
                        key={it.type + (it.id || it.key)}
                        className={"pitem" + (myIdx === cur ? " cursor" : "")}
                        onMouseEnter={() => setCur(myIdx)}
                        onMouseDown={() => choose(it)}
                      >
                        <span className="pico">
                          {it.type === "model" ? "▤" : "+"}
                        </span>
                        <span className="pmain">
                          <span className="ptitle">{it.title}</span>{" "}
                          <span className="psub">{it.sub}</span>
                        </span>
                        {it.type === "filter" && it.active ? (
                          <span className="ptag">active</span>
                        ) : null}
                        {it.type === "model" ? (
                          <span className="ptag">open</span>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>
        <div className="palette-foot">
          <span>
            <span className="kbd">↑↓</span> navigate
          </span>
          <span>
            <span className="kbd">↵</span> select
          </span>
          <span>
            <span className="kbd">esc</span> close
          </span>
        </div>
      </div>
    </div>
  );
}
