"""Command line: two steps with the founder in between.

  python -m ied.cli analyse  --data data/sample --run runs/demo
      -> runs/demo/analysis.json, runs/demo/evidence.md, runs/demo/decisions.todo.json  (then STOPS)
  (founder edits decisions.todo.json -> decisions.json: decision + reason for every hypothesis)
  python -m ied.cli finish   --run runs/demo
      -> runs/demo/memo.md, runs/demo/run.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .llm import Ledger, build_router
from .pipeline import (CheckpointIncomplete, analyse, load_hypotheses, load_interviews, memo, next_questions,
                       require_decisions, save_run)
from .schemas import Evidence, HumanDecision, HypothesisSummary
from .report import evidence_markdown


def _dump_state(state: dict, n: int) -> dict:
    return {"n_interviews": n, "processed": state["processed"], "unused_numbers": state.get("unused_numbers", []),
            "kept": [e.model_dump() for e in state["kept"]],
            "dropped": [e.model_dump() for e in state["dropped"]],
            "summaries": [s.model_dump() for s in state["summaries"]]}


def _load_state(d: dict) -> dict:
    return {"kept": [Evidence(**e) for e in d["kept"]], "dropped": [Evidence(**e) for e in d["dropped"]],
            "summaries": [HypothesisSummary(**s) for s in d["summaries"]], "processed": d["processed"],
            "unused_numbers": d.get("unused_numbers", [])}


def cmd_analyse(a) -> int:
    data, run = Path(a.data), Path(a.run)
    interviews, hyps = load_interviews(data / "interviews"), load_hypotheses(data / "hypotheses.json")
    ledger = Ledger()
    router = build_router(a.backends, ledger)
    state = analyse(router, interviews, hyps, progress=lambda f, m: print(f"[{f:4.0%}] {m}", file=sys.stderr))
    run.mkdir(parents=True, exist_ok=True)
    (run / "analysis.json").write_text(json.dumps({**_dump_state(state, len(interviews)),
                                                   "usage": ledger.totals(),
                                                   "calls": [c.__dict__ for c in ledger.calls]}, indent=2), encoding="utf-8")
    (run / "evidence.md").write_text(evidence_markdown(state, len(interviews)), encoding="utf-8")
    todo = [{"hypothesis_id": s.hypothesis.id, "statement": s.hypothesis.statement, "lean": s.lean,
             "decision": "accept | reject | doubt", "reason": ""} for s in state["summaries"]]
    (run / "decisions.todo.json").write_text(json.dumps(todo, indent=2), encoding="utf-8")
    print(f"\nHUMAN CHECKPOINT: read {run/'evidence.md'}, then save your decisions as {run/'decisions.json'} "
          f"(copy decisions.todo.json; one decision and a reason per hypothesis) and run `finish`.")
    print(json.dumps(ledger.totals(), indent=2))
    return 0


def cmd_finish(a) -> int:
    run = Path(a.run)
    saved = json.loads((run / "analysis.json").read_text(encoding="utf-8"))
    state = _load_state(saved)
    try:
        raw = json.loads((run / "decisions.json").read_text(encoding="utf-8"))
        decisions = [HumanDecision(hypothesis_id=d["hypothesis_id"], decision=d["decision"], reason=d["reason"]) for d in raw]
        by_id = require_decisions(state["summaries"], decisions)
    except FileNotFoundError:
        print("No decisions.json yet - the agent will not continue without the founder's decisions.", file=sys.stderr)
        return 2
    except (CheckpointIncomplete, ValueError) as e:
        print(f"Checkpoint incomplete: {e}", file=sys.stderr)
        return 2
    ledger = Ledger()
    router = build_router(a.backends, ledger)
    questions, rejected_q = next_questions(router, state["summaries"], by_id)
    state["rejected_questions"] = rejected_q
    md = memo(state["summaries"], by_id, questions, a.founder, saved["n_interviews"], len(state["dropped"]),
              rejected_questions=len(rejected_q))
    (run / "memo.md").write_text(md, encoding="utf-8")
    usage = saved["usage"]
    t2 = ledger.totals()
    total = {k: usage[k] + t2[k] for k in ("calls", "failed_calls", "prompt_tokens", "completion_tokens", "seconds")}
    total["backends"] = sorted(set(usage["backends"]) | set(t2["backends"]))
    save_run(run / "run.json", state, decisions, questions, md, total, [*saved["calls"], *[c.__dict__ for c in ledger.calls]])
    print(md)
    print(json.dumps(total, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ied")
    sub = p.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("analyse")
    a1.add_argument("--data", default="data/sample")
    a1.add_argument("--run", default="runs/demo")
    a1.add_argument("--backends", default=None)
    a2 = sub.add_parser("finish")
    a2.add_argument("--run", default="runs/demo")
    a2.add_argument("--founder", default="Founder")
    a2.add_argument("--backends", default=None)
    a = p.parse_args(argv)
    return {"analyse": cmd_analyse, "finish": cmd_finish}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
