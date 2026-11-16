import json
from pathlib import Path

import pytest

from ied.llm import FakeBackend, Ledger, Router
from ied.pipeline import (CheckpointIncomplete, Questions, analyse, strength_guard, cluster, load_hypotheses, load_interviews, memo,
                          require_decisions, verify_quotes)
from ied.schemas import Evidence, HumanDecision, Hypothesis

DATA = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.fixture
def ivs():
    return load_interviews(DATA / "interviews")


@pytest.fixture
def hyps():
    return load_hypotheses(DATA / "hypotheses.json")


def ev(**kw):
    base = dict(hypothesis_id="H2", kind="pain", strength="did", supports=True, quote="", line=1, interview_id="i01-lea-cafe")
    base.update(kw)
    return Evidence(**base)


def test_sample_data_loads(ivs, hyps):
    assert len(ivs) == 8 and len(hyps) == 4
    assert all(iv.lines[0].startswith("Interviewer:") for iv in ivs)


def test_verify_keeps_exact_quote_and_fixes_line(ivs, hyps):
    d = {iv.id: iv for iv in ivs}
    kept, dropped = verify_quotes([ev(quote="I opened alone for the first hour", line=2)], d, hyps)
    assert not dropped and kept[0].line == 7 and "corrected" in kept[0].verify_note


def test_verify_drops_invented_quote(ivs, hyps):
    d = {iv.id: iv for iv in ivs}
    kept, dropped = verify_quotes([ev(quote="I would happily pay 100 euros a month", line=12)], d, hyps)
    assert not kept and dropped[0].verify_note.startswith("quote not found")


def test_verify_rejects_interviewer_words(ivs, hyps):
    d = {iv.id: iv for iv in ivs}
    kept, dropped = verify_quotes([ev(quote="would you need to approve it", line=15)], d, hyps)
    assert not kept


def test_verify_handles_ellipsis_and_curly_quotes(ivs, hyps):
    d = {iv.id: iv for iv in ivs}
    q = "the Sunday grid is fine… it’s the 6 a.m. phone calls"
    kept, _ = verify_quotes([ev(quote=q, line=10)], d, hyps)
    assert kept


def test_cluster_weights_and_lean(hyps):
    e = [ev(hypothesis_id="H3", kind="willingness_to_pay", strength="paid", quote="x" * 10),
         ev(hypothesis_id="H3", kind="counter", strength="said", supports=False, quote="y" * 10)]
    s = {x.hypothesis.id: x for x in cluster(e, hyps)}
    assert s["H3"].score_for == 3 and s["H3"].score_against == 1 and s["H3"].lean == "supported"
    assert s["H1"].lean == "no evidence"


def test_checkpoint_blocks_without_every_decision(hyps):
    sums = cluster([], hyps)
    with pytest.raises(CheckpointIncomplete):
        require_decisions(sums, [HumanDecision(hypothesis_id="H1", decision="accept", reason="enough evidence")])


def test_reason_is_mandatory():
    with pytest.raises(ValueError):
        HumanDecision(hypothesis_id="H1", decision="accept", reason=" ")


def test_leading_questions_rejected():
    with pytest.raises(ValueError):
        Questions(questions=["Would you pay 20 euros?", "Tell me about the last swap.", "What did it cost?"])
    assert Questions(questions=["Tell me about the last swap.", "What did it cost?", "Who found the cover?"])
    from ied.pipeline import is_leading
    assert is_leading("How much are you willing to pay for a tool?")
    assert is_leading("What did you spend last month? What features do you think matter?")
    assert not is_leading("How much did you spend on scheduling last year, and on what?")


def test_next_questions_filters_and_reasks(hyps):
    from ied.pipeline import next_questions
    answers = iter([["Would you pay 20 EUR?", "Tell me about the last sick call."],
                    ["What did the last no-show cost you?", "Who covered the last swap?", "Are you willing to switch?"]])
    r = Router([FakeBackend(lambda s, u: json.dumps({"questions": next(answers)}))])
    sums = cluster([], hyps)
    dec = {h.id: HumanDecision(hypothesis_id=h.id, decision="doubt", reason="need more") for h in hyps}
    good, bad = next_questions(r, sums, dec)
    assert len(good) == 3 and len(bad) == 2


def _fake(system, user):
    if "Interview i" in user:
        iv = user.split("Interview ")[1].split(" ")[0]
        good = {"i01-lea-cafe": ("H2", "it's the 6 a.m. phone calls that make me want to sell the place", 10)}
        out = []
        if iv in good:
            h, q, l = good[iv]
            out.append({"hypothesis_id": h, "kind": "pain", "strength": "said", "supports": True, "quote": q, "line": l})
        out.append({"hypothesis_id": "H1", "kind": "pain", "strength": "said", "supports": True,
                    "quote": "this sentence was invented by the model", "line": 3})
        return json.dumps({"evidence": out})
    if "Quoted evidence" in user:
        return json.dumps({"reasoning": "Lea says early sick calls are the worst part.", "stance": "for", "strength": "paid"})
    if "devils_advocate" in user:
        return json.dumps({"devils_advocate": "Only one owner said so.", "would_change_mind": "A second owner losing money."})
    return json.dumps({"questions": ["Tell me about the last sick call.", "What did it cost?", "Who covered?"]})


def test_end_to_end_with_fake_backend(ivs, hyps):
    led = Ledger()
    st = analyse(Router([FakeBackend(_fake)], led), ivs, hyps)
    assert len(st["kept"]) == 1 and len(st["dropped"]) == 8
    by = {s.hypothesis.id: s for s in st["summaries"]}
    assert by["H2"].challenge.devils_advocate
    dec = {h.id: HumanDecision(hypothesis_id=h.id, decision="doubt", reason="need more") for h in hyps}
    md = memo(st["summaries"], dec, ["Tell me about the last sick call."], "Test", 8, len(st["dropped"]))
    assert "DOUBT" in md and "8 model-proposed quotes were rejected" in md
    assert led.totals()["calls"] == 8 + 1 + 4
    assert st["kept"][0].strength == "said"  # "paid" without money spent is downgraded


def test_router_falls_back_after_bad_json():
    bad = FakeBackend(lambda s, u: "not json", model="broken")
    good = FakeBackend(lambda s, u: json.dumps({"questions": ["Tell me a.", "Tell me b.", "Tell me c."]}))
    led = Ledger()
    r = Router([bad, good], led)
    assert r.json("q", "", "", Questions).questions[0] == "Tell me a."
    assert [c.ok for c in led.calls] == [False, False, True]


def test_strength_guard():
    assert strength_guard("I would pay around 15 euros a month.", "paid")[0] == "said"
    assert strength_guard("I paid for one of those scheduling apps for three months, about 35 euros a month", "paid")[0] == "paid"
    assert strength_guard("I pay a student 50 euros a month to be the person who checks the chat", "paid")[0] == "paid"
    assert strength_guard("Two or three times a week there's some change.", "paid")[0] == "said"
    assert strength_guard("I'd pay 30 a month without thinking", "did")[0] == "said"


def test_unused_number_lines_flags_missed_money(ivs):
    from ied.pipeline import unused_number_lines
    out = unused_number_lines(ivs, [])
    texts = [u["text"] for u in out]
    assert any("50 euros a month" in t for t in texts)
    assert not any(t.startswith("Interviewer") for t in texts)


def test_hypothesis_ids_are_constrained_and_normalised():
    from ied.pipeline import _extract_schema, normalise_hypothesis_id
    hyps = [Hypothesis(id="H1", statement="a"), Hypothesis(id="H2", statement="b")]
    schema = _extract_schema(hyps)
    enums = [d["properties"]["hypothesis_id"].get("enum") for d in schema["$defs"].values()
             if "hypothesis_id" in d.get("properties", {})]
    assert enums == [["H1", "H2"]]
    assert [normalise_hypothesis_id(x, hyps) for x in ("h1", "2", "H 2", "i02", "H3")] == ["H1", "H2", "H2", "i02", "H3"]
