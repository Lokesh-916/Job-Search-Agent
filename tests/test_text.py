from job_agent.text import html_to_text


def test_lists_and_paragraphs():
    raw = "<h3>Role</h3><p>Build &amp; ship agents.</p><ul><li>Python</li><li>LLMs</li></ul>"
    assert html_to_text(raw) == "Role\nBuild & ship agents.\n- Python\n- LLMs"


def test_truncates_on_word_boundary():
    out = html_to_text("<p>alpha beta gamma delta</p>", max_chars=12)
    assert out == "alpha beta …"


def test_empty():
    assert html_to_text(None) == ""
