"""Markdown briefing -> email-safe HTML with inline CSS (Gmail strips <style> in many clients)."""
from __future__ import annotations

import re

import markdown as md

CSS = {
    "body": "font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.45;color:#1a1a1a;max-width:720px;margin:0 auto;padding:12px",
    "h1": "font-size:20px;margin:18px 0 6px",
    "h2": "font-size:17px;margin:22px 0 6px;padding-bottom:4px;border-bottom:2px solid #e5e5e5",
    "h3": "font-size:15px;margin:16px 0 4px;color:#444",
    "p": "margin:6px 0",
    "table": "border-collapse:collapse;font-size:13px;margin:8px 0;width:100%",
    "th": "text-align:left;padding:4px 6px;border-bottom:2px solid #ccc;background:#f4f4f4",
    "td": "padding:3px 6px;border-bottom:1px solid #eee;vertical-align:top",
    "hr": "border:0;border-top:2px dashed #bbb;margin:24px 0",
    "li": "margin:2px 0",
    "blockquote": "margin:8px 0;padding:6px 10px;background:#fff8e1;border-left:4px solid #f5c542",
}


def to_html(markdown_text: str) -> str:
    body = md.markdown(markdown_text, extensions=["tables", "sane_lists"])
    for tag, style in CSS.items():
        if tag == "body":
            continue
        body = re.sub(rf"<{tag}(\s|>)", f'<{tag} style="{style}"\\1', body)
    return f'<div style="{CSS["body"]}">{body}</div>'
