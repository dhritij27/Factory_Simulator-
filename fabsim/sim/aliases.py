"""How each vendor writes station names, and the variants operators type by hand."""
from __future__ import annotations

from fabsim.config import Station


def primary_alias(st: Station, vendor_format: str) -> str:
    n, line = st.number, st.line
    site_num = st.site_id[-1] if not st.is_lab else ""
    if vendor_format == "cm1_csv":
        return st.station_id                                   # CM1-L1-ST02
    if vendor_format == "cm2_jsonl":
        return f"cm{site_num}_line{line}_st{n}"                # cm2_line3_st4
    if vendor_format == "cm3_xlsx":
        return f"CM{site_num} L{line} Station {n}"             # CM3 L1 Station 2
    lab = st.site_id.split("-")[1]                             # SV / RD
    return f"{lab} Bench {n}"                                  # SV Bench 1


def variant_aliases(st: Station) -> list[str]:
    """Other spellings seen in the wild. Some are only resolvable with site context,
    and the bare ``ST-0n`` form is ambiguous when two lines share a station number."""
    n, line = st.number, st.line
    if st.is_lab:
        lab = st.site_id.split("-")[1]
        return [st.station_id, f"{lab.lower()}_bench{n:02d}", f"Bench {n}", f"LAB {lab} B{n}"]
    c = st.site_id[-1]
    return [
        st.station_id,
        f"cm{c}_line{line}_st{n}",
        f"CM{c} L{line} Station {n}",
        f"cm{c}-l{line:02d}-st{n:03d}",
        f"C{c}L{line}S{n}",
        f"ST-{n:02d}",
    ]
