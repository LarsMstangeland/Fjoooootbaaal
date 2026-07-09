from __future__ import annotations

from urllib import request
import json
import logging

logger = logging.getLogger(__name__)


def send_webhook(webhook_url: str | None, message: str, timeout_secs: int) -> None:
    if not webhook_url:
        return

    payload = json.dumps({"content": message}).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_secs) as response:
            if response.status >= 400:
                logger.warning("webhook returned HTTP %s", response.status)
    except Exception as error:
        logger.warning("failed to send webhook: %s", error)


def send_sms_webhook(
    webhook_url: str | None,
    phone: str,
    message: str,
    timeout_secs: int,
    dry_run: bool,
) -> None:
    if dry_run or not webhook_url:
        logger.warning("SMS dry-run to %s: %s", phone, message)
        return

    payload = json.dumps({"to": phone, "message": message}).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_secs) as response:
            if response.status >= 400:
                logger.warning("SMS webhook returned HTTP %s for %s", response.status, phone)
    except Exception as error:
        logger.warning("failed to send SMS webhook to %s: %s", phone, error)
