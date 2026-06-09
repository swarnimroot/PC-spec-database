// Facet groups mapped to REAL catalog fields (live joined-string rollups).
//
// Prototype facets vs. our mapping:
//   Brand           -> m.brand                            (kept)
//   Use case        -> m.segment (ROG/Legion/Alienware/OMEN/HyperX) (kept; renamed "Sub-brand")
//   Wi-Fi           -> network rollup, contains Wi-Fi 7 / 6E         (kept)
//   Display / OLED  -> display rollup, contains "OLED"               (kept)
//   Graphics        -> graphics rollup is set / empty (discrete vs unspecified) (adapted)
//   Memory          -> memory rollup, "up to NGB" parsed             (kept)
//   Refresh rate    -> display rollup, max "NHz" parsed              (kept)
//   Ports           -> io_hdmi (has HDMI) + io_sd_card (card reader) (kept)
//   IPS panel       -> dropped (panel sub-type only cleanly exposes OLED in rollup)
//   Touchscreen     -> dropped (no touch field in the rollup sections)
//
// Each option has pred(spec, model) -> boolean, run against the latest-year spec.

import { cellHas, lead, maxHz, maxMemGb } from "../shared/data.js";

const hasGraphics = (sp) => {
  const c = sp.graphics;
  return !!(c && c.v != null);
};

export const FACETS = [
  {
    id: "brand",
    label: "Brand",
    dynamic: "brand",
  },
  {
    id: "segment",
    label: "Sub-brand",
    dynamic: "segment",
  },
  {
    id: "wifi",
    label: "Wi-Fi",
    options: [
      { id: "w7", label: "Wi-Fi 7", pred: (s) => cellHas(s.network, "Wi-Fi 7") },
      { id: "w6e", label: "Wi-Fi 6E", pred: (s) => cellHas(s.network, "6E") },
    ],
  },
  {
    id: "panel",
    label: "Display",
    options: [
      { id: "oled", label: "OLED", pred: (s) => cellHas(s.display, "OLED") },
    ],
  },
  {
    id: "gpu",
    label: "Graphics",
    options: [
      { id: "disc", label: "Discrete board", pred: (s) => hasGraphics(s) },
      { id: "none", label: "No board listed", pred: (s) => !hasGraphics(s) },
    ],
  },
  {
    id: "mem",
    label: "Memory",
    options: [
      { id: "m128", label: "128 GB option", pred: (s) => maxMemGb(s.memory) >= 128 },
      { id: "m64", label: "64 GB+ option", pred: (s) => maxMemGb(s.memory) >= 64 },
    ],
  },
  {
    id: "refresh",
    label: "Refresh rate",
    options: [
      { id: "r240", label: "240 Hz", pred: (s) => maxHz(s.display) >= 240 },
      { id: "r165", label: "165 Hz+", pred: (s) => maxHz(s.display) >= 165 },
    ],
  },
  {
    id: "ports",
    label: "Ports",
    options: [
      { id: "hdmi", label: "HDMI", pred: (s) => cellHas(s.io_hdmi, "×") && !cellHas(s.io_hdmi, "0×") },
      {
        id: "sd",
        label: "Card reader",
        pred: (s) => {
          const v = lead(s.io_sd_card);
          return v != null && v !== "none" && v !== "—";
        },
      },
    ],
  },
];

// Build the concrete facet list (resolve dynamic brand/segment options).
export function buildFacets(models) {
  return FACETS.map((g) => {
    if (g.dynamic === "brand") {
      const brands = [...new Set(models.map((m) => m.brand))].sort();
      return {
        ...g,
        options: brands.map((b) => ({
          id: b,
          label: b,
          pred: (_s, m) => m.brand === b,
        })),
      };
    }
    if (g.dynamic === "segment") {
      const segs = [
        ...new Set(models.map((m) => m.segment).filter(Boolean)),
      ].sort();
      return {
        ...g,
        options: segs.map((s) => ({
          id: s,
          label: s,
          pred: (_sp, m) => m.segment === s,
        })),
      };
    }
    return g;
  });
}
