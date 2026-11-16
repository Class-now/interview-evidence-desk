# Responsible AI

## Data
* All demo data is synthetic and was written for this project. The eight "owners" are fictional.
* The default set-up runs a local open-weight model: transcripts never leave the founder's machine.
  If a cloud free tier (Gemini, Groq) is enabled, transcripts are sent to that provider and its terms apply;
  the README says so next to the setting.
* Real interviews contain personal data about the interviewee. We recommend replacing names with roles
  before upload, and getting the interviewee's consent to record and analyse the conversation. The tool
  stores nothing on a server; run records are written only where the user chooses.
* No API key is stored in the repository, the app or the run records.

## Known failure modes and what we do about them

| Risk | Mitigation in the product | What remains |
|---|---|---|
| Hallucinated quotes | Every quote is checked literally against interviewee lines; failures are dropped and listed | None for precision; paraphrases are dropped even when faithful |
| Missed evidence (low recall) | Evidence board shows how many interviews mention each hypothesis; founder can read the transcript lines | A small model misses some quotes. Treat "no evidence" as "not found", not "absent" |
| Mislabelled strength (said/did/paid) | Labels shown next to every quote; weights are simple and printed | The model's judgement; spot-check high-weight quotes |
| Confirmation bias of the founder | Devil's advocate and "what would change our mind" for every hypothesis; decision and reason are mandatory and recorded | The founder can still overrule evidence — by design, but on the record |
| Leading questions in the next round | Validator rejects hypothetical / leading questions | Question quality still depends on the model |
| Over-trust in numbers | The UI says "lean", never "proof", and shows interview coverage | 8 interviews is qualitative research, not statistics |
| Model outage / quota | Fall-back chain across back-ends, failures recorded in the run record | If all back-ends fail, the stage stops with an error rather than guessing |

## Bias
Interviewees who speak at length produce more quotes, and therefore more weight. The evidence board shows
"interviews covered" next to the score so that one talkative interviewee cannot silently dominate. The model
was asked to treat all interviewees alike; it is not told names, gender or origin beyond what is in the text.

## Human oversight
See `human-judgment.md`. The agent never sends messages, never contacts interviewees and never takes a
business decision. Its output is a draft memo for the founding team.
