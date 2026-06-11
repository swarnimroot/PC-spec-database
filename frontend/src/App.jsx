import { useState } from "react";
import Home from "./home/Home.jsx";
import Finder from "./finder/Finder.jsx";
import Compare from "./compare/Compare.jsx";
import Curation from "./curation/Curation.jsx";
import Refresh from "./refresh/Refresh.jsx";
import "./App.css";

const SCREENS = [
  { id: "home", label: "Home" },
  { id: "finder", label: "Spec Finder" },
  { id: "compare", label: "Compare" },
  { id: "curation", label: "Review" },
  { id: "refresh", label: "Add/Refresh" },
];

export default function App() {
  const [screen, setScreen] = useState("home");
  // When navigating to the Finder to open a specific product (e.g. after
  // adding one), stash the catalog id here; Finder consumes it then clears it.
  const [finderDetailId, setFinderDetailId] = useState(null);

  // Navigate by screen id, optionally opening a product detail on arrival.
  const navigate = (id, productId = null) => {
    if (productId != null) setFinderDetailId(productId);
    setScreen(id);
  };

  return (
    <>
      <div className="appnav">
        <button className="brandmark" onClick={() => setScreen("home")}>
          <span className="sq" />
          <span className="t">Comp Database</span>
        </button>
        <nav className="navtabs">
          {SCREENS.map((s) => (
            <button
              key={s.id}
              className={screen === s.id ? "on" : ""}
              onClick={() => setScreen(s.id)}
            >
              {s.label}
            </button>
          ))}
        </nav>
      </div>
      {screen === "home" ? (
        <Home onNavigate={navigate} />
      ) : screen === "finder" ? (
        <Finder
          initialDetailId={finderDetailId}
          onConsumeInitialDetail={() => setFinderDetailId(null)}
        />
      ) : screen === "compare" ? (
        <Compare />
      ) : screen === "curation" ? (
        <Curation />
      ) : (
        <Refresh onNavigate={navigate} />
      )}
    </>
  );
}
