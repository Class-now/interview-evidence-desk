# Interview Evidence Desk

**Customer-interview transcripts in, verified evidence out — the founder makes the call.**

Early-stage founders run dozens of customer-discovery interviews, then spend an evening re-reading notes,
copying quotes onto sticky notes and arguing about what people "really meant". Interview Evidence Desk does
the tedious part — finding, sorting and weighing the evidence — and refuses to do the part that must stay
human: deciding what the evidence means for the business.

## What it does

```
transcripts + hypotheses
   │
   ▼  1. extract          (LLM, one call per interview, JSON-schema constrained)
   ▼  2. verify_quotes    (no LLM: every quote must literally appear in an interviewee line; otherwise dropped)
   ▼  2b. judge           (LLM, one call per verified quote, with the interviewer's question as context:
   │                       for / against / irrelevant + said / did / paid; rules stop "I would pay" counting as "paid")
   ▼  3. cluster          (no LLM: weight evidence said=1 / did=2 / paid=3, compute lean per hypothesis)
   │     + recall aid     (no LLM: interviewee lines with money or time figures that no quote used are listed for the founder)
   ▼  4. challenge        (LLM: devil's advocate + "what would change our mind" for each hypothesis)
   ▼  5. HUMAN CHECKPOINT (founder must choose accept / reject / doubt AND give a reason for every hypothesis)
   ▼  6. next_questions   (LLM: past-behaviour questions only; leading "Would you…?" questions are rejected by a validator)
   ▼  7. memo             (no LLM: one-page decision memo naming who decided and citing interview + line for every quote)
```

* **No invented quotes.** The model proposes quotes with line numbers; deterministic code checks each one
  against the transcript (normalising quotes/ellipses, rejecting words spoken by the interviewer, correcting
  off-by-one line numbers). Rejected output is shown on the evidence board, not hidden.
* **Small-model aware.** A 3B model is good at finding sentences and bad at judging them in bulk, so stance is
  judged one quote at a time, and a pattern scan shows the founder the money/time lines the model skipped.
  See `examples/qwen2.5-3b-cpu/` and `examples/qwen2.5-7b-cpu/` for unedited runs, mistakes included.
  With grammar-constrained back-ends the hypothesis id is restricted to the real ids (Qwen2.5-7B otherwise
  answered "h1" or an interview id and lost 15 good quotes).
* **The human decides.** Steps 6–7 cannot run until each hypothesis has a decision and a written reason.
  The memo records the decision maker by name.
* **Free to run.** Default model is the open-weight **Qwen2.5-3B-Instruct (Q4_K_M GGUF, Apache-2.0)** on a laptop
  CPU through llama.cpp. Optional fall-backs: a local Ollama server, the Google Gemini API free tier, the Groq free tier.
* **Traceable.** Every run writes `run.json` with every quote, every model call (back-end, model, tokens, seconds,
  retries) and every human decision.

## Quick start (local, no API key, no data leaves the machine)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt llama-cpp-python
mkdir -p models && curl -L -o models/qwen2.5-3b-instruct-q4_k_m.gguf \
  https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf
python app.py            # open http://localhost:7860
# no time to wait? press "Or open the recorded sample run (no waiting)" to go straight to the checkpoint
```

Command line instead of the web app:

```bash
python -m ied.cli analyse --data data/sample --run runs/demo      # stops at the human checkpoint
cp runs/demo/decisions.todo.json runs/demo/decisions.json          # fill decision + reason for each hypothesis
python -m ied.cli finish --run runs/demo --founder "Your Name"
```

Other free back-ends (tried in the order given; unavailable ones are skipped):

| `IED_BACKENDS` entry | needs |
|---|---|
| `llamacpp` | `IED_GGUF=path/to/model.gguf` (default `models/qwen2.5-3b-instruct-q4_k_m.gguf`; `IED_AUTO_DOWNLOAD=1` fetches it at start-up) |
| `ollama` | a running Ollama, `IED_OLLAMA_MODEL` (default `qwen2.5:7b-instruct`) |
| `gemini` | `GEMINI_API_KEY` from Google AI Studio (free tier) |
| `groq` | `GROQ_API_KEY` (free tier) |

Example: `IED_BACKENDS=gemini,llamacpp python app.py` uses Gemini's free tier and falls back to the local model.

## Input format

* Transcripts: `.txt`, optional first line `# title`, then one turn per line: `Speaker: text`.
  Lines whose speaker starts with `Interviewer` are never used as evidence.
* Hypotheses: up to 6, one per line in the web app, or `hypotheses.json` for the CLI.

## Sample data

`data/sample/` holds 8 **synthetic** interviews written for this project (fictional owners of cafes and
bakeries, a staff-scheduling idea) and 4 hypotheses. No real person's data is used.

## Tests

```bash
pip install pytest && pytest -q
```

The tests use a fake back-end (no model needed) and cover quote verification, interviewer-line rejection,
weighting, the mandatory checkpoint, the leading-question validator and back-end fall-back.

## Project layout

```
app.py              Gradio one-screen app
ied/pipeline.py     the seven stages
ied/llm.py          back-ends, JSON validation, retry, fall-back, token ledger
ied/schemas.py      pydantic models for every stage
ied/report.py       evidence board
ied/cli.py          two-step command line
data/sample/        synthetic interviews + hypotheses
tests/              pytest
```

## Limits

Read `docs/responsible-ai.md`. In short: a 3B model misses some evidence (recall, not precision, is the weak
side — verification removes made-up quotes but cannot add missed ones); the said/did/paid labels are the
model's judgement and should be spot-checked; eight interviews are not a statistically meaningful sample, and
the tool says "lean", never "proof".

## Licence

MIT. Built for the HETIC *AI Agents for Founders Challenge 2026*.
