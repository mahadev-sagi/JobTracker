#!/usr/bin/env python3
"""
One-time Gmail OAuth bootstrap.

The server never runs an interactive consent flow: it is headless in Docker
and Lambda, where a browser cannot open. Instead you run this script once, on
a machine with a browser, to exchange your OAuth client credentials for a
long-lived ``token.json`` that the server then refreshes on its own.

Prerequisites
-------------
1. In Google Cloud Console, enable the Gmail API for your project.
2. Create an OAuth 2.0 Client ID of type **Desktop app**.
3. Download it as ``credentials.json``.
4. While the app is in "Testing", add your own address as a test user.

Usage
-----
    python backend/scripts/bootstrap_gmail_token.py \
        --credentials path/to/credentials.json \
        --output      backend/secrets/token.json

Then point the server at the result:

    GOOGLE_CREDENTIALS_JSON=/app/secrets/token.json

and mount the directory into the container (see docker-compose.yml).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:  # pragma: no cover - guidance path
    sys.exit(
        "google-auth-oauthlib is not installed.\n"
        "Run: pip install -r backend/requirements.txt"
    )

# Must match _SCOPES in src/email_pipeline/gmail_service.py, or the stored
# token will be rejected as insufficiently scoped at runtime.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--credentials",
        default="credentials.json",
        help="Path to the OAuth desktop-client credentials.json from GCP.",
    )
    parser.add_argument(
        "--output",
        default="backend/secrets/token.json",
        help="Where to write the authorised token.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Local port for the OAuth redirect listener (0 = pick one).",
    )
    args = parser.parse_args()

    if not os.path.exists(args.credentials):
        print(f"ERROR: no credentials file at '{args.credentials}'.", file=sys.stderr)
        print(
            "Download an OAuth 'Desktop app' client from the Google Cloud "
            "Console and pass it with --credentials.",
            file=sys.stderr,
        )
        return 1

    # Guard against the most common mistake: passing a service-account key,
    # which has no interactive flow and fails with an opaque error.
    with open(args.credentials) as fh:
        blob = json.load(fh)
    if blob.get("type") == "service_account":
        print(
            "ERROR: that is a service-account key, not an OAuth client.\n"
            "For a personal @gmail.com address you need a Desktop-app OAuth "
            "client. Service accounts only work with Google Workspace "
            "domain-wide delegation.",
            file=sys.stderr,
        )
        return 1

    print("Opening a browser for Google consent…")
    print("Sign in as the mailbox you want JobTracker to monitor.\n")

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials, SCOPES)
    creds = flow.run_local_server(port=args.port)

    if not creds.refresh_token:
        print(
            "\nWARNING: Google returned no refresh_token, so this token will "
            "stop working within the hour.\n"
            "Revoke the app at https://myaccount.google.com/permissions and "
            "run this script again to force a fresh consent prompt.",
            file=sys.stderr,
        )

    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w") as fh:
        fh.write(creds.to_json())
    # The token grants mailbox access; keep it owner-readable where supported.
    try:
        os.chmod(args.output, 0o600)
    except OSError:
        pass

    print(f"\nWrote {args.output}")
    print("\nNext steps:")
    print("  1. Set GOOGLE_CREDENTIALS_JSON to this path (in-container path).")
    print("  2. Mount the directory into the backend container.")
    print("  3. POST /api/webhooks/gmail/watch to start push notifications.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
