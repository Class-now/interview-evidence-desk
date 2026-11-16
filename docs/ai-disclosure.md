# AI Disclosure Statement

## AI inside the product (run time)

| Model | Provider / licence | Role | Plan | Per run (8 interviews, 4 hypotheses) |
|---|---|---|---|---|
| Qwen2.5-3B-Instruct, Q4_K_M GGUF (default) | Alibaba Cloud Qwen team, Apache-2.0, open weights, run locally with llama.cpp | extract quotes, judge each quote, devil's advocate, next questions | free (local) | 45 calls, 17,696 prompt + 5,046 completion tokens, 731 s on a 4-core CPU |
| Qwen2.5-7B-Instruct, Q4_K_M GGUF (optional, better quality) | Alibaba Cloud Qwen team, Apache-2.0, open weights, local llama.cpp or Ollama | same | free (local) | 52 calls, 20,415 prompt + 5,410 completion tokens, 1,609 s on a 4-core CPU |
| Gemini 2.0 Flash (optional fall-back) | Google, Gemini API free tier | same | free tier only | same number of calls |
| Llama 3.1 8B Instant (optional fall-back) | Meta weights, served by Groq free tier | same | free tier only | same number of calls |

* No paid model, paid credit or paid plan is used when the product runs.
* The runs recorded in `examples/qwen2.5-3b-cpu/run.json` and `examples/qwen2.5-7b-cpu/run.json` used only the
  local Qwen2.5-3B and Qwen2.5-7B models. The demo video opens the 7B run from the saved file and computes the
  next questions live with the same local 7B model.
  Every call (stage, back-end, model, tokens, seconds, retries) is listed there.
* Deterministic code, not AI, does quote verification, weighting, the human checkpoint, the
  money/time pattern scan, leading-question filtering and the memo layout.

## AI used to build the product (development time)

| Tool | Provider | Plan | What it did |
|---|---|---|---|
| Claude Code (Claude Opus model) | Anthropic | paid subscription | wrote most of the Python code, tests, prompts, the eight synthetic interviews, the architecture diagram and the first drafts of the documentation, under the team's direction |

The team chose the problem, the hypotheses and the design, ran the agent, reviewed its outputs, wrote the
founder decisions in the sample run and edited the documents. All code and data were created during the
submission period (from 16 November 2026). Third-party libraries used: pydantic, gradio, requests,
llama-cpp-python, pytest.

## Data
The sample interviews are synthetic. No personal data of real people was used for development or in the demo.
