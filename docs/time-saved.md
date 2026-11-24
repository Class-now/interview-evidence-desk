# Time-Saved Report

## The task
After a round of customer-discovery interviews, a founder has to turn 5–10 transcripts into a decision:
which assumptions survived, which died, and what to ask next. Done by hand this means re-reading every
transcript, copying quotes, sorting them by assumption, weighing them and writing a memo for the co-founders.

## Measured: the agent
Sample: 8 interviews (13–19 turns each), 4 hypotheses. Hardware: a 4-core 2.3 GHz cloud CPU, no GPU.
Model: Qwen2.5-3B-Instruct Q4_K_M via llama.cpp. Numbers from `examples/qwen2.5-3b-cpu/run.json`.

| Stage | Model calls | Machine time |
|---|---|---|
| extract (one call per interview) | 8 | 262 s |
| judge (one call per verified quote) | 32 | 375 s |
| challenge (one call per hypothesis) | 4 | 76 s |
| next questions | 1 | 18 s |
| **Total** | **45** (0 failed) | **731 s ≈ 12 min**, unattended |

Tokens: 17,696 in / 5,046 out for the whole run. Cost: 0 (local open-weight model).

Second run, same machine, **Qwen2.5-7B-Instruct Q4_K_M** (`examples/qwen2.5-7b-cpu/run.json`):

| Stage | Model calls | Machine time |
|---|---|---|
| extract | 8 | 648 s |
| judge | 39 | 800 s |
| challenge | 4 | 123 s |
| next questions | 1 | 38 s |
| **Total** | **52** (0 failed) | **1,609 s ≈ 27 min**, unattended |

Tokens: 20,415 in / 5,410 out. Cost: 0. The 7B model kept 35 checked quotes (3B: 30), drawn from 8/8
interviews for H1 and H3 and 7/8 for H2 and H4. The quote check rejected 1 quote as not in the transcript
(3B: 2, the same sentence proposed for two hypotheses); a further 4 (3B: 2) were judged irrelevant and listed.
We have not timed a GPU or cloud run; with a GPU the machine time should be a few minutes, but that is an estimate.

## Founder time: before and after

| Step | By hand (estimate) | With the agent (estimate) |
|---|---|---|
| Re-read 8 transcripts and mark quotes | 8 × 20 min = 160 min | 0 (machine) |
| Sort quotes by hypothesis, weigh them | 45 min | 0 (machine) |
| Check the evidence and decide | 30 min | 25 min: read the evidence board, the "lines with numbers the model did not use", decide and write 4 reasons |
| Draft next questions and memo | 40 min | 10 min: edit the generated questions and memo |
| **Total** | **≈ 4.6 h** | **≈ 35 min** of founder time (+12 min unattended) |

**Saved: about 4 hours per interview round, ≈ 87 % of founder time.** A team doing one round every two
weeks in the discovery phase saves about 8 hours a month.

## How the estimates were made
* By-hand times follow a common manual method (read, highlight, sticky-note sort, memo). The 20 minutes
  per transcript assumes 30-minute interviews transcribed to ~2,000 words; our synthetic transcripts are
  shorter, so for them the manual time is an upper bound.
* "With the agent" founder time is the time to read `evidence.md` (≈ 3,200 words in the sample run, most
  of it one-line reasons the founder can skim) and write one-line decisions, plus light editing of the memo.
* We did not time real founders. The run record makes the machine side reproducible; the human side is an
  estimate and is labelled as such.

## What the time buys
The saving is not only speed. In the sample run the founder's decisions differ from the raw evidence lean
on two of four hypotheses: H4 was "supported" by the evidence score but rejected by the founder, who saw that
several "for" quotes were about price, not approval; H1 was "mixed" and rejected because the stated hours
cluster below 3. H3 stayed in doubt because the pattern scan surfaced three owners who already pay 35–89 EUR/month.
The agent spends the founder's attention on judgment rather than on copying quotes.
