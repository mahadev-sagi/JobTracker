"""
AWS Lambda handler for Gmail Pub/Sub push notifications.

This function is invoked by API Gateway when Google Cloud Pub/Sub delivers
a push notification indicating new email activity. It decodes the Pub/Sub
message, extracts the Gmail history ID and email address, then forwards
the notification to the JobTracker backend webhook endpoint for processing.

Architecture:
    Gmail -> Google Pub/Sub -> API Gateway -> This Lambda -> Backend API

Environment Variables:
    BACKEND_API_URL: Base URL of the JobTracker backend (e.g. https://api.jobtracker.example.com)
    API_SECRET_KEY:  Shared secret for authenticating with the backend webhook endpoint
    LOG_LEVEL:       Logging verbosity (default: INFO)
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any
from urllib import request, error

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_API_URL: str = os.environ.get("BACKEND_API_URL", "http://localhost:8000")
API_SECRET_KEY: str = os.environ.get("API_SECRET_KEY", "")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

logger = logging.getLogger("email_webhook")
logger.setLevel(LOG_LEVEL)

if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(asctime)s %(name)s — %(message)s")
    )
    logger.addHandler(_handler)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

APIGatewayEvent = dict[str, Any]
LambdaContext = Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_pubsub_message(body: dict[str, Any]) -> dict[str, Any]:
    """Decode a Google Cloud Pub/Sub push notification payload.

    The push notification body has the shape::

        {
            "message": {
                "data": "<base64-encoded JSON>",
                "messageId": "...",
                "publishTime": "..."
            },
            "subscription": "projects/.../subscriptions/..."
        }

    The *data* field, once base64-decoded, contains::

        {
            "emailAddress": "user@example.com",
            "historyId": "12345"
        }

    Returns:
        Decoded message data as a dict.

    Raises:
        ValueError: If the payload structure is unexpected or data cannot be decoded.
    """
    message = body.get("message")
    if not message:
        raise ValueError("Missing 'message' key in Pub/Sub payload")

    raw_data: str | None = message.get("data")
    if not raw_data:
        raise ValueError("Missing 'data' key in Pub/Sub message")

    try:
        decoded_bytes = base64.b64decode(raw_data)
        decoded_json: dict[str, Any] = json.loads(decoded_bytes)
    except (base64.binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to decode Pub/Sub message data: {exc}") from exc

    logger.info(
        "Decoded Pub/Sub message — email=%s historyId=%s messageId=%s",
        decoded_json.get("emailAddress", "unknown"),
        decoded_json.get("historyId", "unknown"),
        message.get("messageId", "unknown"),
    )
    return decoded_json


def _forward_to_backend(payload: dict[str, Any]) -> dict[str, Any]:
    """POST the decoded notification to the backend webhook endpoint.

    Args:
        payload: Decoded Pub/Sub message data containing emailAddress and historyId.

    Returns:
        Response body from the backend as a dict.

    Raises:
        RuntimeError: If the backend returns a non-2xx status code.
    """
    url = f"{BACKEND_API_URL.rstrip('/')}/api/webhooks/gmail"
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if API_SECRET_KEY:
        headers["X-Webhook-Secret"] = API_SECRET_KEY

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method="POST")

    logger.info("Forwarding notification to %s", url)

    try:
        with request.urlopen(req, timeout=30) as resp:
            response_body = resp.read().decode("utf-8")
            logger.info("Backend responded with status %d", resp.status)
            return json.loads(response_body) if response_body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Backend returned HTTP {exc.code}: {body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Failed to reach backend at {url}: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def handler(event: APIGatewayEvent, context: LambdaContext) -> dict[str, Any]:
    """AWS Lambda handler for Gmail Pub/Sub push notifications.

    Args:
        event:   API Gateway proxy integration event.
        context: Lambda runtime context (request ID, remaining time, etc.).

    Returns:
        API Gateway proxy response with status 200 on success, or an
        appropriate error status code on failure.
    """
    request_id = getattr(context, "aws_request_id", "local")
    logger.info("Invoked — requestId=%s", request_id)
    logger.debug("Raw event: %s", json.dumps(event, default=str))

    try:
        # --- Parse the incoming request body ---
        body_str: str = event.get("body", "") or ""
        if event.get("isBase64Encoded"):
            body_str = base64.b64decode(body_str).decode("utf-8")

        if not body_str:
            logger.warning("Received empty body — returning 400")
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Empty request body"}),
            }

        body: dict[str, Any] = json.loads(body_str)

        # --- Decode the Pub/Sub message ---
        decoded = _decode_pubsub_message(body)

        # --- Forward to backend ---
        result = _forward_to_backend(decoded)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "ok",
                "emailAddress": decoded.get("emailAddress"),
                "historyId": decoded.get("historyId"),
                "backendResponse": result,
            }),
        }

    except ValueError as exc:
        logger.error("Bad request: %s", exc)
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc)}),
        }

    except RuntimeError as exc:
        logger.error("Backend communication error: %s", exc)
        return {
            "statusCode": 502,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"Backend error: {exc}"}),
        }

    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error processing webhook")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"Internal error: {exc}"}),
        }
