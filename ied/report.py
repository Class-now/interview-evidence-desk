"""Human-readable evidence table shown at the checkpoint."""
from __future__ import annotations

from .schemas import STRENGTH_WEIGHT


def evidence_markdown(state: dict, n_interviews: int) -> str:
    out = ["# Evidence board", "",
           f"Interviews processed: {len(state['processed'])}/{n_interviews}. "
           f"Verified quotes: {len(state['kept'])}. Rejected (not found in transcript): {len(state['dropped'])}.", "",
           "| Hypothesis | Lean | For | Against | Interviews |", "|---|---|---|---|---|"]
    for s in state["summaries"]:
        out.append(f"| {s.hypothesis.id} | {s.lean} | {s.score_for} ({len(s.supporting)} quotes) | "
                   f"{s.score_against} ({len(s.weakening)} quotes) | {s.interviews_covered}/{n_interviews} |")
    out.append("")
    for s in state["summaries"]:
        out += [f"## {s.hypothesis.id}: {s.hypothesis.statement}", f"Lean: **{s.lean}**", ""]
        for label, items in (("For", s.supporting), ("Against", s.weakening)):
            out.append(f"**{label}**")
            for e in sorted(items, key=lambda e: -STRENGTH_WEIGHT[e.strength]) or []:
                note = f" _({e.verify_note})_" if e.verify_note else ""
                why = f" - why: {e.judge_reason}" if e.judge_reason else ""
                out.append(f'- "{e.quote}" - {e.interview_id} L{e.line}, {e.kind}, {e.strength}{note}{why}')
            if not items:
                out.append("- none")
        if s.challenge:
            out += ["", f"> Devil's advocate: {s.challenge.devils_advocate}",
                    f"> Would change our mind: {s.challenge.would_change_mind}"]
        out.append("")
    if state.get("unused_numbers"):
        out += ["## Not used as evidence, but contains money or time figures (check these yourself)",
                "_The model may have missed them. Found by a simple pattern, not by the model._"]
        out += [f"- {u['interview_id']} L{u['line']}: {u['text']}" for u in state["unused_numbers"]]
        out.append("")
    if state["dropped"]:
        out += ["## Rejected model output (shown for transparency)"]
        out += [f'- {e.interview_id} {e.hypothesis_id}: "{e.quote}" - {e.verify_note}' for e in state["dropped"]]
    return "\n".join(out)
