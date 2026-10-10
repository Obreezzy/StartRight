# Week 7: Structured output design

## Purpose
The Week 7 design kept the source grounding idea but moved it into a strict schema. The goal was to stop the model from writing a free-text answer and instead produce a machine-readable checklist such as `BusinessChecklist` with numbered steps, fees, deadlines and a `not_covered` section for missing information.

The project wanted to reduce the most common failure mode from earlier weeks: an answer that sounded official but still had invented fees, placeholder forms or unsupported timelines.

## How it works
The core logic lived in `src/startright/structured.py` and `src/startright/schemas.py`.

The flow was:
1. Gather a small set of source chunks from each relevant specialist domain using local retrieval.
2. Build a source bundle with numbered references.
3. Ask the model for JSON that matched the `BusinessChecklist` schema.
4. Validate the shape with Pydantic.
5. Validate the facts against the retrieved sources.
6. If either check failed, send the exact problem list back to the model and ask for a repair.
7. Stop after two repairs and fail honestly.

The schema was strict:
- `BusinessChecklist.business` is a business description.
- `steps` must be numbered 1..n in order.
- `ChecklistStep.source_n` must point at one of the provided sources.
- `Fee.amount` must be non-negative and `currency` must be a three-letter ISO code.
- placeholders such as `?`, `TBD`, `N/A`, `see Act` and `...` were rejected.
- `not_covered` was used for things the sources did not state, instead of inventing a gap.

A second validation layer in `validate_against_sources` checked source-backed facts directly. It rejected mismatched fees and unsupported claims such as percentages, day counts, cents and form names that did not appear in the source text.

## Key decisions and why
The main design choice was to separate schema validity from factual validity. Pydantic could verify the JSON structure, but it could not tell whether a sentence or fee was actually grounded in the source. The project therefore used a manual fact-checker that looked for the numeric or textual evidence in the retrieved source.

Another design decision was to refuse the request before the model call if the local retrieval found nothing relevant. This was important for cost control and for honesty. If there were no relevant results, the system returned a decline instead of wasting a Groq call.

The project also adopted a custom retry loop rather than using an external library. This kept the tooling simple and local and allowed the project to show exact repair messages to the model.

## Measured results
The Week 7 runs were the strongest in the project so far:
- Hair salon question: 2,060 tokens, 1 attempt.
- Shop and hire staff question: 2,050 tokens.
- Fee and timeline question: 2,004 tokens, and the system correctly listed exact fee amounts and processing times under `not_covered` instead of inventing them.
- Off-topic question: 0 tokens.
- `--json` output matched the schema.

This showed the checklist format was practical and that the system could say “not found in the sources retrieved for this question” without inventing facts.

## Limitations and known issues
The strict schema reduced invented facts, but it did not fully solve relevance problems.

One issue was that “valid” and “relevant” were not the same thing. A checklist could include a foreign-company step or a non-resident VAT step because the source texts allowed it, even when the user’s question was about a small local business. The project had to rely on the model to narrow the checklist to the person in the question.

Another issue was that the Harare shop licence form was missed for a salon phrasing but found for a direct “shop” question. This showed that the retrieval stage was still sensitive to phrasing and domain vocabulary.

The label “Not stated in the documents” was also misleading and was later renamed to “Not found in the sources retrieved for this question.” That wording is clearer and less likely to imply that a fact does not exist legally.

A final limitation was that weeks, months and years were not fact-checked in the same way as percentages, amounts, cents and form names. The project noted this as a real blind spot.

TODO(verify): Labour Act: first run said maternity leave may start "no earlier than the 45th day" before delivery, one run said "40th day". Check page 31 of the Labour Act PDF.
TODO(verify): Companies Act page 30: the checklist said a reserved name is held "for up to one month". Check the page.

## What comes next
The Week 7 checklist is the clearest prototype of a usable product flow. The next major step, as planned for Week 8, is to improve retrieval quality with BM25 keyword search and a reranker, then to benchmark the system on a 40-50 question set. The failures above are the first real test cases for that benchmark.

The project has already shown that structured output is useful when paired with source checks. The next improvement is not more model formatting; it is better retrieval and a stronger verifier so the checklist stays grounded even when the user asks a vague question.
