from app.pipeline.extract import find_urls, classify_urls, is_github_profile, is_linkedin


def test_find_urls_basic():
    text = "check https://github.com/alice and http://alice.dev/projects, also https://linkedin.com/in/alice."
    urls = find_urls(text)
    assert "https://github.com/alice" in urls
    assert any("alice.dev" in u for u in urls)


def test_classify_urls_picks_each():
    urls = [
        "https://github.com/alice",
        "https://linkedin.com/in/alice",
        "https://alice.dev",
    ]
    g, p, l = classify_urls(urls)
    assert g == "https://github.com/alice"
    assert p == "https://alice.dev"
    assert l == "https://linkedin.com/in/alice"


def test_is_github_profile():
    assert is_github_profile("https://github.com/alice")
    assert not is_github_profile("https://github.com/")
    assert not is_github_profile("https://example.com/alice")


def test_is_linkedin():
    assert is_linkedin("https://www.linkedin.com/in/alice")
    assert not is_linkedin("https://github.com/alice")
