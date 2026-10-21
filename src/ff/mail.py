"""Send the briefing by email: `ff email`, the briefing skill's send path (C5). The files go on the wire as they are on
disk; the Gmail connector paste is the skill's fallback when no path is configured, so `ff doctor` prints `status()`
to say which path the run will take.

Two paths (C7). The cloud container's egress is a web proxy that carries HTTP and HTTPS only, so SMTP to
smtp.gmail.com:465 hangs there until it times out. The first path is therefore an HTTPS POST to a Google Apps Script
web app in Dustin's account (`scripts/gmail_send_relay.gs`, setup in `scripts/gmail_send_relay.md`) that sends with
GmailApp: `FF_MAIL_RELAY_URL` + `FF_MAIL_RELAY_TOKEN`. SMTP with a Gmail app password (`GMAIL_USER` +
`GMAIL_APP_PASSWORD`) is the path when only those are set, which works anywhere port 465 is open."""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

MISSING = ("FF_MAIL_RELAY_URL and FF_MAIL_RELAY_TOKEN (the Apps Script relay, scripts/gmail_send_relay.md) or "
           "GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env (Google account > Security > App passwords)")
RELAY_TIMEOUT = 60


def relay_configured() -> bool:
    return bool(os.getenv("FF_MAIL_RELAY_URL") and os.getenv("FF_MAIL_RELAY_TOKEN"))


def smtp_configured() -> bool:
    return bool(os.getenv("GMAIL_USER") and os.getenv("GMAIL_APP_PASSWORD"))


def configured() -> bool:
    return relay_configured() or smtp_configured()


def path() -> str:
    """Which send path `send` takes with the current environment: `relay`, `smtp` or `none`."""
    if relay_configured():
        return "relay"
    if smtp_configured():
        return "smtp"
    return "none"


def recipient(to: str | None = None) -> str | None:
    return to or os.getenv("BRIEFING_TO") or os.getenv("GMAIL_USER")


def status() -> str:
    """One line for `ff doctor`: which send path the briefing takes."""
    which = path()
    if which == "relay":
        return f"email: HTTPS relay (FF_MAIL_RELAY_URL, Apps Script) to {recipient() or 'BRIEFING_TO unset: ff email needs --to'} (ff email)"
    if which == "smtp":
        return f"email: SMTP as {os.getenv('GMAIL_USER')} to {recipient()} (ff email); SMTP hangs behind the cloud proxy, set FF_MAIL_RELAY_URL there"
    return "email: neither FF_MAIL_RELAY_URL/FF_MAIL_RELAY_TOKEN nor GMAIL_USER/GMAIL_APP_PASSWORD set; ff email will fail and the skill falls back to the Gmail connector paste"


def send(subject: str, markdown: str, to: str | None = None, html: str | None = None) -> str:
    """Send `markdown` as the plain part and `html` (or the markdown rendered) as the rich part; returns the recipient."""
    which = path()
    if which == "none":
        raise SystemExit(MISSING)
    to = recipient(to)
    if not to:
        raise SystemExit("no recipient: set BRIEFING_TO in .env or pass --to")
    if html is None:
        from .html import to_html
        html = to_html(markdown)
    if which == "relay":
        _send_relay(subject, markdown, html, to)
    else:
        _send_smtp(subject, markdown, html, to)
    return to


def relay_payload(subject: str, markdown: str, html: str, to: str) -> dict[str, str]:
    """The relay's request body; the files go in as they are, the script puts them on the wire unchanged."""
    return {"token": os.environ["FF_MAIL_RELAY_TOKEN"], "subject": subject, "to": to, "markdown": markdown, "html": html}


def _send_relay(subject: str, markdown: str, html: str, to: str) -> None:
    """POST to the Apps Script web app. Apps Script answers 200 (after a redirect) whatever happened, so the relay's
    own verdict is the `code` in its JSON body; anything but a 2xx there, or a body that is not its JSON, is a
    failure with the detail, so the skill knows to fall back."""
    url = os.environ["FF_MAIL_RELAY_URL"]
    try:
        r = requests.post(url, json=relay_payload(subject, markdown, html, to), timeout=RELAY_TIMEOUT)
    except requests.RequestException as exc:
        raise SystemExit(f"mail relay unreachable ({url}): {exc}") from exc
    if r.status_code >= 300:
        raise SystemExit(f"mail relay returned HTTP {r.status_code}: {r.text[:300]}")
    try:
        verdict = r.json()
    except ValueError:
        verdict = None
    if not isinstance(verdict, dict) or "code" not in verdict:
        raise SystemExit(f"mail relay answered with something other than its JSON verdict (is FF_MAIL_RELAY_URL the /exec URL of a "
                         f"deployed web app?): {r.text[:300]}")
    code = verdict.get("code")
    if verdict.get("ok") is not True or not isinstance(code, int) or not 200 <= code < 300:
        raise SystemExit(f"mail relay refused the send ({code}): {verdict.get('detail', '')}")


def _send_smtp(subject: str, markdown: str, html: str, to: str) -> None:
    user, pw = os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"]
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(markdown, "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)
