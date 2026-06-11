import { useState, useEffect } from "react";
import {
  getVendors,
  postProductScrape,
  postProductAdd,
} from "../api.js";
import "./addProduct.css";

// Multi-step "Add product" modal: pick vendor -> paste URL -> scrape preview
// -> confirm -> success. Single modal, internal step state. All network calls
// surface their error inline (no silent swallow). State resets on close.
//
// CSS gotcha: component CSS is bundled into one global sheet, so every class
// here is prefixed `ap-` to avoid colliding with `hm-`/`rf-` etc.
export default function AddProduct({ onClose, onViewProduct }) {
  const [step, setStep] = useState(1);

  // step 1
  const [vendors, setVendors] = useState(null);
  const [vendorsErr, setVendorsErr] = useState("");
  const [vendor, setVendor] = useState(null);

  // step 2
  const [url, setUrl] = useState("");
  const [scraping, setScraping] = useState(false);
  const [scrapeErr, setScrapeErr] = useState("");

  // step 3
  const [token, setToken] = useState(null);
  const [products, setProducts] = useState([]);
  // Editable product names, keyed by `${model_code}|${year}`. Seeded from each
  // scrape preview's `name` (which falls back to the model_code) when the
  // preview arrives; the user can edit before saving.
  const [names, setNames] = useState({});
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState("");

  // step 4
  const [added, setAdded] = useState([]);

  useEffect(() => {
    getVendors()
      .then((rows) => setVendors(rows))
      .catch((e) => setVendorsErr(String(e.message || e)));
  }, []);

  function pickVendor(v) {
    setVendor(v);
    setStep(2);
  }

  async function scrape() {
    setScraping(true);
    setScrapeErr("");
    try {
      const res = await postProductScrape({ brand: vendor.brand, url: url.trim() });
      const prods = res.products || [];
      setToken(res.token);
      setProducts(prods);
      // Seed editable names from each preview (name falls back to model_code).
      const seed = {};
      for (const p of prods) {
        seed[p.model_code + "|" + p.year] = p.name || p.model_code;
      }
      setNames(seed);
      setStep(3);
    } catch (e) {
      setScrapeErr(String(e.message || e));
    } finally {
      setScraping(false);
    }
  }

  function backToPaste() {
    // Discard the pending preview; the token stays server-side until expiry.
    setToken(null);
    setProducts([]);
    setNames({});
    setSaveErr("");
    setStep(2);
  }

  function nameKey(p) {
    return p.model_code + "|" + p.year;
  }
  function setName(key, value) {
    setNames((prev) => ({ ...prev, [key]: value }));
  }

  const saveable = products.filter((p) => !p.already_exists);
  const allExist = products.length > 0 && saveable.length === 0;

  async function save() {
    if (!token) return;
    setSaving(true);
    setSaveErr("");
    try {
      // Build the names dict from trimmed inputs, only for products we'll
      // actually save (skip already-existing PKs). Empty inputs are omitted so
      // the backend keeps the model_code default.
      const namePayload = {};
      for (const p of saveable) {
        const key = nameKey(p);
        const trimmed = (names[key] || "").trim();
        if (trimmed) namePayload[key] = trimmed;
      }
      const res = await postProductAdd({ token, names: namePayload });
      setAdded(res.items || []);
      setStep(4);
    } catch (e) {
      setSaveErr(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  // Map a just-added item back to a label + the catalog id used for "View
  // product" (catalog id is the model_code).
  function addedLabel(item) {
    // Prefer the name the backend actually applied to products.product.
    if (item.product) return item.product;
    const match = products.find(
      (p) => p.model_code === item.model_code && p.year === item.year
    );
    if (match?.name) return match.name;
    return `${item.model_code} (${item.year})`;
  }

  const insertedItems = added.filter((i) => i.inserted);

  return (
    <div className="ap-modal-backdrop" onClick={onClose}>
      <div className="ap-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ap-head">
          <h2>Add a product</h2>
          <button className="ap-x" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="ap-steps">
          {["Company", "Find URL", "Preview", "Done"].map((label, i) => {
            const n = i + 1;
            return (
              <span
                key={label}
                className={
                  "ap-step" +
                  (step === n ? " on" : "") +
                  (step > n ? " done" : "")
                }
              >
                <span className="ap-step-n">{n}</span>
                {label}
              </span>
            );
          })}
        </div>

        {/* Step 1 — pick company */}
        {step === 1 && (
          <div className="ap-body">
            <p className="ap-lead">Which company makes the laptop?</p>
            {vendorsErr && (
              <div className="ap-err">Couldn’t load companies: {vendorsErr}</div>
            )}
            {!vendors && !vendorsErr && (
              <div className="ap-muted">Loading companies…</div>
            )}
            {vendors && (
              <div className="ap-vendors">
                {vendors.map((v) => (
                  <button
                    key={v.brand}
                    className="ap-vendor"
                    onClick={() => pickVendor(v)}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Step 2 — navigate + paste */}
        {step === 2 && vendor && (
          <div className="ap-body">
            <p className="ap-lead">
              Open the <strong>{vendor.label}</strong> site, find your product,
              copy its URL, and paste it below.
            </p>
            {vendor.links?.length > 0 && (
              <div className="ap-sitelinks">
                {vendor.links.map((lnk) => (
                  <a
                    key={lnk.url}
                    className="ap-sitelink"
                    href={lnk.url}
                    target="_blank"
                    rel="noopener"
                  >
                    Open {lnk.label} site ↗
                  </a>
                ))}
              </div>
            )}
            <input
              className="ap-input"
              type="url"
              value={url}
              placeholder="Paste the product URL here"
              onChange={(e) => setUrl(e.target.value)}
              disabled={scraping}
            />
            {scrapeErr && <div className="ap-err">{scrapeErr}</div>}
            <div className="ap-actions">
              <button className="ap-secondary" onClick={() => setStep(1)} disabled={scraping}>
                Back
              </button>
              <button
                className="ap-primary"
                onClick={scrape}
                disabled={!url.trim() || scraping}
              >
                {scraping ? "Scraping…" : "Scrape"}
              </button>
            </div>
            {scraping && (
              <div className="ap-running">
                <span className="ap-spinner" />
                Fetching from {vendor.label}… this can take about a minute. Leave
                this open.
              </div>
            )}
          </div>
        )}

        {/* Step 3 — preview + confirm */}
        {step === 3 && (
          <div className="ap-body">
            <p className="ap-lead">
              Found {products.length} product{products.length === 1 ? "" : "s"}.
              Review and save.
            </p>
            <div className="ap-cards">
              {products.map((p, i) => {
                const s = p.summary || {};
                return (
                  <div
                    className={"ap-card" + (p.already_exists ? " exists" : "")}
                    key={p.model_code + ":" + p.year + ":" + i}
                  >
                    <div className="ap-card-h">
                      <span className="ap-card-name">{p.name || p.model_code}</span>
                      {p.already_exists && (
                        <span className="ap-badge">Already in your database</span>
                      )}
                    </div>
                    <div className="ap-card-meta">
                      <span className="ap-code">{p.model_code}</span>
                      <span>·</span>
                      <span>{p.year}</span>
                    </div>
                    {!p.already_exists && (
                      <label className="ap-namefield">
                        <span className="ap-namefield-label">Product name</span>
                        <input
                          className="ap-name-input"
                          type="text"
                          value={names[nameKey(p)] ?? ""}
                          placeholder={p.model_code}
                          onChange={(e) => setName(nameKey(p), e.target.value)}
                          disabled={saving}
                        />
                      </label>
                    )}
                    <dl className="ap-specs">
                      <SpecRow label="CPU" value={s.cpu} />
                      <SpecRow label="GPU" value={s.gpu} />
                      <SpecRow
                        label="RAM"
                        value={
                          s.memory_max_gb != null
                            ? `up to ${s.memory_max_gb} GB`
                            : null
                        }
                      />
                      <SpecRow
                        label="Storage"
                        value={
                          s.storage_max_gb != null
                            ? `${s.storage_max_gb} GB`
                            : null
                        }
                      />
                      <SpecRow label="Display" value={s.display} />
                    </dl>
                  </div>
                );
              })}
            </div>

            {allExist && (
              <div className="ap-note">
                Every product here is already in your database — nothing to add.
              </div>
            )}
            {saveErr && <div className="ap-err">{saveErr}</div>}

            <div className="ap-actions">
              <button className="ap-secondary" onClick={backToPaste} disabled={saving}>
                Back
              </button>
              <button
                className="ap-primary"
                onClick={save}
                disabled={saving || allExist || saveable.length === 0}
              >
                {saving
                  ? "Saving…"
                  : `Save ${saveable.length} to database`}
              </button>
            </div>
          </div>
        )}

        {/* Step 4 — success */}
        {step === 4 && (
          <div className="ap-body">
            {insertedItems.length === 0 ? (
              <p className="ap-lead">
                Nothing new was added — everything was already in your database.
              </p>
            ) : (
              <>
                <p className="ap-lead">Added to your database:</p>
                <ul className="ap-added">
                  {added.map((item, i) => (
                    <li key={item.model_code + ":" + item.year + ":" + i}>
                      {item.inserted ? (
                        <>
                          <span className="ap-check">✓</span>
                          <span className="ap-added-name">{addedLabel(item)}</span>
                          <button
                            className="ap-link"
                            onClick={() => onViewProduct(item.model_code)}
                          >
                            View product →
                          </button>
                        </>
                      ) : (
                        <>
                          <span className="ap-skip">—</span>
                          <span className="ap-added-name">
                            {addedLabel(item)} (already existed)
                          </span>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <div className="ap-actions">
              <button className="ap-primary" onClick={onClose}>
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SpecRow({ label, value }) {
  return (
    <>
      <dt>{label}</dt>
      <dd className={value == null ? "ap-blank" : ""}>{value == null ? "—" : value}</dd>
    </>
  );
}
