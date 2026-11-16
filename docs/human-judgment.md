# Human judgment by design

## Where the human sits
The pipeline has one hard stop: after the evidence board and before anything is written for the team.

1. The agent shows, for every hypothesis, the verified quotes for and against, their strength (said / did / paid),
   how many interviews mention it, a **devil's advocate** reading and **one observation that would change the conclusion**.
2. The founder must choose **accept, reject or doubt** for every hypothesis **and write a reason**.
   The web app and the command line both refuse to continue while any decision or reason is missing
   (`require_decisions` in `ied/pipeline.py`, covered by tests).
3. Only then does the agent draft the next interview questions — aimed at the hypotheses the founder doubts —
   and the memo, which records the founder's name as the decision maker and the reason in their own words.

## Why there, and not elsewhere
* Extracting and checking quotes is mechanical: the machine is faster and, with literal verification, more
  reliable than a tired founder at midnight. Asking a human to approve each quote would add clicks, not judgment.
* Deciding whether "two owners lost money on no-shows" is enough to build a product is a business bet that
  depends on context the transcripts do not contain (runway, team skills, competitors). That decision stays human.
* The devil's advocate is placed **before** the decision, not after, so that it can change it.

## Critical-thinking aids
* Evidence is weighted by what people did and paid, not by what they said they would do.
* The next-question generator is not allowed to ask hypothetical or leading questions ("Would you pay…?"),
  following the customer-interview practice of asking about past behaviour.
* The memo lists the strongest quote **against** each decision next to the strongest quote for it.

## What the founder can audit
`run.json` contains every proposed quote (kept and rejected, with the reason), every model call with its
back-end, model, token count, time and retries, and every human decision with its reason.
