# StartRight

An AI assistant that helps aspiring business owners in Zimbabwe understand what they must register, license and pay, using local retrieval and grounded source citations.

**Status:** Weeks 1-7 are done.

## Stack
- Python
- FastAPI
- PostgreSQL 16 with pgvector in Docker
- Local embeddings with sentence-transformers all-MiniLM-L6-v2 (384 dims)
- Groq API model: openai/gpt-oss-20b with reasoning_effort low
- LangGraph
- Pydantic v2
- GitHub Actions CI

This is general information, not legal advice.

## How to run
From the repository root:

- Ingest the documents:
  `python -m startright.cli ingest`
- Ask a single question:
  `python -m startright.cli ask "What do I need to register a private company?"`
- Run the tool-using agent:
  `python -m startright.cli agent "When is the VAT return due?"`
- Run the specialist team:
  `python -m startright.cli team "What do I need to start a shop and hire staff?"`
- Run the checklist builder:
  `python -m startright.cli checklist "I want to open a salon"`
- Run the checklist builder as JSON:
  `python -m startright.cli checklist "I want to open a salon" --json`

The system is designed for a zero-budget setup. It uses free-tier or local services only, and the only external model call is the Groq answer generation step. Chunking, embedding and search are local and do not spend tokens.

## Free-tier / local note
StartRight is intentionally built for a zero budget. The database runs in Docker on the local machine, the embedding model is local, and the Groq call is only used for answer generation. Do not add API keys or secrets to files in the repo.

## Documentation index
- [BRD.md](docs/BRD.md)
- [agent-design.md](docs/agent-design.md)
- [multi-agent-design.md](docs/multi-agent-design.md)
- [rag-design.md](docs/rag-design.md)
- [structured-output-design.md](docs/structured-output-design.md)
- [test-questions.md](docs/test-questions.md)

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md).