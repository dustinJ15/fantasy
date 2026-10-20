"""Send the briefing by email over SMTP (Gmail app password): `ff email`, the briefing skill's send path (C5). The
files go on the wire as they are on disk; the Gmail connector paste is the skill's fallback when the credentials
are missing, so `ff doctor` prints `status()` to say which path the run will take."""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

MISSING = "GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env (Google account > Security > App passwords)"


def configured() -> bool:
    return bool(os.getenv("GMAIL_USER") and os.getenv("GMAIL_APP_PASSWORD"))


def status() -> str:
    """One line for `ff doctor`: which send path the briefing takes."""
    if configured():
        return f"email: SMTP as {os.getenv('GMAIL_USER')} to {os.getenv('BRIEFING_TO') or os.getenv('GMAIL_USER')} (ff email)"
    return "email: GMAIL_USER/GMAIL_APP_PASSWORD not set; ff email will fail and the skill falls back to the Gmail connector paste"


def send(subject: str, markdown: str, to: str | None = None, html: str | None = None) -> str:
    """Send `markdown` as the plain part and `html` (or the markdown rendered) as the rich part; returns the recipient."""
    user = os.getenv("GMAIL_USER")
    pw = os.getenv("GMAIL_APP_PASSWORD")
    if not (user and pw):
        raise SystemExit(MISSING)
    to = to or os.getenv("BRIEFING_TO") or user
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(MIMEText(markdown, "plain"))
    if html is None:
        from .html import to_html
        html = to_html(markdown)
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)
    return to
