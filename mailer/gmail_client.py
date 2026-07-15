"""Gmail API client — sends the daily digest via OAuth (refresh token, no
password stored)."""
import base64
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import config


def get_gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=config.GMAIL_REFRESH_TOKEN,
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    return build("gmail", "v1", credentials=creds)


def send_email(service, body: str, job_count: int):
    from datetime import datetime
    subject = f"Job Alert — {job_count} new match(es), {datetime.now().strftime('%d %b')}"
    message = MIMEText(body)
    message["to"] = config.GMAIL_TO
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
