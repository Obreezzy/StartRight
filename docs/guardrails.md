# Guardrails

StartRight has two layers of guardrails. The first is always on; the second is optional.

## Layer 1: own code guardrails (always on)
| Rule | Where | What it does |
|---|---|---|
| Question checks | `guardrails.check_question` | length limit, prompt-injection patterns |
| Score threshold | `retrieval.score_floor` | refuses when no document is relevant enough |
| Topic gate | `structured.is_business_description` | rejects off-topic checklist requests |
| Grounding check | `multiagent` verify step | every cited number must be a real source; figures must appear in sources |
| Structured output | `structured.py` (Pydantic) | invalid JSON is re-asked with the exact errors |

## Layer 2: Guardrails AI (optional)
`src/startright/guards.py` declares three rules as validators on Guardrails AI `Guard` objects:

| Guard | Validator | On failure |
|---|---|---|
| input | `startright/valid-question` (re-uses `check_question`) | refuse |
| input | `startright/no-personal-data` | **fix**: Zimbabwean ID numbers, mobile numbers and emails are replaced with placeholders before the text goes to Groq |
| output | `startright/has-citation` | add a note to the answer when it cites nothing or cites a source that does not exist |

Turn it on locally:
```powershell
pip install -r requirements-guardrails.txt
$env:GUARDRAILS_AI = "on"
```
`/api/info` shows `guardrails_ai` with `requested`, `installed` and `active`.

**Why it is off by default:** the package is large (about 450 MB installed, about 120 MB of memory to import)
and does not fit a 512 MB free server. The hosted site relies on layer 1. For the demo, run layer 2 locally.

**Privacy:** Guardrails AI sends anonymous usage traces to its own server unless told not to.
`guards._load()` discards them, and `tests/test_guards.py::test_nothing_is_sent_to_the_internet`
checks that no network connection is attempted.

**Limits:** the personal-data patterns are regular expressions for Zimbabwean formats; they will miss
names and addresses. Only the question is masked, not the whole conversation.
