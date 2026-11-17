"""Vendor schema contracts and the schema-drift detector.

Each vendor format has a contract: the fields we expect. Every file's observed
fields are compared to it. Differences become issues, and an issue is never
silently fixed: a renamed field only loads if a human approved that rename in
config/schema_mappings.json, and the first sighting raises an alert either way.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass

from fabsim.config import SCHEMA_MAPPINGS

CONTRACTS: dict[str, list[str]] = {
    "cm1_csv": ["timestamp", "station", "unit_sn", "instrument", "operator", "test_type", "eye", "metric", "value"],
    "cm2_jsonl": ["ts", "station_name", "serial", "op", "kind", "trial", "instruments", "results",
                  "results.mtf50", "results.lum_uniformity", "results.delta_uv", "results.vert_misalign"],
    "cm3_xlsx": ["Date", "Time", "Station", "SN", "Type", "Operator", "Trial", "Cam_ID", "Clr_ID", "Aln_ID",
                 "MTF50_L", "MTF50_R", "LumUnif_L", "LumUnif_R", "dUV_L", "dUV_R", "VertMisalign"],
    "lab_csv": ["MeasDateTime", "Bench", "DUT", "Inst", "Tech", "Purpose", "Trial", "Param", "Side", "Reading"],
}
# Fields the loader cannot do without. Losing any of these quarantines the whole file.
REQUIRED: dict[str, set[str]] = {
    "cm1_csv": {"timestamp", "station", "unit_sn", "metric", "eye", "value"},
    "cm2_jsonl": {"ts", "station_name", "serial", "results"},
    "cm3_xlsx": {"Date", "Time", "Station", "SN"},
    "lab_csv": {"MeasDateTime", "Bench", "DUT", "Param", "Side", "Reading"},
}


@dataclass
class SchemaIssue:
    kind: str          # unexpected_field | missing_field | approved_rename | column_order_changed
    field: str
    severity: str      # info | warning | error
    detail: str


def load_mappings() -> dict[str, dict[str, str]]:
    if not SCHEMA_MAPPINGS.exists():
        return {}
    raw = json.loads(SCHEMA_MAPPINGS.read_text())
    return {v: {k: e["maps_to"] for k, e in m.items()} for v, m in raw.items() if not v.startswith("_")}


def check_schema(vendor: str, observed: list[str], mappings: dict[str, dict[str, str]] | None = None,
                 ordered: bool = False) -> tuple[dict[str, str], list[SchemaIssue]]:
    """Return (rename map to apply, issues). ``observed`` keeps file order when ``ordered``."""
    mappings = load_mappings() if mappings is None else mappings
    contract = CONTRACTS[vendor]
    approved = mappings.get(vendor, {})
    rename: dict[str, str] = {}
    issues: list[SchemaIssue] = []
    seen = set()
    unexpected = []
    for f in observed:
        if f in contract:
            seen.add(f)
        elif f in approved:
            rename[f] = approved[f]
            seen.add(approved[f])
            issues.append(SchemaIssue("approved_rename", f, "info", f"'{f}' loaded as '{approved[f]}' (approved mapping)"))
        else:
            unexpected.append(f)
    missing = [c for c in contract if c not in seen]
    for f in unexpected:
        guess = difflib.get_close_matches(f.lower().replace("_", ""), [m.lower().replace("_", "") for m in missing], n=1, cutoff=0.6)
        hint = ""
        if guess:
            orig = next(m for m in missing if m.lower().replace("_", "") == guess[0])
            hint = f"; looks like a rename of '{orig}' (not approved, data not loaded)"
        issues.append(SchemaIssue("unexpected_field", f, "warning", f"field '{f}' is not in the {vendor} contract{hint}"))
    for f in missing:
        sev = "error" if f in REQUIRED[vendor] or f.startswith("results.") else "warning"
        issues.append(SchemaIssue("missing_field", f, sev, f"expected field '{f}' is missing"))
    if ordered:
        present = [rename.get(f, f) for f in observed if rename.get(f, f) in contract]
        expect = [c for c in contract if c in present]
        if present != expect:
            issues.append(SchemaIssue("column_order_changed", "*", "info", "columns are in a different order"))
    return rename, issues
