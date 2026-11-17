import pytest

from fabsim.ingest.stations import StationResolver

R = StationResolver()


@pytest.mark.parametrize("label,site,expected", [
    ("CM2-L3-ST02", "CM2", "CM2-L3-ST02"),
    ("cm2_line3_st2", "CM2", "CM2-L3-ST02"),
    ("CM2 L3 Station 2", "CM2", "CM2-L3-ST02"),
    ("cm2-l03-st002", "CM2", "CM2-L3-ST02"),
    ("C2L3S2", "CM2", "CM2-L3-ST02"),
    ("SV Bench 1", "LAB-SV", "LAB-SV-B01"),
    ("sv_bench01", "LAB-SV", "LAB-SV-B01"),
    ("Bench 2", "LAB-RD", "LAB-RD-B02"),
    ("ST-03", "CM1", "CM1-L1-ST03"),          # only line 1 has a station 3, so the line can be inferred
])
def test_resolves(label, site, expected):
    assert R.resolve(label, site).station_id == expected


@pytest.mark.parametrize("label,site,reason", [
    ("ST-01", "CM1", "ambiguous_station"),     # CM1 has a station 1 on two lines: never guess
    ("CM2-L3-ST02", "CM1", "site_conflict"),   # label names a different site than the file came from
    ("CM1-L9-ST01", "CM1", "unknown_station"),
    ("", "CM1", "missing_station"),
    (None, "CM1", "missing_station"),
])
def test_refuses(label, site, reason):
    r = R.resolve(label, site)
    assert r.station_id is None and r.reason == reason
