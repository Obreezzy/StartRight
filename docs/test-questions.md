# Test questions and findings

## Week 4 RAG questions

### RAG questions
| # | Question | Source area | Result | Notes |
|---|---|---|---|---|
| 1 | What do I need to register a private company? | Companies Act | FAIL → PASS after keyword search | Vector search ranked pages 176-180 (private business corporations) first, but keyword search found the real private company provisions on pages 63-79. This showed the need for a hybrid search approach in Week 8. |
| 2 | When must an employer register with NSSA? | NSSA Act | FAIL → PASS with the full name | The acronym "NSSA" retrieved Labour Act pages and the model refused. Using "National Social Security Authority" retrieved the NSSA Act pages and produced an answer. |
| 3 | How do I understand the difference between a private company and a private business corporation? | Companies Act | Mixed | It showed that citations can still look convincing even when the answer is not fully grounded. |

### Findings from Week 4
- Keyword search found the private company provisions on pages 63-79 of the Companies and Other Business Entities Act; vector search returned only pages 176-180 (private business corporations).
- The acronym problem was real: the acronym "NSSA" was not enough; the full legal name "National Social Security Authority" was needed to find the relevant source.
- Cited answers can still be wrong, so every answer must be verified against the PDF page.
- About 1,000-1,200 tokens were used per answered question; off-topic questions cost 0 tokens because the system refused before a model call.

## Week 5 agent runs

### Agent questions
| # | Question | Area | Result | Notes |
|---|---|---|---|---|
| 1 | What is the total fee for the items I gave you? | Fees | PASS | Fee total 85.50 was calculated correctly using exact Decimal sums. |
| 2 | VAT return due date question | Tax | FAIL before fix | An early run skipped a search, guessed the due day and cited a source that did not exist. |
| 3 | Check a VAT due date from a source | Tax | PASS after fix | The guardrail in code forced a search before `check_deadline` was allowed. |
| 4 | Maternity leave question | Employment | PASS | Answer used 2,257 tokens. |
| 5 | Off-topic question | General | PASS refusal | The agent refused cleanly, but it cost 588 tokens compared with 0 in plain ask mode. |

### Findings from Week 5
- The agent needed three tools: `search_regulations`, `calculate_fees` and `check_deadline`.
- A code-level guardrail was essential: `check_deadline` was blocked until a search had returned results.
- The agent still had a risk of model memory leaking into legal reasoning when a search result was weak or missing.
- The off-topic refusal path was much more expensive than a direct retrieval-only refusal.

## Week 6 team runs

### Team questions
| # | Question | Area | Result | Notes |
|---|---|---|---|---|
| 1 | Two-specialist run | Mixed | FAIL | Invented specifics with valid-looking citations, including incorrect NSSA rates and fake form names. |
| 2 | Maternity question | Employment | PASS after fixes | Better grounding improved the answer. |
| 3 | VAT question | Tax | PASS after fixes | The verifier and source checks reduced unsupported claims. |
| 4 | Off-topic question | General | PASS refusal | Decline still happened without hallucinating a legal answer. |

### Findings from Week 6
- The first verifier only checked that cited numbers existed, not that the claim was actually supported by the source.
- The coordinator could leak wrong planning dates or say that days could not be calculated.
- Source numbering and global citation renumbering were needed so specialists did not conflict.
- A citation could still attach to a summary that was not actually supported by the right source.
- Registration answers sometimes contained placeholders such as "(Form ? - see Act)".

## Week 7 checklist runs

### Checklist questions
| # | Question | Area | Result | Notes |
|---|---|---|---|---|
| 1 | Hair salon question | Registration and compliance | PASS | 2,060 tokens, 1 attempt. |
| 2 | Shop and hire staff question | Registration and compliance | PASS | 2,050 tokens. |
| 3 | Fee and timeline question | Tax and compliance | PASS | The system listed exact fees and processing times under `not_covered` instead of inventing them. |
| 4 | Off-topic question | General | PASS refusal | 0 tokens. |

### Findings from Week 7
- The `BusinessChecklist` schema gave a reliable structure, but relevance was still separate from validity.
- The Harare shop licence form was missed for the salon phrasing but found for the direct “shop” question.
- “Not stated in the documents” was misleading; it was renamed to “Not found in the sources retrieved for this question”.

Weeks, months and years were not fact-checked in the same way as percentages, fees and form names.
- The live retry loop never triggered in the runs observed; the proof of the repair path was in unit tests.

## Week 8 hybrid retrieval and guardrail checks

### Benchmark questions
| # | Question | Area | Result | Notes |
|---|---|---|---|---|
| 1 | `q03` | Entity / PBC | MISS across all modes | The benchmark phrase may be too strict, or retrieval may still be failing on the legal wording. |
| 2 | `q21` | Acronym / NSSA | PASS in hybrid and rerank | The acronym expansion fix in `retrieval.py` helped here; vector-only still missed it. |
| 3 | `q26` / `q31` | VAT and notice questions | VECTOR-only wins | The plain vector baseline still found the VAT questions that BM25, hybrid and rerank missed. |
| 4 | `q33` | General retrieval miss | MISS across all modes | Needs a follow-up check on whether the key phrase is too strict or the chunk is truly missing. |

### Findings from Week 8
- The code provides four retrieval modes: `vector`, `bm25`, `hybrid` and `hybrid_rerank`.
- `RETRIEVAL_MODE` chooses the mode used by the agent, team and checklist flows.
- The default `ask` command remains vector-only to preserve the Week 4 baseline.
- Hybrid search alone was not a clear win on this benchmark: it tied vector on Hit@4 and was slightly below vector on MRR.
- The measurable gain came from the reranker: `hybrid_rerank` reached 89% Hit@4 and 0.82 MRR after text cleaning, compared with vector at 84% and 0.76.
- The benchmark dataset had a data-quality issue: ligature characters caused PDF text extraction to store sequences like `fi` and `fl` as single glyphs, which broke plain keyword matching in a few cases.
- The text-cleaning fix changed the benchmark outcome only for `q02`, because few benchmark questions were affected by ligature-based terms.

### Benchmark results after text cleaning
- vector: 84% Hit@4, MRR 0.76
- bm25: 82% Hit@4, MRR 0.74
- hybrid: 84% Hit@4, MRR 0.75
- hybrid_rerank: 89% Hit@4, MRR 0.82
- refusals: 6/6 correct refusals in every mode; 0 false refusals in every mode

### Benchmark results before text cleaning
- vector: 82% Hit@4, MRR 0.73
- bm25: 80% Hit@4, MRR 0.71
- hybrid: 82% Hit@4, MRR 0.72
- hybrid_rerank: 86% Hit@4, MRR 0.80

### Honest summary
- Plain hybrid was not the winner; hybrid plus reranking was.
- Acronym handling improved for NSSA questions, but not every legal acronym is solved by the same expansion map.
- No mode wins everywhere: vector still found some VAT questions that the BM25/hybrid paths missed.
- Small benchmark deltas are directional only because the answerable set contains 44 questions; one question equals about 2.3 percentage points.
- TODO(verify): confirm whether `q03` and `q33` are retrieval misses or benchmark-keyword errors.
- TODO(verify): paste the ligature-count query result before and after text cleaning.

## Findings that motivate Week 8
- Vector-only retrieval can miss the real legal provision even when a nearby page is semantically close.
- Acronym handling is weak; full legal names must be used to find the correct document.
- A citation is not proof; it can still be attached to a wrong fact.
- Strict schema validation helps, but retrieval quality matters more than formatting.
- The project needs BM25 keyword search, a reranker and stronger guardrails before claiming good legal answers.

TODO(verify): Labour Act: first run said maternity leave may start "no earlier than the 45th day" before delivery, one run said "40th day". Check page 31 of the Labour Act PDF.
TODO(verify): Companies Act page 30: the checklist said a reserved name is held "for up to one month". Check the page.
TODO(verify): Page references cited in my runs for the Companies Act: pages 12, 30, 170, 176-180, 203, 223, 292.