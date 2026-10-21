"""`ff email` is the briefing's send path (C5): the model used to paste briefing.html into the Gmail connector line by
line and compare `wc -c` with what it had assembled, so a truncated or mangled email was one skipped line away. Both
paths send the two files as they are on disk: the Apps Script relay (C7, an HTTPS POST, the only path the cloud proxy
carries) against a stub `requests.post`, SMTP against a stub SMTP server; these tests hold them to that."""
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


class StubRelay:
    """Records the one POST `mail.send` makes to the Apps Script web app and answers as the script does: HTTP 200 (Apps
    Script never sets another status on a web-app response) with the verdict in the JSON body."""
    posts: list = []
    verdict: dict | None = {"ok": True, "code": 200, "detail": "sent"}
    text: str = ""

    def __init__(self, status_code: int, text: str):
        self.status_code, self.text = status_code, text

    def json(self):
        import json
        return json.loads(self.text)

    @classmethod
    def post(cls, url, json=None, timeout=None):
        import json as _json
        cls.posts.append({"url": url, "json": json, "timeout": timeout})
        return cls(200, _json.dumps(cls.verdict) if cls.verdict is not None else cls.text)


@pytest.fixture
def smtp(monkeypatch):
    StubSMTP.sent, StubSMTP.logins = [], []
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", StubSMTP)
    monkeypatch.setenv("GMAIL_USER", "bot@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-pass")
    monkeypatch.setenv("BRIEFING_TO", "dustin@example.com")
    monkeypatch.delenv("FF_MAIL_RELAY_URL", raising=False)
    monkeypatch.delenv("FF_MAIL_RELAY_TOKEN", raising=False)
    return StubSMTP


@pytest.fixture
def relay(monkeypatch):
    StubRelay.posts, StubRelay.verdict, StubRelay.text = [], {"ok": True, "code": 200, "detail": "sent"}, ""
    monkeypatch.setattr(mail.requests, "post", StubRelay.post)
    monkeypatch.setenv("FF_MAIL_RELAY_URL", "https://script.google.com/macros/s/AKfycb-relay/exec")
    monkeypatch.setenv("FF_MAIL_RELAY_TOKEN", "relay-tok")
    monkeypatch.setenv("BRIEFING_TO", "dustin@example.com")
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    return StubRelay


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


def test_ff_email_posts_the_html_and_markdown_files_verbatim_to_the_relay(tmp_path: Path, relay):
    """C7: in the cloud the only route out is HTTPS, so the send is a POST to the Apps Script web app with the two files
    in the body as they are on disk; the script puts them on the wire unchanged (scripts/gmail_send_relay.test.js)."""
    md, html = tmp_path / "briefing.md", tmp_path / "briefing.html"
    md.write_text(MARKDOWN); html.write_text(HTML)
    r = runner.invoke(app, ["email", str(md), "--html", str(html), "--subject", "FF briefing — Week 7 — 2026-10-20"])
    assert r.exit_code == 0, r.output
    assert len(relay.posts) == 1, "exactly one POST, one email"
    post = relay.posts[0]
    assert post["url"] == "https://script.google.com/macros/s/AKfycb-relay/exec"
    assert post["timeout"], "a hung proxy must not hold the briefing run forever"
    body = post["json"]
    assert set(body) == {"token", "subject", "to", "markdown", "html"}, "the relay's contract: these five fields, nothing else"
    assert body["token"] == "relay-tok"
    assert body["subject"] == "FF briefing — Week 7 — 2026-10-20"
    assert body["to"] == "dustin@example.com", "the recipient is BRIEFING_TO when --to is not given"
    assert body["html"] == HTML, "the rich body is briefing.html byte for byte, closing tags included"
    assert body["markdown"] == MARKDOWN, "the plain fallback is briefing.md"
    assert "dustin@example.com" in r.output, "the log line names where it went"


def test_relay_wins_over_smtp_when_both_are_configured(tmp_path: Path, relay, monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "bot@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-pass")
    StubSMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", StubSMTP)
    md = tmp_path / "briefing.md"
    md.write_text(MARKDOWN)
    r = runner.invoke(app, ["email", str(md), "--subject", "FF briefing — Week 7 — 2026-10-20"])
    assert r.exit_code == 0, r.output
    assert len(relay.posts) == 1 and StubSMTP.sent == [], "the relay is the path when both are set; SMTP only when it alone is"
    assert mail.path() == "relay"


def test_relay_refusal_fails_ff_email_so_the_skill_falls_back(tmp_path: Path, relay):
    """Apps Script answers HTTP 200 whatever happened; the verdict is the `code` in the body, and a refusal there is a
    failed send, not a success with a strange log line."""
    relay.verdict = {"ok": False, "code": 403, "detail": "bad token"}
    md = tmp_path / "briefing.md"
    md.write_text(MARKDOWN)
    r = runner.invoke(app, ["email", str(md), "--subject", "FF briefing — Week 7 — 2026-10-20"])
    assert r.exit_code != 0
    assert "403" in r.output and "bad token" in r.output, "the relay's reason reaches the run log"
    assert "sent '" not in r.output


def test_relay_answering_a_login_page_is_a_failure_that_names_the_deployment(tmp_path: Path, relay):
    """A wrong URL (the editor's /dev URL, or a deployment that is not 'Anyone') answers with Google's sign-in HTML."""
    relay.verdict, relay.text = None, "<!doctype html><html><body>Sign in</body></html>"
    md = tmp_path / "briefing.md"
    md.write_text(MARKDOWN)
    r = runner.invoke(app, ["email", str(md), "--subject", "FF briefing — Week 7 — 2026-10-20"])
    assert r.exit_code != 0
    assert "/exec" in r.output


def test_relay_without_a_recipient_fails_instead_of_guessing(tmp_path: Path, relay, monkeypatch):
    monkeypatch.delenv("BRIEFING_TO")
    md = tmp_path / "briefing.md"
    md.write_text(MARKDOWN)
    r = runner.invoke(app, ["email", str(md), "--subject", "x"])
    assert r.exit_code != 0 and "BRIEFING_TO" in r.output
    assert relay.posts == []
    r = runner.invoke(app, ["email", str(md), "--subject", "x", "--to", "me@example.com"])
    assert r.exit_code == 0, r.output
    assert relay.posts[0]["json"]["to"] == "me@example.com"


def test_status_names_the_path_ff_doctor_will_take(relay, monkeypatch):
    assert mail.path() == "relay" and "relay" in mail.status() and "dustin@example.com" in mail.status()
    monkeypatch.delenv("FF_MAIL_RELAY_TOKEN")
    monkeypatch.setenv("GMAIL_USER", "bot@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app-pass")
    assert mail.path() == "smtp" and "SMTP" in mail.status() and "FF_MAIL_RELAY_URL" in mail.status(), \
        "a half-set relay falls back to SMTP and the doctor line says what the cloud needs"
    monkeypatch.delenv("GMAIL_APP_PASSWORD")
    assert mail.path() == "none" and not mail.configured()
    assert "Gmail connector" in mail.status() and "FF_MAIL_RELAY_URL" in mail.status() and "GMAIL_USER" in mail.status()
