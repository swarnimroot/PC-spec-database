import { useState, useEffect, useMemo } from "react";
import { getCatalog, getQueueCounts } from "../api.js";
import "./home.css";

// Per-session: sessionStorage clears when the tab/session ends, so the modal
// shows once per new visit session rather than once ever.
const WELCOME_KEY = "cdb_welcome_seen";

const CARDS = [
  {
    id: "finder",
    title: "Spec Finder",
    desc: "Search products by any spec — find every laptop that matches a value.",
  },
  {
    id: "compare",
    title: "Compare",
    desc: "Line products up side by side and read their specs in one matrix.",
  },
  {
    id: "curation",
    title: "Review",
    desc: "Resolve conflicts, verify flagged values, and fill gaps.",
  },
  {
    id: "refresh",
    title: "Refresh",
    desc: "Re-fetch the latest specs from vendor sites and update the database.",
  },
];

export default function Home({ onNavigate }) {
  const [catalog, setCatalog] = useState(null);
  const [counts, setCounts] = useState(null);
  const [err, setErr] = useState("");
  const [showWelcome, setShowWelcome] = useState(false);

  useEffect(() => {
    if (!sessionStorage.getItem(WELCOME_KEY)) setShowWelcome(true);
    Promise.all([getCatalog(), getQueueCounts()])
      .then(([cat, cnt]) => {
        setCatalog(cat);
        setCounts(cnt);
      })
      .catch((e) => setErr(String(e.message || e)));
  }, []);

  const vendors = useMemo(() => {
    if (!catalog) return 0;
    return new Set(catalog.map((p) => p.brand).filter(Boolean)).size;
  }, [catalog]);

  function dismissWelcome() {
    sessionStorage.setItem(WELCOME_KEY, "1");
    setShowWelcome(false);
  }

  const stats = [
    { n: catalog?.length, l: "Products", to: "finder" },
    { n: vendors || null, l: "Vendors", to: "finder" },
    { n: counts?.conflicts, l: "Conflicts", warn: counts?.conflicts > 0, to: "curation" },
    { n: counts?.review, l: "Unverified", warn: counts?.review > 0, to: "curation" },
  ];

  return (
    <div className="home">
      <div className="hm-hero">
        <h1>Comp Database</h1>
        <p>Track and compare gaming-laptop specs across vendors.</p>
      </div>

      {err && <div className="hm-err">Couldn’t load status: {err}</div>}

      <div className="hm-stats">
        {stats.map((s) => (
          <button
            className={"hm-stat" + (s.warn ? " warn" : "")}
            key={s.l}
            onClick={() => onNavigate(s.to)}
          >
            <span className="n">{s.n == null ? "—" : s.n}</span>
            <span className="l">{s.l}</span>
          </button>
        ))}
      </div>

      <div className="hm-cards">
        {CARDS.map((c) => (
          <button className="hm-card" key={c.id} onClick={() => onNavigate(c.id)}>
            <span className="t">{c.title}</span>
            <span className="d">{c.desc}</span>
          </button>
        ))}
      </div>

      {showWelcome && (
        <div className="hm-modal-backdrop" onClick={dismissWelcome}>
          <div className="hm-modal" onClick={(e) => e.stopPropagation()}>
            <h2>Welcome 👋</h2>
            <p>
              This is your competitive spec database for gaming laptops. Here’s
              what each screen does:
            </p>
            <ul>
              <li>
                <strong>Spec Finder</strong> — search products by any spec value.
              </li>
              <li>
                <strong>Compare</strong> — line products up side by side.
              </li>
              <li>
                <strong>Review</strong> — resolve conflicts and verify values.
              </li>
              <li>
                <strong>Refresh</strong> — pull the latest specs from vendor
                sites.
              </li>
            </ul>
            <button className="hm-modal-btn" onClick={dismissWelcome}>
              Get started
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
