import {
  latestYear,
  resolve,
  lead,
  changedInfo,
} from "../shared/data.js";

// Key specs shown on each result card; `group` ties a column to a facet group
// so the matched spec highlights. display:true builds a sub-line.
const STRIP = [
  { k: "processor", label: "CPU", group: null },
  { k: "graphics", label: "GPU", group: "gpu" },
  { k: "display", label: "Display", group: "panel", display: true },
  { k: "memory", label: "Memory", group: "mem" },
  { k: "weight", label: "Weight", group: "weight" },
  { k: "network", label: "Wi-Fi", group: "wifi" },
];

export default function ResultRow({ m, activeGroups, showState, onOpen }) {
  const sp = resolve(m, latestYear(m));
  return (
    <div className="res" onClick={() => onOpen(m.id)}>
      <div className="res-id">
        <div className="seg">
          {m.brand} · {m.segment || "—"}
        </div>
        <div className="nm">
          <span className="ser">{m.series ? m.series + " " : ""}</span>
          {m.model}
        </div>
        <div className="yrs">
          {m.years.map((y) => (
            <span key={y} className="yrtag">
              {y}
            </span>
          ))}
        </div>
      </div>
      <div className="specstrip">
        {STRIP.map((item) => {
          const cell = sp[item.k];
          const isMatch = item.group && activeGroups.has(item.group);
          const ch = changedInfo(m, item.k);
          const l = lead(cell);
          let sub = null;
          if (item.display && cell && cell.v != null) {
            // display rollup already a rich string; show nothing extra
            sub = null;
          }
          return (
            <div className="spec" key={item.k}>
              <div className="k">{item.label}</div>
              {l == null ? (
                <div className="v blank">
                  {cell && cell.s === "not_published"
                    ? "not published"
                    : "—"}
                </div>
              ) : (
                <div className={"v" + (isMatch ? " match" : "")}>
                  {showState && cell.s === "hand" ? (
                    <span className="dotmk dotmk--hand" />
                  ) : null}
                  {showState && cell.s === "review" ? (
                    <span className="dotmk dotmk--review" />
                  ) : null}
                  <span className="vt">{l}</span>
                  {ch ? (
                    <span
                      className="changed"
                      title={ch.oldYear + ": " + (ch.oldLead || "—")}
                    >
                      →{String(ch.year).slice(2)}
                    </span>
                  ) : null}
                </div>
              )}
              {sub ? <div className="sub">{sub}</div> : null}
            </div>
          );
        })}
      </div>
      <div className="res-go">›</div>
    </div>
  );
}
