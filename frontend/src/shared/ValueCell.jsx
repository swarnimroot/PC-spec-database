// ValueCell — renders a spec value object: lead value + alt options, with
// blank / not-published handling. Shared primitive for grids & detail rows.

import StateDot from "./StateDot.jsx";
import { valArray } from "./data.js";

export default function ValueCell({ cell, showDot = true }) {
  const vals = valArray(cell);
  if (!vals) {
    const np = cell && cell.s === "not_published";
    return (
      <div className="vc-blank">
        {np ? "vendor doesn't publish" : "missing"}
      </div>
    );
  }
  return (
    <div className="vc">
      {vals.map((v, i) => (
        <div className={i === 0 ? "vc-lead" : "vc-alt"} key={i}>
          {i === 0 && showDot ? <StateDot s={cell.s} /> : null}
          <span>{v}</span>
        </div>
      ))}
    </div>
  );
}
