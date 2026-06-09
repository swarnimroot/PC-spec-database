import { useState } from "react";
import Finder from "./finder/Finder.jsx";
import Compare from "./compare/Compare.jsx";
import Curation from "./curation/Curation.jsx";
import "./App.css";

const SCREENS = [
  { id: "finder", label: "Spec Finder" },
  { id: "compare", label: "Compare" },
  { id: "curation", label: "Curation" },
];

export default function App() {
  const [screen, setScreen] = useState("finder");
  return (
    <>
      <div className="appnav">
        <div className="brandmark">
          <span className="sq" />
          <span className="t">Comp Database</span>
        </div>
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
      {screen === "finder" ? (
        <Finder />
      ) : screen === "compare" ? (
        <Compare />
      ) : (
        <Curation />
      )}
    </>
  );
}
