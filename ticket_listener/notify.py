from __future__ import annotations

from urllib import request
from urllib import parse
from dataclasses import dataclass
import base64
import json
import logging
import os

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmsSettings:
    provider: str
    webhook_url: str | None
    twilio_account_sid_env: str
    twilio_auth_token_env: str
    twilio_from_env: str
    dry_run: bool


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


def send_sms(
    settings: SmsSettings,
    phone: str,
    message: str,
    timeout_secs: int,
) -> None:
    if settings.dry_run:
        logger.warning("SMS dry-run to %s: %s", phone, message)
        return

    if settings.provider == "twilio":
        _send_twilio_sms(settings, phone, message, timeout_secs)
        return

    _send_sms_webhook(settings.webhook_url, phone, message, timeout_secs)


def _send_sms_webhook(
    webhook_url: str | None,
    phone: str,
    message: str,
    timeout_secs: int,
) -> None:
    if not webhook_url:
        logger.warning("SMS webhook is missing; cannot send to %s", phone)
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


def _send_twilio_sms(
    settings: SmsSettings,
    phone: str,
    message: str,
    timeout_secs: int,
) -> None:
    account_sid = os.environ.get(settings.twilio_account_sid_env)
    auth_token = os.environ.get(settings.twilio_auth_token_env)
    from_number = os.environ.get(settings.twilio_from_env)

    missing = [
        name
        for name, value in [
            (settings.twilio_account_sid_env, account_sid),
            (settings.twilio_auth_token_env, auth_token),
            (settings.twilio_from_env, from_number),
        ]
        if not value
    ]
    if missing:
        logger.warning("Twilio env vars missing; cannot send SMS: %s", ", ".join(missing))
        return

    payload = parse.urlencode(
        {
            "From": from_number,
            "To": phone,
            "Body": message,
        }
    ).encode("utf-8")
    auth = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    req = request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
        data=payload,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_secs) as response:
            if 200 <= response.status < 300:
                logger.warning("SMS sent via Twilio to %s", phone)
            else:
                logger.warning("Twilio returned HTTP %s for %s", response.status, phone)
    except Exception as error:
        logger.warning("failed to send Twilio SMS to %s: %s", phone, error)
