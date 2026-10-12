import pytest


@pytest.fixture(autouse=True)
def _traces_go_to_a_temporary_file(tmp_path, monkeypatch):
    """Tests must never write into the project's data/traces.jsonl."""
    monkeypatch.setenv("TRACE_FILE", str(tmp_path / "traces.jsonl"))
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    from startright import observability

    observability.reset()
    yield
    observability.reset()
