from fabsim.ingest.schema import CONTRACTS, check_schema


def test_clean_file_has_no_issues():
    rename, issues = check_schema("cm3_xlsx", CONTRACTS["cm3_xlsx"], mappings={})
    assert rename == {} and issues == []


def test_unapproved_rename_is_flagged_not_applied():
    obs = [c if c != "SN" else "Serial No." for c in CONTRACTS["cm3_xlsx"]]
    rename, issues = check_schema("cm3_xlsx", obs, mappings={})
    kinds = {(i.kind, i.field, i.severity) for i in issues}
    assert rename == {}
    assert ("unexpected_field", "Serial No.", "warning") in kinds
    assert ("missing_field", "SN", "error") in kinds


def test_approved_rename_loads_but_still_alerts():
    obs = [c if c != "SN" else "Serial No." for c in CONTRACTS["cm3_xlsx"]]
    rename, issues = check_schema("cm3_xlsx", obs, mappings={"cm3_xlsx": {"Serial No.": "SN"}})
    assert rename == {"Serial No.": "SN"}
    assert [i.kind for i in issues] == ["approved_rename"]


def test_additive_column_and_reorder():
    obs = ["station", "timestamp"] + [c for c in CONTRACTS["cm1_csv"] if c not in ("station", "timestamp")] + ["fw_version"]
    _, issues = check_schema("cm1_csv", obs, mappings={}, ordered=True)
    assert {i.kind for i in issues} == {"unexpected_field", "column_order_changed"}
