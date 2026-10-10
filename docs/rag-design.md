# Week 4: RAG design

## Purpose
The Week 4 retrieval system was the first working evidence layer for StartRight. It had to answer questions about business registration, tax and compliance in Zimbabwe using a small set of official documents and a source citation pattern. The project used 14 ingested documents, including six laws, the Harare business licence application form and seven ZIMRA public notices.

The design goal was simple: retrieve the right pages, keep costs low, and refuse answers when the evidence was weak or off-topic.

## How it works
The code in `src/startright/loaders.py`, `src/startright/chunking.py`, `src/startright/embeddings.py`, `src/startright/store.py` and `src/startright/rag.py` handled this flow.

1. PDF pages were read with `pypdf`.
2. Each page was chunked with a `max_chars` of 1,000 and `overlap` of 150 characters.
3. Local embeddings were produced with `sentence-transformers/all-MiniLM-L6-v2` and stored in Postgres with pgvector.
4. Retrieval used cosine similarity search with the top 4 chunks.
5. A minimum score of 0.25 filtered weak matches.
6. If no chunk met the threshold, the system returned a refusal without calling Groq.
7. The model then answered from the numbered source blocks and was instructed to cite them as `[1]`, `[2]`, and so on.

The project separated the retrieval pipeline from answer generation. Chunking, embedding and search were local and cost no tokens. Only the final Groq answer generation called the paid model.

## Key decisions and why
The main decision was to use local embeddings and pgvector instead of a hosted vector service. This matched the zero-budget requirement and allowed the project to keep the retrieval layer fully local.

The chunk size was set to 1,000 characters with 150-character overlap. That was large enough to keep legal context around a relevant clause, but small enough to limit the number of tokens passed to the model.

The score threshold of 0.25 was deliberately conservative. It allowed the system to reject off-topic questions with no model call, and this was important for controlling cost. The project later observed that refusing an off-topic question cost 0 tokens, while a tool-using agent refusal could cost hundreds of tokens.

The project also stored document metadata in `data/sources.csv`, including title, URL, type and dates. The ZIMRA notices had no publication date, so `doc_date` was left blank for them. This is also a good reminder that metadata quality matters and that some documents are only partially structured.

## Measured results
The project recorded these facts from the Week 4 run:
- It ingested 14 documents.
- It created about 2,785 chunks.
- The article split by document was roughly: Companies Act 1,399; VAT Act 557; Labour Act 407; Finance Act 212; NSSA Act 96; Labour Amendment Act 76; the rest were smaller.
- The source set included six laws, one Harare licence form and seven ZIMRA notices.
- The retrieval system used top 4 hits and a minimum score of 0.25.
- The project’s early runs showed both good and bad retrieval behaviour.

The findings were concrete:
- A question about a private company initially found only pages 176-180 (private business corporations), but a keyword search found the correct private company provisions on pages 63-79.
- The acronym "NSSA" failed to retrieve the correct source, while the full legal name "National Social Security Authority" worked.
- About 1,000-1,200 tokens were used per answered question.
- Off-topic questions cost 0 tokens because retrieval did not find a relevant document and the model was not called.

## Limitations and known issues
The retrieval system was useful, but it was not dependable enough by itself.

The biggest issue was semantic drift. A legal phrase could land close to the wrong document section, especially where a concept had multiple forms or related clauses. This was shown clearly in the private company problem, where vector search ranked the wrong explanation above the correct legal language.

Another weakness was acronym handling. The model and retrieval stack both struggled with short names like "NSSA", even though the full legal name identified the correct act.

A third issue was that source citation was not enough on its own. A cited answer could still be wrong, and the project later learned that every answer needed to be checked against the page itself before it was trusted.

TODO(verify): Labour Act: first run said maternity leave may start "no earlier than the 45th day" before delivery, one run said "40th day". Check page 31 of the Labour Act PDF.
TODO(verify): Companies Act page 30: the checklist said a reserved name is held "for up to one month". Check the page.
TODO(verify): Page references cited in my runs for the Companies Act: pages 12, 30, 170, 176-180, 203, 223, 292.

## What comes next
The Week 4 system proved the project could ingest local documents, search them and answer with citations. The lesson was not to keep adding more prompt instructions. The lesson was that retrieval quality needed improvement.

The Week 8 plan therefore fits naturally into the same direction: add BM25 keyword search next to vector search, add a reranker, tighten guardrails and benchmark hybrid search against vector-only search on a 40-50 question set. The failures above were the first examples that the project used to justify that work.
