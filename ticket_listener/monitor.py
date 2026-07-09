from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from html import unescape
from pathlib import Path
from typing import Callable
import logging
import re
import time
import urllib.error
import urllib.request
import urllib.parse
import webbrowser

from ticket_listener.config import Config, TargetConfig
from ticket_listener.notify import send_sms_webhook, send_webhook
from ticket_listener.subscribers import SubscriberStore

logger = logging.getLogger(__name__)


class Availability(Enum):
    AVAILABLE = "available"
    SOLD_OUT = "sold_out"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CompiledTarget:
    config: TargetConfig
    available_regex: re.Pattern[str]
    sold_out_regex: re.Pattern[str] | None


class TicketMonitor:
    def __init__(self, config: Config, should_stop: Callable[[], bool] | None = None) -> None:
        self.config = config
        self.should_stop = should_stop or (lambda: False)
        self.targets = [self._compile_target(target) for target in config.enabled_targets]
        self.subscribers = SubscriberStore(Path(config.service.subscribers_path))
        self.already_notified: set[str] = set()

    def run(self) -> None:
        logger.info("ticket listener started with %s target(s)", len(self.targets))

        while not self.should_stop():
            started = time.monotonic()
            for target in self.targets:
                if self.should_stop():
                    break
                self._check_and_handle(target)

            elapsed = time.monotonic() - started
            sleep_for = max(1.0, self.config.app.interval_secs - elapsed)
            self._sleep_until_next_tick(sleep_for)

        logger.info("ticket listener stopped")

    def _check_and_handle(self, target: CompiledTarget) -> None:
        try:
            availability = self._check_target(target)
        except Exception as error:
            logger.warning("target check failed for %s: %s", target.config.name, error)
            return

        if availability is Availability.AVAILABLE:
            should_notify = (
                not self.config.actions.notify_once_per_target
                or target.config.name not in self.already_notified
            )
            self.already_notified.add(target.config.name)

            if should_notify:
                self._handle_available(target.config)
            else:
                logger.debug("%s still available; notification already sent", target.config.name)
        elif availability is Availability.SOLD_OUT:
            logger.info("%s: sold out or not open yet", target.config.name)
        else:
            logger.info("%s: availability unknown", target.config.name)

    def _check_target(self, target: CompiledTarget) -> Availability:
        body = self._fetch(target.config.url)
        normalized_body = unescape(body)

        if target.sold_out_regex and target.sold_out_regex.search(normalized_body):
            return Availability.SOLD_OUT

        if target.available_regex.search(normalized_body):
            return Availability.AVAILABLE

        return Availability.UNKNOWN

    def _fetch(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.config.app.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=self.config.app.request_timeout_secs
            ) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"HTTP {error.code} from {url}") from error

    def _handle_available(self, target: TargetConfig) -> None:
        open_url = target.open_url or target.url
        message = f"Tickets may be available for {target.name}: {open_url}"
        logger.warning(message)

        send_webhook(self.config.actions.webhook_url, message, self.config.app.request_timeout_secs)
        self._notify_subscribers(target)

        if self.config.actions.open_browser:
            webbrowser.open(open_url)

    def _sleep_until_next_tick(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self.should_stop() and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))

    @staticmethod
    def _compile_target(target: TargetConfig) -> CompiledTarget:
        flags = re.IGNORECASE | re.MULTILINE
        return CompiledTarget(
            config=target,
            available_regex=re.compile(target.available_regex, flags),
            sold_out_regex=re.compile(target.sold_out_regex, flags)
            if target.sold_out_regex
            else None,
        )

    def _notify_subscribers(self, target: TargetConfig) -> None:
        subscribers = self.subscribers.list(target.name)
        if not subscribers:
            logger.warning("no phone subscribers registered for %s", target.name)
            return

        for subscriber in subscribers:
            form_link = self._build_purchase_form_link(target, subscriber.phone)
            message = f"{target.name} may be open. Continue here: {form_link}"
            send_sms_webhook(
                self.config.sms.webhook_url,
                subscriber.phone,
                message,
                self.config.app.request_timeout_secs,
                self.config.sms.dry_run,
            )

    def _build_purchase_form_link(self, target: TargetConfig, phone: str) -> str:
        base_url = (
            target.purchase_form_url
            or self.config.service.purchase_form_url
            or target.open_url
            or target.url
        )
        query = {
            "phone": phone,
            "target": target.name,
            "ticket_url": target.open_url or target.url,
        }
        if target.prefill:
            query.update(target.prefill)

        separator = "&" if urllib.parse.urlparse(base_url).query else "?"
        return f"{base_url}{separator}{urllib.parse.urlencode(query)}"
