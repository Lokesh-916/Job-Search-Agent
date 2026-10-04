import pytest

from job_agent.bot import BadCommand, Invocation, chunks, help_text, parse


@pytest.mark.parametrize(
    ("command", "words", "expected"),
    [
        ("status", [], Invocation(["status"])),
        ("now", [], Invocation(["now"])),
        ("now", ["25"], Invocation(["now", "--limit", "25"])),
        ("schedule", ["3"], Invocation(["schedule", "3"])),
        ("schedule", ["22", "once"], Invocation(["schedule", "22", "--once"])),
        ("top", ["20"], Invocation(["top", "--compact", "-n", "20"])),
        ("show", ["112024"], Invocation(["show", "112024"])),
        ("pitch", ["112024"], Invocation(["pitch", "112024"], llm=True)),
        ("ask", ["remote", "AI", "jobs?"], Invocation(["ask", "remote AI jobs?"], llm=True)),
    ],
)
def test_parse_valid(command, words, expected):
    assert parse(command, words) == expected


@pytest.mark.parametrize(
    ("command", "words"),
    [
        ("schedule", ["24"]),
        ("schedule", ["3", "weekly"]),
        ("now", ["; rm -rf ~"]),
        ("show", ["../etc"]),
        ("pitch", []),
        ("ask", []),
        ("deploy", []),
    ],
)
def test_parse_rejects_bad_input(command, words):
    with pytest.raises(BadCommand):
        parse(command, words)


def test_chunks_respect_limit_and_lines():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
    parts = chunks(text, size=500)
    assert all(len(p) <= 500 for p in parts)
    assert "".join(parts).count("line ") == 200


def test_help_lists_every_command():
    text = help_text()
    for name in ("status", "now", "schedule", "ask", "pitch", "tailor"):
        assert f"/{name}" in text
