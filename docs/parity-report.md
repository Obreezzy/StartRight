# Environment parity report

Run at 2026-10-13 21:52 UTC.

| | Local | Staging |
|---|---|---|
| URL | http://127.0.0.1:8002 | https://startright-3phu.onrender.com |
| Health | ok | ok |
| Model | openai/gpt-oss-20b | openai/gpt-oss-20b |
| Search mode | bm25_light | bm25_light |

## Same questions on both

| Question | Mode | Local (kind, tokens, seconds) | Staging (kind, tokens, seconds) |
|---|---|---|---|
| What does the Labour Act say about maternity leave? | answer | answer, 5237, 4.6s | answer, 5247, 8.9s |
| What do I need to register a private company? | answer | HTTP 429 | answer, 5534, 43.6s |
| Hair salon in Harare | checklist | HTTP 429 | checklist, 2163, 14.0s |

## Checks

| Check | Result | Detail |
|---|---|---|
| both sites are healthy | PASS | ok / ok |
| same model | PASS | openai/gpt-oss-20b / openai/gpt-oss-20b |
| answer: What does the Labour Act say about mater: same kind of result | PASS | answer / answer |
| answer: What does the Labour Act say about mater: cites at least one common source | PASS | Labour Act [Chapter 28:01] p31 |
| answer: What do I need to register a private com answered on both | FAIL | HTTP 429 / ok |
| checklist: Hair salon in Harare answered on both | FAIL | HTTP 429 / ok |

Expected differences: the search mode may differ (the hosted site runs the model-free `bm25_light` mode to fit 512 MB of memory), and answer wording varies between runs.
