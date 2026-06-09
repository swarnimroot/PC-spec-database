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
  { id: "refresh", label: "Refresh" },
];

export default function App() {
  const [screen, setScreen] = useState("home");
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
        <Home onNavigate={setScreen} />
      ) : screen === "finder" ? (
        <Finder />
      ) : screen === "compare" ? (
        <Compare />
      ) : screen === "curation" ? (
        <Curation />
      ) : (
        <Refresh />
      )}
    </>
  );
}
