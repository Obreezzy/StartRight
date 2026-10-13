# Sending user data to third-party language models: compliance note

This is a working note for the Week 10 review, not legal advice. It should be checked against
Zimbabwe's Cyber and Data Protection Act and the providers' current terms before a real launch.

## What goes to which provider
See `docs/data-flow.md`. In short: Groq receives the masked question plus public passages; Cohere (if
enabled) receives the same; Langfuse (if enabled) receives metadata only.

## Position taken
1. **Data minimisation.** Collect nothing on purpose. The page tells visitors not to type personal details.
2. **Mask before sending.** ID numbers, phone numbers and emails are replaced before any third-party call.
3. **No storage of questions.** We keep sizes and timings only; nothing in the trace file holds question text.
4. **Public sources only.** The document store holds public legal and tax texts, so the passages sent out are not
   confidential.
5. **Disclosure.** The page states that questions are processed by third-party AI services and that the answer is
   general information, not legal advice.

## Provider checklist (fill in before launch)
| Provider | Trains on API data? | Retention | Region | Terms checked on |
|---|---|---|---|---|
| Groq | to check on groq.com terms | to check | to check | |
| Cohere | to check (trial vs production terms differ) | to check | to check | |
| Langfuse | metadata only | per plan | EU or US cloud | |
| Neon | holds public documents only | n/a | us-east-1 | |

## Residual risks
- Names, addresses and free-text details are not masked; they could reach Groq.
- Trial and free tiers can have weaker terms than paid ones (for example on data use or commercial use).
- Masking uses patterns for Zimbabwean formats and misses other formats.

## What would reduce the risk further
- A named-entity detector for names and addresses (adds a model, so not on the 512 MB server).
- A provider with a signed data-processing agreement and zero data retention.
- A consent notice shown before the first question.
