from runtime.execution.suckers import web_skills as web


def test_search_normalizes_and_deduplicates_without_hiding_fallback(monkeypatch):
    monkeypatch.setattr(web, "_web_search_impl", lambda *args, **kwargs: {
        "backend": "brave", "fallback_from": "ddg", "results": [
            {"title": "A", "url": "https://example.org/a#one", "content": "Summary"},
            {"title": "A duplicate", "url": "https://example.org/a#two"},
            {"title": "Bad", "url": "javascript:alert(1)"},
        ]})
    result = web._web_search("question")
    assert result["result_count"] == 1
    assert result["provider"] == "brave"
    assert result["fallback_from"] == "ddg"
    assert result["results"][0]["snippet"] == "Summary"
    assert result["results"][0]["source"] == "example.org"
    assert result["elapsed_ms"] >= 0


def test_search_error_stays_an_error(monkeypatch):
    monkeypatch.setattr(web, "_web_search_impl", lambda *args, **kwargs: {"error": "unavailable", "results": []})
    assert web._web_search("question")["error"] == "unavailable"
