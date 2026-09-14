"""Send the briefing by email over SMTP (Gmail app password). Used on headless servers."""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send(subject: str, markdown: str, to: str | None = None, html: str | None = None) -> None:
    user = os.getenv("GMAIL_USER")
    pw = os.getenv("GMAIL_APP_PASSWORD")
    if not (user and pw):
        raise SystemExit("GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env (Google account > Security > App passwords)")
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
