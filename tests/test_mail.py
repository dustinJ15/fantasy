"""`ff email` is the briefing's send path (C5): the model used to paste briefing.html into the Gmail connector line by
line and compare `wc -c` with what it had assembled, so a truncated or mangled email was one skipped line away. The
SMTP path sends the two files as they are on disk; these tests hold it to that against a stub SMTP server."""
from __future__ import annotations

import email
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ff import mail
from ff.cli import app

runner = CliRunner()
HTML = "<html><body>\n<p>Hold Hubbard</p>\n<p>ünïcode · μ 17.8</p>\n</body></html>\n"
MARKDOWN = "# Week 7\n\n- Hold Hubbard\n"


class StubSMTP:
    """Records the one message `mail.send` hands to smtplib.SMTP_SSL."""
    sent: list = []
    logins: list = []

    def __init__(self, host, port, timeout=None):
        assert (host, port) == ("smtp.gmail.com", 465)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, pw):
        StubSMTP.logins.append((user, pw))

    def send_message(self, msg):
        StubSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    StubSMTP.sent, StubSMTP.logins = [], []
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", StubSMTP)
    monkeypatch.setenv("GMAIL_USER", "bot@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-pass")
    monkeypatch.setenv("BRIEFING_TO", "dustin@example.com")
    return StubSMTP


def parts(msg) -> dict[str, str]:
    parsed = email.message_from_bytes(msg.as_bytes())
    return {p.get_content_type(): p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8")
            for p in parsed.walk() if not p.is_multipart()}


def test_ff_email_sends_the_html_and_markdown_files_verbatim(tmp_path: Path, smtp):
    md, html = tmp_path / "briefing.md", tmp_path / "briefing.html"
    md.write_text(MARKDOWN); html.write_text(HTML)
    r = runner.invoke(app, ["email", str(md), "--html", str(html), "--subject", "FF briefing — Week 7 — 2026-10-20"])
    assert r.exit_code == 0, r.output
    assert len(smtp.sent) == 1, "exactly one email"
    msg = smtp.sent[0]
    assert msg["Subject"] == "FF briefing — Week 7 — 2026-10-20"
    assert msg["To"] == "dustin@example.com", "the recipient is BRIEFING_TO when --to is not given"
    assert msg["From"] == "bot@example.com"
    assert smtp.logins == [("bot@example.com", "app-pass")]
    body = parts(msg)
    assert body["text/html"] == HTML, "the rich body is briefing.html byte for byte, closing tags included"
    assert body["text/plain"] == MARKDOWN, "the plain fallback is briefing.md"
    assert "dustin@example.com" in r.output, "the log line names where it went"


def test_ff_email_without_credentials_fails_so_the_skill_falls_back(tmp_path: Path, monkeypatch, smtp):
    monkeypatch.delenv("GMAIL_APP_PASSWORD")
    md = tmp_path / "briefing.md"
    md.write_text(MARKDOWN)
    r = runner.invoke(app, ["email", str(md)])
    assert r.exit_code != 0
    assert "GMAIL_USER and GMAIL_APP_PASSWORD" in r.output
    assert smtp.sent == []


def test_ff_email_renders_the_markdown_when_no_html_is_given(tmp_path: Path, smtp):
    md = tmp_path / "note.md"
    md.write_text("cookies need refreshing, see scripts/setup_cookies.md\n")
    r = runner.invoke(app, ["email", str(md), "--subject", "FF briefing FAILED — 2026-10-20", "--to", "me@example.com"])
    assert r.exit_code == 0, r.output
    msg = smtp.sent[0]
    assert msg["To"] == "me@example.com"
    assert "cookies need refreshing" in parts(msg)["text/html"]
