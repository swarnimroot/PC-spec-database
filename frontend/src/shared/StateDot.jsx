// StateDot — the 5 value-state marks (provenance at a glance).
// Reused by the Finder result strip, detail slide-over, and later screens.

const STATE_DOT = {
  confirmed: { background: "#1F8A3F" },
  hand: { background: "#fff", border: "1.5px solid #B8BAC4" },
  review: { background: "#E0A526" },
  not_published: { background: "transparent", border: "1.5px dotted #9A9DAA" },
  blank: { background: "transparent", border: "1.5px dashed #9A9DAA" },
};

export default function StateDot({ s }) {
  return (
    <span
      className="st-dot"
      style={{
        width: 7,
        height: 7,
        borderRadius: "50%",
        flex: "none",
        display: "inline-block",
        boxSizing: "border-box",
        ...(STATE_DOT[s] || STATE_DOT.blank),
      }}
    />
  );
}
