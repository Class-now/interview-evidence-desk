"""Interview Evidence Desk pipeline.

extract (LLM, per interview) -> verify_quotes (no LLM) -> cluster (no LLM) -> challenge (LLM, per hypothesis)
-> HUMAN CHECKPOINT (founder decides accept / reject / doubt + reason) -> next_questions (LLM) + memo (no LLM)
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, field_validator

from .llm import Router
from .schemas import (STRENGTH_WEIGHT, Challenge, Evidence, ExtractResult, Hypothesis, HumanDecision,
                      HypothesisSummary, Interview, Judgement)

# ---------------------------------------------------------------- loading

def load_interview(path: Path) -> Interview:
    lines = [l.rstrip() for l in path.read_text(encoding="utf-8").splitlines()]
    title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("#") else path.stem
    body = [l for l in (lines[1:] if lines and lines[0].startswith("#") else lines) if l.strip()]
    return Interview(id=path.stem, title=title, lines=body)


def load_interviews(folder: Path) -> list[Interview]:
    return [load_interview(p) for p in sorted(Path(folder).glob("*.txt"))]


def load_hypotheses(path: Path) -> list[Hypothesis]:
    return [Hypothesis(**h) for h in json.loads(Path(path).read_text(encoding="utf-8"))]


# ---------------------------------------------------------------- stage 1: extract

EXTRACT_SYSTEM = """You help a startup founder analyse customer-discovery interviews.
You only report what the interviewee actually said. Never invent quotes.
For each piece of evidence copy the interviewee's words exactly (a short contiguous span, max 25 words)
and give the line number where they appear. Ignore lines spoken by the Interviewer.
kind: pain = a problem they have; workaround = what they do today instead; willingness_to_pay = money or
budget; counter = something that weakens a hypothesis.
strength: said = opinion or claim; did = a past action they describe; paid = money already spent.
supports: true if the quote makes the hypothesis more likely, false if less likely."""


def extract_prompt(iv: Interview, hyps: list[Hypothesis]) -> str:
    h = "\n".join(f"{x.id}: {x.statement}" for x in hyps)
    return (f"Hypotheses:\n{h}\n\nInterview {iv.id} ({iv.title}), numbered lines:\n{iv.numbered()}\n\n"
            "Return JSON {\"evidence\": [{\"hypothesis_id\", \"kind\", \"strength\", \"supports\", \"quote\", \"line\"}]}. "
            "Give 2 to 8 items. Use only the hypothesis ids above.")


def _extract_schema(hyps: list[Hypothesis]) -> dict:
    """JSON schema with hypothesis_id restricted to the real ids, so grammar-constrained back-ends cannot
    answer "h1", "1" or an interview id (Qwen2.5-7B did that for 15 quotes before this)."""
    schema = ExtractResult.model_json_schema()
    for d in schema.get("$defs", {}).values():
        if "hypothesis_id" in d.get("properties", {}):
            d["properties"]["hypothesis_id"] = {"type": "string", "enum": [h.id for h in hyps]}
    return schema


def normalise_hypothesis_id(raw: str, hyps: list[Hypothesis]) -> str:
    """Map harmless variants ("h1", "H 1", "1") to the real id; anything else is returned unchanged."""
    ids = [h.id for h in hyps]
    if raw in ids:
        return raw
    m = re.fullmatch(r"\s*h?\s*(\d+)\s*", raw or "", re.I)
    if m:
        cand = f"H{int(m.group(1))}"
        if cand in ids:
            return cand
    return raw


def extract(router: Router, iv: Interview, hyps: list[Hypothesis]) -> list[Evidence]:
    res: ExtractResult = router.json(f"extract:{iv.id}", EXTRACT_SYSTEM, extract_prompt(iv, hyps), ExtractResult,
                                     schema=_extract_schema(hyps))
    out = []
    for e in res.evidence:
        d = e.model_dump()
        d["hypothesis_id"] = normalise_hypothesis_id(d["hypothesis_id"], hyps)
        out.append(Evidence(**d, interview_id=iv.id))
    return out


# ---------------------------------------------------------------- stage 2: verify quotes (deterministic)

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[^a-z0-9'\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _speaker_text(line: str) -> tuple[str, str]:
    if ":" in line[:30]:
        who, text = line.split(":", 1)
        return who.strip().lower(), text
    return "", line


def _found_in(quote: str, line: str) -> bool:
    who, text = _speaker_text(line)
    if who.startswith("interviewer"):
        return False
    parts = [p for p in re.split(r"\.\.\.|…", quote) if _norm(p)]
    return bool(parts) and all(_norm(p) in _norm(text) for p in parts)


def verify_quotes(evidence: Iterable[Evidence], interviews: dict[str, Interview],
                  hyps: list[Hypothesis]) -> tuple[list[Evidence], list[Evidence]]:
    """Keep only quotes that literally exist in an interviewee line. Returns (kept, dropped)."""
    ids = {h.id for h in hyps}
    kept, dropped, seen = [], [], set()
    for e in evidence:
        iv = interviews.get(e.interview_id)
        if e.hypothesis_id not in ids or iv is None:
            dropped.append(e.model_copy(update={"verify_note": "unknown hypothesis or interview"}))
            continue
        n = len(iv.lines)
        near = [i for i in (e.line, e.line - 1, e.line + 1) if 1 <= i <= n]
        hit = next((i for i in near if _found_in(e.quote, iv.lines[i - 1])), None)
        note = ""
        if hit is None:
            hit = next((i for i in range(1, n + 1) if _found_in(e.quote, iv.lines[i - 1])), None)
            note = f"line corrected {e.line}->{hit}" if hit else ""
        if hit is None:
            dropped.append(e.model_copy(update={"verify_note": "quote not found in interviewee speech"}))
            continue
        key = (e.interview_id, e.hypothesis_id, hit, _norm(e.quote))
        if key in seen:
            continue
        seen.add(key)
        kept.append(e.model_copy(update={"line": hit, "verified": True, "verify_note": note}))
    return kept, dropped


# ---------------------------------------------------------------- stage 2b: judge each verified quote (LLM + rules)

JUDGE_SYSTEM = """You check one piece of interview evidence against one hypothesis.
Read the interviewer's question and the answer in context. Decide whether the quoted words make the
hypothesis MORE likely (for), LESS likely (against), or say nothing about it (irrelevant).
Numbers matter: if the hypothesis says "3 or more hours" and the speaker says ten minutes or one hour, that is against.
A refusal to pay, or a price below the threshold in the hypothesis, is against.
Wanting to approve or control every change is against letting staff act without approval.
strength: said = opinion, promise or hypothetical ("I would..."); did = something that already happened;
paid = money that was already spent. A future or conditional promise to pay is "said", never "paid"."""

_HYPOTHETICAL = re.compile(r"\b(would|'d|will|might|could|if)\b", re.I)
_SPENT = re.compile(r"\b(paid|pay|spent|spend|cost|costs|bought|refunded|subscription)\b.*?(\d|euro|eur|€)|"
                    r"(\d|euro|eur|€).*?\b(paid|pay|spent|cost|bought|refunded)\b", re.I)


def strength_guard(quote: str, strength: str) -> tuple[str, str]:
    """Deterministic correction of the most common small-model labelling errors."""
    if strength == "paid" and (_HYPOTHETICAL.search(quote) or not _SPENT.search(quote)):
        return "said", "strength paid->said (no money already spent)"
    if strength == "did" and re.search(r"\b(would|'d)\b", quote, re.I) and not re.search(r"\b(did|was|were|had|last)\b", quote, re.I):
        return "said", "strength did->said (hypothetical)"
    return strength, ""


def _context(iv: Interview, line: int) -> str:
    lo = max(1, line - 2)
    return "\n".join(f"{i}: {iv.lines[i - 1]}" for i in range(lo, line + 1))


def judge(router: Router, e: Evidence, iv: Interview, h: Hypothesis) -> tuple[Evidence, str]:
    user = (f"Hypothesis {h.id}: {h.statement}\n\nContext from interview {iv.id}:\n{_context(iv, e.line)}\n\n"
            f"Quoted evidence (line {e.line}): \"{e.quote}\"\n\n"
            'Return JSON {"reasoning": "...", "stance": "for|against|irrelevant", "strength": "said|did|paid"}.')
    j = router.json(f"judge:{iv.id}:{h.id}:L{e.line}", JUDGE_SYSTEM, user, Judgement)
    strength, note = strength_guard(e.quote, j.strength)
    kind = "counter" if j.stance == "against" else (e.kind if e.kind != "counter" else "pain")
    notes = "; ".join(x for x in (e.verify_note, note) if x)
    upd = {"supports": j.stance == "for", "strength": strength, "kind": kind, "judge_reason": j.reasoning,
           "verify_note": notes}
    if j.stance == "irrelevant":
        upd["verify_note"] = f"judged irrelevant to {h.id}: {j.reasoning}"
    return e.model_copy(update=upd), j.stance


def judge_all(router: Router, kept: list[Evidence], interviews: dict[str, Interview], hyps: list[Hypothesis],
              progress=None) -> tuple[list[Evidence], list[Evidence]]:
    hmap = {h.id: h for h in hyps}
    out, irrelevant = [], []
    for i, e in enumerate(kept, 1):
        if progress:
            progress(i / max(len(kept), 1), f"judging quote {i}/{len(kept)}")
        try:
            ne, stance = judge(router, e, interviews[e.interview_id], hmap[e.hypothesis_id])
        except RuntimeError:
            out.append(e.model_copy(update={"verify_note": (e.verify_note + "; not judged (model error)").strip("; ")}))
            continue
        (irrelevant if stance == "irrelevant" else out).append(ne)
    return out, irrelevant


# ---------------------------------------------------------------- stage 3: cluster (deterministic)

def cluster(evidence: list[Evidence], hyps: list[Hypothesis]) -> list[HypothesisSummary]:
    out = []
    for h in hyps:
        mine = [e for e in evidence if e.hypothesis_id == h.id]
        sup = [e for e in mine if e.supports and e.kind != "counter"]
        weak = [e for e in mine if not (e.supports and e.kind != "counter")]
        out.append(HypothesisSummary(
            hypothesis=h, supporting=sup, weakening=weak,
            score_for=sum(STRENGTH_WEIGHT[e.strength] for e in sup),
            score_against=sum(STRENGTH_WEIGHT[e.strength] for e in weak),
            interviews_covered=len({e.interview_id for e in mine})))
    return out


# ---------------------------------------------------------------- stage 4: challenge (LLM)

CHALLENGE_SYSTEM = """You are a sceptical co-founder. Your job is to stop the team fooling itself.
Given a hypothesis and the verified quotes for and against it, write:
devils_advocate: the strongest honest argument against the way the evidence currently leans (2 sentences max).
would_change_mind: one concrete thing an owner could SAY OR DO in the next interviews that would flip the conclusion
(for example "two owners show receipts for a scheduling tool they still pay for").
Refer to interview ids. Do not invent facts that are not in the quotes. If the evidence is thin, say so."""


def _fmt(e: Evidence) -> str:
    return f'- [{e.interview_id} L{e.line}, {e.kind}/{e.strength}] "{e.quote}"'


def challenge(router: Router, s: HypothesisSummary, n_interviews: int) -> Challenge:
    user = (f"Hypothesis {s.hypothesis.id}: {s.hypothesis.statement}\n"
            f"Current lean: {s.lean} (weighted for {s.score_for} / against {s.score_against}; "
            f"{s.interviews_covered} of {n_interviews} interviews mention it)\n"
            "Supporting:\n" + ("\n".join(map(_fmt, s.supporting)) or "- none") +
            "\nWeakening:\n" + ("\n".join(map(_fmt, s.weakening)) or "- none") +
            '\n\nReturn JSON {"devils_advocate": "...", "would_change_mind": "..."}.')
    return router.json(f"challenge:{s.hypothesis.id}", CHALLENGE_SYSTEM, user, Challenge)


# ---------------------------------------------------------------- stage 5: human checkpoint

class CheckpointIncomplete(Exception):
    pass


def require_decisions(summaries: list[HypothesisSummary], decisions: list[HumanDecision]) -> dict[str, HumanDecision]:
    got = {d.hypothesis_id: d for d in decisions}
    missing = [s.hypothesis.id for s in summaries if s.hypothesis.id not in got]
    if missing:
        raise CheckpointIncomplete("Founder decision and reason still needed for: " + ", ".join(missing))
    return got


# ---------------------------------------------------------------- stage 6: next questions (LLM)

_LEADING = re.compile(r"\b(would you|will you|wouldn't you|are you willing|would it|do you think|what do you think|"
                      r"if (we|you|there) (built|had|offered|made)|how likely|imagine)\b", re.I)


def is_leading(q: str) -> bool:
    """Hypothetical / opinion questions anywhere in the text (customer interviews should ask about past behaviour)."""
    return bool(_LEADING.search(q))


class RawQuestions(BaseModel):
    questions: list[str]


class Questions(BaseModel):
    questions: list[str]

    @field_validator("questions")
    @classmethod
    def _past_behaviour_only(cls, qs: list[str]) -> list[str]:
        qs = [q.strip() for q in qs if q.strip()]
        bad = [q for q in qs if is_leading(q)]
        if bad:
            raise ValueError("hypothetical/leading questions are not allowed (ask about past behaviour): " + " | ".join(bad))
        if not 3 <= len(qs) <= 8:
            raise ValueError("give 3 to 8 questions")
        return qs


QUESTIONS_SYSTEM = """You design the next round of customer-discovery questions.
Each question is ONE short sentence about past behaviour or a concrete recent event
("Tell me about the last time...", "What did you do when...", "How much did you spend on..., and on what?").
Never ask hypothetical, opinion or leading questions ("Would you...", "Are you willing...", "Do you think...").
Target the hypotheses the founder doubts or rejected, and the evidence that would change the decision."""


def next_questions(router: Router, summaries: list[HypothesisSummary], decisions: dict[str, HumanDecision],
                   want: int = 5) -> tuple[list[str], list[str]]:
    """Returns (accepted questions, rejected questions). Leading questions are filtered by code, then re-asked once."""
    lines = []
    for s in summaries:
        d = decisions[s.hypothesis.id]
        lines.append(f"{s.hypothesis.id} ({s.hypothesis.statement}) - founder: {d.decision} because \"{d.reason}\"; "
                     f"evidence lean: {s.lean}; would change mind: "
                     f"{s.challenge.would_change_mind if s.challenge else 'n/a'}")
    user = "\n".join(lines) + f'\n\nReturn JSON {{"questions": ["...", ...]}} with {want} questions.'
    good, bad = [], []
    for attempt in range(2):
        raw = router.json(f"next_questions:{attempt + 1}", QUESTIONS_SYSTEM, user, RawQuestions).questions
        for q in (q.strip() for q in raw if q.strip()):
            (bad if is_leading(q) else good).append(q)
        if len(good) >= 3:
            break
        user += ("\n\nThese were rejected as hypothetical or leading - do not repeat this style: " + " | ".join(bad))
    return good[:want], bad


# ---------------------------------------------------------------- stage 7: memo (deterministic)

def memo(summaries: list[HypothesisSummary], decisions: dict[str, HumanDecision], questions: list[str],
         founder: str, n_interviews: int, dropped: int, when: Optional[str] = None,
         rejected_questions: int = 0) -> str:
    when = when or dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"# Validation memo - {when}", "",
           f"Decided by: **{founder}** (human). Evidence prepared by Interview Evidence Desk from {n_interviews} "
           f"interviews; {dropped} model-proposed quotes were rejected because they did not appear in the transcripts.", ""]
    for s in summaries:
        d = decisions[s.hypothesis.id]
        out += [f"## {s.hypothesis.id}: {s.hypothesis.statement}",
                f"- **Decision: {d.decision.upper()}** - {d.reason}",
                f"- Evidence lean: {s.lean} (for {s.score_for} / against {s.score_against}, weights said=1 did=2 paid=3; "
                f"{s.interviews_covered}/{n_interviews} interviews)"]
        if s.challenge:
            out += [f"- Devil's advocate: {s.challenge.devils_advocate}",
                    f"- Would change our mind: {s.challenge.would_change_mind}"]
        best = sorted(s.supporting, key=lambda e: -STRENGTH_WEIGHT[e.strength])[:2]
        worst = sorted(s.weakening, key=lambda e: -STRENGTH_WEIGHT[e.strength])[:2]
        for e in best:
            out.append(f'- For: "{e.quote}" ({e.interview_id}, line {e.line}, {e.strength})')
        for e in worst:
            out.append(f'- Against: "{e.quote}" ({e.interview_id}, line {e.line}, {e.strength})')
        out.append("")
    out += ["## Next interview questions (past behaviour only)", *[f"{i}. {q}" for i, q in enumerate(questions, 1)]]
    if rejected_questions:
        out.append(f"_{rejected_questions} hypothetical or leading question(s) proposed by the model were filtered out._")
    out += ["",
            "_Nothing was sent anywhere. This memo is a draft for the founding team._"]
    return "\n".join(out)


# ---------------------------------------------------------------- orchestration helpers

def analyse(router: Router, interviews: list[Interview], hyps: list[Hypothesis], progress=None,
            judge_quotes: bool = True):
    """Everything before the human checkpoint."""
    raw: list[Evidence] = []
    for i, iv in enumerate(interviews, 1):
        if progress:
            progress(i / (len(interviews) + len(hyps)), f"extracting {iv.id}")
        try:
            raw += extract(router, iv, hyps)
        except RuntimeError:
            continue  # recorded in the ledger; the interview is reported as unprocessed
    ivmap = {iv.id: iv for iv in interviews}
    kept, dropped = verify_quotes(raw, ivmap, hyps)
    if judge_quotes:
        kept, irrelevant = judge_all(router, kept, ivmap, hyps,
                                     progress=(lambda f, m: progress(f, m)) if progress else None)
        dropped += irrelevant
    summaries = cluster(kept, hyps)
    for j, s in enumerate(summaries, 1):
        if progress:
            progress((len(interviews) + j) / (len(interviews) + len(hyps)), f"challenging {s.hypothesis.id}")
        try:
            s.challenge = challenge(router, s, len(interviews))
        except RuntimeError:
            s.challenge = None
    processed = sorted({e.interview_id for e in raw})
    return {"raw": raw, "kept": kept, "dropped": dropped, "summaries": summaries, "processed": processed,
            "unused_numbers": unused_number_lines(interviews, kept)}


_NUMBERED = re.compile(r"(\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|half|forty|fifty)\b)"
                       r".{0,25}\b(euro|euros|eur|hours?|minutes?|weeks?|months?|days?|orders?)\b|€", re.I)


def unused_number_lines(interviews: list[Interview], kept: list[Evidence]) -> list[dict]:
    """Recall aid (no LLM): interviewee lines with money or time figures that no kept quote cites.
    Small models miss evidence; this list shows the founder where to look."""
    used = {(e.interview_id, e.line) for e in kept}
    out = []
    for iv in interviews:
        for i, line in enumerate(iv.lines, 1):
            who, text = _speaker_text(line)
            if who.startswith("interviewer") or (iv.id, i) in used:
                continue
            if _NUMBERED.search(text):
                out.append({"interview_id": iv.id, "line": i, "text": line})
    return out


def save_run(path: Path, state: dict, decisions: list[HumanDecision], questions: list[str], memo_md: str,
             ledger_totals: dict, calls: list) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "kept_evidence": [e.model_dump() for e in state["kept"]],
        "dropped_evidence": [e.model_dump() for e in state["dropped"]],
        "summaries": [{"hypothesis": s.hypothesis.model_dump(), "lean": s.lean, "for": s.score_for,
                       "against": s.score_against, "challenge": s.challenge.model_dump() if s.challenge else None}
                      for s in state["summaries"]],
        "human_decisions": [d.model_dump() for d in decisions],
        "next_questions": questions,
        "rejected_questions": state.get("rejected_questions", []),
        "memo": memo_md,
        "usage": ledger_totals,
        "unused_number_lines": state.get("unused_numbers", []),
        "calls": [c if isinstance(c, dict) else c.__dict__ for c in calls],
    }
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
