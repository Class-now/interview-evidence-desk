"""One-screen web app: Analyse -> founder decides (required) -> memo + next questions.

Run:  python app.py      (Hugging Face Spaces runs this file directly)
Back-ends are picked from IED_BACKENDS (default llamacpp,ollama,gemini,groq) - see README.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path

import gradio as gr

try:  # Hugging Face ZeroGPU hardware needs at least one @spaces.GPU function; the agent itself runs on CPU.
    import spaces

    @spaces.GPU
    def _zerogpu_probe() -> None:
        return None
except ImportError:
    pass

from ied.llm import Ledger, build_router
from ied.pipeline import (CheckpointIncomplete, analyse, load_hypotheses, load_interview, load_interviews, memo,
                          next_questions, require_decisions, save_run)
from ied.report import evidence_markdown
from ied.schemas import Hypothesis, HumanDecision

ROOT = Path(__file__).parent
SAMPLE = ROOT / "data" / "sample"
RECORDED = ROOT / "examples" / os.environ.get("IED_RECORDED", "qwen2.5-7b-cpu") / "analysis.json"
MAX_H = 6
GGUF_URL = "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"


def _ensure_model() -> None:
    """On a hosted demo (IED_AUTO_DOWNLOAD=1) fetch the default open-weight model once at start-up."""
    path = Path(os.environ.get("IED_GGUF", "models/qwen2.5-3b-instruct-q4_k_m.gguf"))
    if os.environ.get("IED_AUTO_DOWNLOAD") != "1" or path.exists():
        return
    import requests
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with requests.get(GGUF_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.rename(path)


def _hyps_from_text(text: str) -> list[Hypothesis]:
    rows = [l.strip() for l in text.splitlines() if l.strip()]
    return [Hypothesis(id=f"H{i}", statement=r.split(":", 1)[1].strip() if r[:3].rstrip(":").startswith("H") and ":" in r else r)
            for i, r in enumerate(rows[:MAX_H], 1)]


def run_analysis(files, hyp_text, progress=gr.Progress()):
    hyps = _hyps_from_text(hyp_text)
    if files:
        ivs = [load_interview(Path(f if isinstance(f, str) else f.name)) for f in files]
    else:
        ivs = load_interviews(SAMPLE / "interviews")
    ledger = Ledger()
    router = build_router(None, ledger)
    state = analyse(router, ivs, hyps, progress=lambda f, m: progress(f, desc=m))
    state["n"] = len(ivs)
    state["ledger"] = ledger
    return _show(state, hyps, ledger.totals(), "")


def load_recorded():
    """Open the unedited sample run saved in examples/ so a visitor can try the checkpoint without waiting."""
    from ied.cli import _load_state
    saved = json.loads(RECORDED.read_text(encoding="utf-8"))
    state = _load_state(saved)
    state["n"] = saved["n_interviews"]
    state["ledger"] = Ledger()
    hyps = [s.hypothesis for s in state["summaries"]]
    return _show(state, hyps, saved["usage"], f"Recorded run from `{RECORDED.parent.name}/` (not re-computed). ",
                 full_calls=_recorded_full_calls())


def _recorded_full_calls():
    """Calls of the whole recorded run (run.json, including next-round questions), if it was saved."""
    try:
        return json.loads((RECORDED.parent / "run.json").read_text(encoding="utf-8"))["usage"]["calls"]
    except (OSError, ValueError, KeyError):
        return None


def _calls_text(t, full_calls=None):
    if full_calls and full_calls != t["calls"]:
        return f"Model calls: {t['calls']} up to the checkpoint ({full_calls} including next-round questions)"
    return f"Model calls: {t['calls']}"


def _show(state, hyps, t, prefix, full_calls=None):
    usage = (f"{prefix}{_calls_text(t, full_calls)} ({t['failed_calls']} retried/failed) - tokens in {t['prompt_tokens']:,} / "
             f"out {t['completion_tokens']:,} - {t['seconds']} s - {', '.join(t['backends']) or 'none'}")
    updates = []
    for i in range(MAX_H):
        if i < len(hyps):
            s = state["summaries"][i]
            updates += [gr.update(visible=True, label=f"{s.hypothesis.id} - {s.hypothesis.statement} (evidence: {s.lean})",
                                  value=None), gr.update(visible=True, value="")]
        else:
            updates += [gr.update(visible=False), gr.update(visible=False)]
    return [state, evidence_markdown(state, state["n"]), usage, *updates]


def finish(state, founder, *vals):
    if not state:
        return "Run the analysis first.", None
    decisions = []
    for i, s in enumerate(state["summaries"]):
        d, r = vals[2 * i], vals[2 * i + 1]
        if d and r and len(r.strip()) >= 3:
            decisions.append(HumanDecision(hypothesis_id=s.hypothesis.id, decision=d, reason=r))
    try:
        by_id = require_decisions(state["summaries"], decisions)
    except CheckpointIncomplete as e:
        return f"**The agent is waiting for you.** {e}. Pick accept / reject / doubt and write one line of reasoning.", None
    ledger: Ledger = state["ledger"]
    router = build_router(None, ledger)
    qs, rejected_q = next_questions(router, state["summaries"], by_id)
    state["rejected_questions"] = rejected_q
    md = memo(state["summaries"], by_id, qs, founder or "Founder", state["n"], state["dropped"],
              rejected_questions=len(rejected_q))
    out = Path(tempfile.gettempdir()) / f"ied-run-{dt.datetime.now():%Y%m%d-%H%M%S}.json"
    save_run(out, state, decisions, qs, md, ledger.totals(), ledger.calls)
    return md, str(out)


with gr.Blocks(title="Interview Evidence Desk") as demo:
    gr.Markdown("# Interview Evidence Desk\nCustomer-interview notes in, verified evidence out - **you** make the call.\n"
                "Leave the upload empty to use 8 synthetic sample interviews (a cafe-scheduling idea).")
    st = gr.State(None)
    with gr.Row():
        files = gr.File(label="Interview transcripts (.txt, one line per turn: 'Name: text')", file_count="multiple",
                        file_types=[".txt"])
        hyp = gr.Textbox(label="Hypotheses (one per line)", lines=6,
                         value="\n".join(f"{h.id}: {h.statement}" for h in load_hypotheses(SAMPLE / "hypotheses.json")))
    with gr.Row():
        go = gr.Button("1. Analyse interviews", variant="primary")
        rec = gr.Button("Or open the recorded sample run (no waiting)", visible=RECORDED.exists())
    usage = gr.Markdown()
    board = gr.Markdown()
    gr.Markdown("## 2. Human checkpoint - decide every hypothesis\nThe agent will not write the memo until each one has a decision and a reason.")
    founder = gr.Textbox(label="Your name (recorded in the memo as the decision maker)", value="Founder")
    ctrls = []
    for i in range(MAX_H):
        with gr.Row():
            ctrls.append(gr.Radio(["accept", "reject", "doubt"], label=f"H{i + 1}", visible=False))
            ctrls.append(gr.Textbox(label="Why? (required)", visible=False))
    done = gr.Button("3. Write memo and next questions", variant="primary")
    out = gr.Markdown()
    dl = gr.File(label="Full run record (JSON: every quote, model call, token count and decision)")
    go.click(run_analysis, [files, hyp], [st, board, usage, *ctrls])
    rec.click(load_recorded, [], [st, board, usage, *ctrls])
    done.click(finish, [st, founder, *ctrls], [out, dl])

if __name__ == "__main__":
    _ensure_model()
    demo.queue().launch(server_name=os.environ.get("HOST", "0.0.0.0"), server_port=int(os.environ.get("PORT", 7860)))
