from fabsim.agent import grounding, rule_agent, tools
from fabsim.agent.evaluate import evaluate
from fabsim.agent.world import World

RESULTS = [{"cert_id": "CERT-CLR-CM2-L3-ST02", "expires_on": "2026-07-14", "days_until_expiry": 9,
            "recent_shift_sigma": 2.37, "window_start": "2026-07-06T22:00"}]


def test_grounded_answer_passes():
    a = "CLR-CM2-L3-ST02 expires 2026-07-14 (9 days). Shift 2.4 sigma. Window 2026-07-06T22:00. DECISION: P1"
    assert grounding.check(a, RESULTS, "drift on CM2-L3-ST02?")["grounded"]


def test_invented_date_is_caught():
    a = "The certificate expires 2026-07-21. DECISION: P1"
    assert grounding.check(a, RESULTS, "")["ungrounded"] == ["2026-07-21"]


def test_invented_number_is_caught():
    a = "Recent shift is 3.1 sigma and 45 units failed. DECISION: P2"
    assert set(grounding.check(a, RESULTS, "")["ungrounded"]) == {"3.1", "45"}


def test_digits_inside_ids_dont_count():
    a = "CM2-L3-ST02 / CAM-CM1-0107 / P1 / TKT-D0042. DECISION: P1"
    assert grounding.check(a, [], "")["grounded"]


def test_no_duplicate_tickets():
    w = World.from_fixture({"tickets": [{"instrument_id": "CAM-CM1-L1-ST01", "status": "open"}]})
    r = tools.draft_maintenance_ticket(w, "CAM-CM1-L1-ST01", "P2", "x")
    assert r["error"] == "duplicate" and not w.created


def test_ambiguous_label_is_not_resolved():
    assert tools.resolve_station(World.from_fixture({}), "ST-02")["error"] == "ambiguous"


def test_rule_baseline_passes_all_scenarios():
    s = evaluate("rule", verbose=False)
    assert s["passed"] == s["scenarios"] == 46
