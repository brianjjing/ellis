"""Rough, demo-grade Gmail search -- our own code, not Creao's connector, so we control exactly which
inbox gets searched instead of depending on Creao's one-connection-per-agent limit.

Setup (you do this part -- it needs a real Google account and can't be done from here):
  1. console.cloud.google.com -> new project -> enable the Gmail API.
  2. OAuth consent screen: External, add yourself as a test user. Credentials: OAuth client ID,
     type "Desktop app". Download the JSON, save it as backend/.gmail_client_secret.json (gitignored).
  3. uv run --extra gmail python -m ellis.agents.gmail_search setup
     Opens a browser for YOU to click through the consent screen once; caches a token at
     backend/.gmail_token.json (gitignored). Re-run this once per Gmail account you want to search
     (the client's test account, the clinic's own account -- whichever you're demoing with).
  4. uv run --extra gmail python -m ellis.agents.gmail_search search <token_path> 2024-09-01

Until step 3 is done, MockGmailService below lets the rest of the pipeline (consent -> search ->
task proposal) run end-to-end against canned data, so the demo isn't blocked on OAuth setup.
"""
from __future__ import annotations

import os
import sys
from datetime import date

CLIENT_SECRET_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".gmail_client_secret.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TRAVEL_KEYWORDS = ["flight", "boarding pass", "itinerary", "booking confirmation", "e-ticket", "reservation"]


def get_service(token_path: str):
    """Real Gmail API service, read-only. Requires step 3 above to have been run for this token_path."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def search_travel_emails(service, around: date, window_days: int = 7) -> list[dict]:
    """Candidates only -- snippet + date, never auto-confirmed. Caller decides what to do with them.

    Deliberately NOT filtering by Gmail's after:/before: here -- those match when the email was
    RECEIVED, not the travel date mentioned inside it (a flight confirmation is often booked weeks or
    months before the trip), so a receive-date filter would miss real matches. Keyword-only; `around`
    is accepted for a future improvement (parsing the matched email's own stated dates) but unused for
    now -- rough, for the demo."""
    query = "(" + " OR ".join(f'"{k}"' for k in TRAVEL_KEYWORDS) + ")"
    resp = service.users().messages().list(userId="me", q=query, maxResults=5).execute()
    out = []
    for m in resp.get("messages", []):
        msg = service.users().messages().get(userId="me", id=m["id"], format="metadata",
                                             metadataHeaders=["Subject", "Date"]).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        out.append({"id": m["id"], "subject": headers.get("Subject", ""), "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", "")})
    return out


class MockGmailService:
    """Demo fallback when real OAuth isn't set up yet -- same interface shape as search_travel_emails'
    real caller needs, canned data only. Never used unless explicitly passed in."""
    def __init__(self, canned: list[dict] | None = None):
        self.canned = canned if canned is not None else [
            {"id": "mock1", "subject": "Your e-ticket confirmation", "date": "Sun, 1 Sep 2024 09:00:00 -0700",
             "snippet": "Your flight home on Sep 1 is confirmed. Boarding pass attached."}]

    def search(self, around: date, window_days: int = 7) -> list[dict]:
        return self.canned


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "setup":
        token_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "..",
                                                                         ".gmail_token.json")
        get_service(token_path)
        print(f"authorized; token saved to {token_path}")
    elif len(sys.argv) >= 4 and sys.argv[1] == "search":
        svc = get_service(sys.argv[2])
        for r in search_travel_emails(svc, date.fromisoformat(sys.argv[3])):
            print(r)
    else:
        print(__doc__)
