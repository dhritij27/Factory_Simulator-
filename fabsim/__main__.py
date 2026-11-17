"""Command line entry point:  python -m fabsim <command>

  simulate    generate raw vendor exports + ground truth + system of record
  ingest      load new raw files into the lake and rebuild the warehouse
  analyze     Gauge R&R, station correlation, drift detection, Cpk -> findings tables
  backtest    score every component against the planted ground truth -> results/
  agent       ask the calibration agent a question
  agent-eval  run the agent evaluation scenarios
  dashboard   export dashboard JSON
  all         simulate -> ingest -> analyze -> backtest -> dashboard
"""
from __future__ import annotations

import argparse
import time


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="fabsim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("simulate")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--scale", type=float, default=1.0, help="multiplies production volume")
    i = sub.add_parser("ingest")
    i.add_argument("--full", action="store_true", help="discard the lake and re-ingest every file")
    sub.add_parser("analyze")
    b = sub.add_parser("backtest")
    b.add_argument("--no-monte-carlo", action="store_true", help="skip the Gauge R&R CI coverage simulation")
    a = sub.add_parser("agent")
    a.add_argument("question")
    a.add_argument("--rule-based", action="store_true", help="use the deterministic baseline instead of the LLM")
    e = sub.add_parser("agent-eval")
    e.add_argument("--agent", choices=["rule", "llm", "both"], default="rule")
    sub.add_parser("dashboard")
    al = sub.add_parser("all")
    al.add_argument("--seed", type=int, default=7)
    al.add_argument("--scale", type=float, default=1.0)
    al.add_argument("--no-monte-carlo", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()
    if args.cmd in ("simulate", "all"):
        from fabsim.config import SimConfig
        from fabsim.sim.simulate import simulate
        print("simulate")
        out = simulate(SimConfig(seed=args.seed, scale=args.scale))
        print(f"  {out['total_rows']:,} measurement rows")
    if args.cmd in ("ingest", "all"):
        from fabsim.ingest.pipeline import Ingestor
        from fabsim.warehouse.build import build
        print("ingest")
        Ingestor(full=getattr(args, "full", False) or args.cmd == "all").run()
        build()
    if args.cmd in ("analyze", "all"):
        from fabsim.analytics.run import run_all
        print("analyze")
        run_all()
    if args.cmd in ("backtest", "all"):
        from fabsim.backtest.run import run_backtest
        print("backtest")
        run_backtest(monte_carlo=not args.no_monte_carlo)
        from fabsim.backtest.sweep import sweep
        from fabsim.backtest import escalation
        sweep()
        escalation.run(verbose=False)
    if args.cmd in ("dashboard", "all"):
        from fabsim.dashboard_export import export
        print("dashboard")
        export()
    if args.cmd == "agent":
        from fabsim.agent.runtime import ask
        print(ask(args.question, rule_based=args.rule_based))
    if args.cmd == "agent-eval":
        from fabsim.agent.evaluate import run_eval
        run_eval(args.agent)
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
