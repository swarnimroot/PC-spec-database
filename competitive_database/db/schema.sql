-- Schema for competitive-database (Stage 1).
-- All bundle/array columns are TEXT (SQLite stores JSON as text). All nullable
-- unless otherwise stated. PK columns are plain scalars; everything else is a
-- JSON provenance bundle (or a JSON array of dicts of bundles).

CREATE TABLE IF NOT EXISTS cpu_catalog (
    model           TEXT PRIMARY KEY,
    catalog_status  TEXT NOT NULL DEFAULT 'needs-review',
    brand           TEXT,
    architecture    TEXT,
    cores           TEXT,
    npu_tops        TEXT,
    base_clock      TEXT,
    boost_clock     TEXT,
    process_node    TEXT,
    nominal_tdp     TEXT
);

CREATE TABLE IF NOT EXISTS gpu_catalog (
    model           TEXT PRIMARY KEY,
    catalog_status  TEXT NOT NULL DEFAULT 'needs-review',
    brand           TEXT,
    architecture    TEXT,
    cuda_cores      TEXT,
    vram_base       TEXT,
    base_clock      TEXT,
    boost_clock     TEXT
);

CREATE TABLE IF NOT EXISTS products (
    -- Identity (PK columns are plain scalars)
    model_code      TEXT NOT NULL,
    year            INTEGER NOT NULL,

    -- Identity (bundles)
    vendor_full_name TEXT,
    brand            TEXT,
    sub_brand        TEXT,
    series           TEXT,
    status           TEXT,
    segment          TEXT,

    -- CPU
    cpu_offerings    TEXT,
    cpu_tdp_max      TEXT,

    -- GPU / power
    boards           TEXT,

    -- Display
    display_offerings TEXT,

    -- Battery
    battery_offerings TEXT,

    -- Memory
    memory_max_gb        TEXT,
    memory_speed_mts     TEXT,
    memory_slots         TEXT,
    memory_type          TEXT,
    memory_overclocking  TEXT,

    -- Thermals
    thermal_design   TEXT,
    thermal_material TEXT,
    tim              TEXT,
    fan_count        TEXT,

    -- Dimensions
    width_mm         TEXT,
    depth_mm         TEXT,
    height_mm_min    TEXT,
    height_mm_max    TEXT,

    -- Weight
    weight_kg_min    TEXT,
    weight_kg_max    TEXT,

    -- Keyboard
    keyboard_offerings TEXT,

    -- Storage
    storage_slots    TEXT,
    storage_max_gb   TEXT,

    -- Network
    wifi_standard      TEXT,
    ethernet           TEXT,
    bluetooth_version  TEXT,

    -- I/O (split into scalar columns)
    usbc_thunderbolt_count        TEXT,
    usbc_thunderbolt_version      TEXT,
    usbc_non_thunderbolt_count    TEXT,
    usbc_non_thunderbolt_version  TEXT,
    usba_count                    TEXT,
    usba_version                  TEXT,
    hdmi_count                    TEXT,
    hdmi_version                  TEXT,
    sd_card                       TEXT,
    sd_card_speed                 TEXT,
    audio_jack                    TEXT,

    -- Adapter
    adapter_offerings  TEXT,
    adapter_connector  TEXT,

    -- Camera
    camera_offerings   TEXT,

    -- Audio
    speaker_count    TEXT,
    tuning_brand     TEXT,
    has_subwoofer    TEXT,

    -- Design
    a_cover_material TEXT,
    c_cover_material TEXT,
    d_cover_material TEXT,
    thermal_shelf    TEXT,
    lighting         TEXT,

    PRIMARY KEY (model_code, year)
);

CREATE TABLE IF NOT EXISTS review_queue (
    id                    INTEGER PRIMARY KEY,
    product_model_code    TEXT,
    product_year          INTEGER,
    field_path            TEXT,
    conflict_type         TEXT,
    existing_value        TEXT,
    existing_provenance   TEXT,
    candidate_value       TEXT,
    candidate_provenance  TEXT,
    detected_at           TIMESTAMP,
    resolved_at           TIMESTAMP,
    resolution            TEXT,
    resolution_value      TEXT,
    resolver_note         TEXT
);

-- Indexes on bundle columns use json_extract on the '$.value' path.
CREATE INDEX IF NOT EXISTS idx_products_brand
    ON products(json_extract(brand, '$.value'));
CREATE INDEX IF NOT EXISTS idx_products_year
    ON products(year);
CREATE INDEX IF NOT EXISTS idx_products_status
    ON products(json_extract(status, '$.value'));
CREATE INDEX IF NOT EXISTS idx_products_segment
    ON products(json_extract(segment, '$.value'));

CREATE INDEX IF NOT EXISTS idx_cpu_catalog_brand
    ON cpu_catalog(json_extract(brand, '$.value'));
CREATE INDEX IF NOT EXISTS idx_cpu_catalog_status
    ON cpu_catalog(catalog_status);

CREATE INDEX IF NOT EXISTS idx_gpu_catalog_brand
    ON gpu_catalog(json_extract(brand, '$.value'));
CREATE INDEX IF NOT EXISTS idx_gpu_catalog_status
    ON gpu_catalog(catalog_status);

CREATE INDEX IF NOT EXISTS idx_review_queue_unresolved
    ON review_queue(resolved_at);
CREATE INDEX IF NOT EXISTS idx_review_queue_product
    ON review_queue(product_model_code, product_year);
