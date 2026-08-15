"""
Sends real email via Gmail SMTP using an App Password (not OAuth) - the
simplest integration path: no Google Cloud project, no consent screen,
just smtplib talking to smtp.gmail.com with an app-scoped password.

Used by Agent 1's "escalate to email" action (POST /deals/{deal_id}/notify-email)
so an actual notification lands in the recipient's inbox, not just a log row.
"""
import smtplib
from email.mime.text import MIMEText

from . import config

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class GmailNotConfigured(RuntimeError):
    pass


def send_email(to_email: str, subject: str, body: str) -> None:
    if not config.GMAIL_SENDER_ADDRESS or not config.GMAIL_APP_PASSWORD:
        raise GmailNotConfigured(
            "GMAIL_SENDER_ADDRESS / GMAIL_APP_PASSWORD not set in .env - "
            "see README.md for how to generate a Gmail App Password."
        )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_SENDER_ADDRESS
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(config.GMAIL_SENDER_ADDRESS, config.GMAIL_APP_PASSWORD)
        smtp.sendmail(config.GMAIL_SENDER_ADDRESS, [to_email], msg.as_string())
