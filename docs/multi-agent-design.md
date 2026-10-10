# Week 6: Multi-agent design

## Purpose
The Week 6 system moved from one tool-using agent to a small team of specialists. The purpose was to split the question by topic so each model instance stayed inside a narrower domain: registration and licensing, tax, or employment and social security. The idea was to reduce cross-topic confusion and make verification easier.

## How it works
The flow in `src/startright/multiagent.py` was:
1. Coordinator: a model call that returned JSON describing which specialists were needed.
2. Keyword fallback: if the coordinator output was unreadable, a simple keyword router picked relevant specialist(s).
3. Specialist runs: three agents, each scoped to a set of documents.
4. Verifier: plain code checked whether the specialist answer used real citations and whether figures, percentages, day counts, cents and form names appeared in the sources or tool results.
5. One revision loop: the specialist was told about the issues and asked to fix them once.
6. Compose step: the system merged the specialist outputs, renumbered citations globally and added the legal footer.

The specialist scopes were:
- registration and licensing: Companies Act and Harare business licence form
- tax: VAT Act, Finance Act 2024 and ZIMRA notices
- employment: Labour Act, Labour Amendment Act 2023, NSSA Act

State was shared between nodes so the coordinator, specialists, verifier and composer could all see the plan, findings, issues, token count and next citation numbers.

## Key decisions and why
The most important decision was to keep specialist scopes small and explicit. For example, the tax specialist was allowed to search only the VAT Act, Finance Act, and ZIMRA notices. That prevented a tax answer from drifting into labour law or company formation questions.

The second major decision was to use a plain code verifier instead of trusting the model to self-check. The original verifier only checked whether cited numbers existed in the source, but it did not check whether the wording supported the claim. A more robust grounding check was added later so that percentages, fees, day counts, amounts, cents and form names had to appear in source text or tool output.

A third decision was to keep the final compose step separate from the specialists. That made it easier to renumber citations consistently and add the legal footer without mixing it into the specialist reasoning itself.

## Measured results
These results are noted from the project history and are not a claim of reproducible benchmark performance:
- The first two-specialist run used 12,197 tokens and included invented specifics with valid-looking citations.
- The first verifier was too weak because it only checked whether cited numbers existed, not whether the statement was supported.
- After the grounding check and prompt fixes, the VAT question cost 3,130 tokens, then 10,356, then 4,816 tokens after the correction cycle.
- The second two-specialist run was 16,079 tokens before the final fix.
- After the fixes, maternity questions used 2,676 and 2,746 tokens, and VAT used 4,816 tokens.
- Off-topic declines cost 272 and 326 tokens.

These numbers show the project was learning from failure, but it also showed that verification and revision cycles could become expensive.

## Limitations and known issues
The team design was a big improvement, but it still had real weaknesses.

One failure mode was citation mismatch: a citation could be attached to a claim it did not truly support, such as the "91 days ago" figure being cited to ZIMRA Notice 23, which was actually about April VAT return dates. This was a reminder that citation is not the same as ground truth.

Another issue was placeholder wording. Some registration answers still included placeholders such as "(Form ? - see Act)". That meant a model could produce an answer that looked structured but still lacked a real source-backed step.

The coordinator also leaked a wrong date into a task and told a specialist that days could not be calculated. That was corrected by stricter prompt rules, but it showed that model-generated plans still needed both code guardrails and verifier checks.

TODO(verify): Companies Act page 30: the checklist said a reserved name is held "for up to one month". Check the page.
TODO(verify): Page references cited in my runs for the Companies Act: pages 12, 30, 170, 176-180, 203, 223, 292.

## What comes next
The Week 6 system was a practical bridge to Week 7. It showed that a multi-agent plan could work, but only when verification was explicit and grounded in source text. The project’s plan for Week 8 fits the same direction: add BM25 keyword search next to vector search, add a reranker, add stronger guardrails, and run a 40-50 question benchmark to compare hybrid search with vector-only search.

The main lesson from Week 6 was not that the team had to be larger. The lesson was that the first thing the team needed was a reliable way to reject invented facts early, before they reached the final answer.
