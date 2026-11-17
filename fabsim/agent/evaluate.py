"""Score agents on the hand-labelled scenarios.

Per scenario:
  decision   the DECISION line matches the hand label
  tools      every required tool was called; no ticket drafted when none is expected
  ticket     for P1-P3, a draft exists for the expected instrument at the expected priority;
             otherwise no draft was created
  grounded   every number/date in the answer appears in a tool result (grounding.py)
A scenario passes only if all four hold.
"""
from __future__ import annotations

import json
import re
import time

from fabsim import jsonsafe
from fabsim.agent import grounding, rule_agent
from fabsim.agent.scenarios import REQUIRED_TOOLS, SCENARIOS, TICKET
from fabsim.agent.world import World
from fabsim.config import RESULTS

DECISION_RE = re.compile(r"DECISION:\s*([A-Z_0-9]+)")


def score(sc: dict, out: dict, world: World) -> dict:
    m = DECISION_RE.findall(out["answer"])
    decision = m[-1] if m else None
    used = {s["name"] for s in out["transcript"] if s["type"] == "tool_use"}
    required = REQUIRED_TOOLS[sc["decision"]]
    drafted = world.created
    tools_ok = required <= used and (sc["decision"] in TICKET or not drafted)
    if sc["decision"] in TICKET:
        ticket_ok = any(t["instrument_id"] == sc["instrument"] and t["priority"] == sc["decision"] for t in drafted)
    else:
        ticket_ok = not drafted
    g = grounding.check(out["answer"], grounding.tool_results_from_transcript(out["transcript"]),
                        sc["question"] + " " + world.as_of.isoformat())
    res = dict(id=sc["id"], expected=sc["decision"], got=decision, decision_ok=decision == sc["decision"],
               tools_ok=tools_ok, missing_tools=sorted(required - used), ticket_ok=ticket_ok,
               grounded=g["grounded"], ungrounded=g["ungrounded"], n_tool_calls=sum(s["type"] == "tool_use" for s in out["transcript"]))
    res["passed"] = res["decision_ok"] and res["tools_ok"] and res["ticket_ok"] and res["grounded"]
    return res


def evaluate(agent: str = "rule", verbose: bool = True) -> dict:
    rows, usage = [], {"input_tokens": 0, "output_tokens": 0}
    client = None
    if agent == "llm":
        import anthropic
        from fabsim.agent import runtime
        client = anthropic.Anthropic()
    t0 = time.time()
    for sc in SCENARIOS:
        world = World.from_fixture(sc["world"])
        if agent == "rule":
            out = rule_agent.run(world, sc["question"])
        else:
            out = runtime.run(world, sc["question"], client=client)
            for k in usage:
                usage[k] += out["usage"][k]
        r = score(sc, out, world)
        r["answer"] = out["answer"]
        rows.append(r)
        if verbose:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"  {sc['id']} {mark}  expected {r['expected']:<15} got {str(r['got']):<15}"
                  + ("" if r["passed"] else f"  tools_ok={r['tools_ok']} ticket_ok={r['ticket_ok']} "
                                            f"grounded={r['grounded']} {r['ungrounded'] or ''} {r['missing_tools'] or ''}"))
    n = len(rows)
    summary = dict(agent=agent, scenarios=n,
                   passed=sum(r["passed"] for r in rows),
                   decision_accuracy=sum(r["decision_ok"] for r in rows) / n,
                   tool_selection=sum(r["tools_ok"] for r in rows) / n,
                   ticket_correct=sum(r["ticket_ok"] for r in rows) / n,
                   grounded=sum(r["grounded"] for r in rows) / n,
                   seconds=round(time.time() - t0, 1),
                   usage=usage if agent == "llm" else None)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"agent_eval_{agent}.json").write_text(jsonsafe.dumps(dict(summary=summary, rows=rows), indent=2))
    if verbose:
        print(f"\n{agent}: {summary['passed']}/{n} passed | decision {100*summary['decision_accuracy']:.0f}% | "
              f"tools {100*summary['tool_selection']:.0f}% | ticket {100*summary['ticket_correct']:.0f}% | "
              f"grounded {100*summary['grounded']:.0f}%")
    return summary


def run_eval(which: str = "rule") -> None:
    for a in (["rule", "llm"] if which == "both" else [which]):
        evaluate(a)
