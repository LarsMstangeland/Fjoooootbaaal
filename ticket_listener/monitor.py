from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from html import unescape
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
from ticket_listener.subscribers import Subscriber, SubscriberStore

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
    purchase_link_regex: re.Pattern[str] | None


@dataclass(frozen=True)
class TargetCheck:
    availability: Availability
    purchase_url: str | None = None


class TicketMonitor:
    def __init__(self, config: Config, should_stop: Callable[[], bool] | None = None) -> None:
        self.config = config
        self.should_stop = should_stop or (lambda: False)
        self.targets = [self._compile_target(target) for target in config.enabled_targets]
        self.subscribers = SubscriberStore(config.resolve_path(config.service.subscribers_path))
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
            check = self._check_target(target)
        except Exception as error:
            logger.warning("target check failed for %s: %s", target.config.name, error)
            return

        if check.availability is Availability.AVAILABLE:
            should_notify = (
                not self.config.actions.notify_once_per_target
                or target.config.name not in self.already_notified
            )
            self.already_notified.add(target.config.name)

            if should_notify:
                self._handle_available(target.config, check.purchase_url)
            else:
                logger.debug("%s still available; notification already sent", target.config.name)
        elif check.availability is Availability.SOLD_OUT:
            logger.info("%s: sold out or not open yet", target.config.name)
        else:
            logger.info("%s: availability unknown", target.config.name)

    def _check_target(self, target: CompiledTarget) -> TargetCheck:
        body = self._fetch(target.config.url)
        normalized_body = unescape(body)
        purchase_url = self._extract_purchase_url(target, normalized_body)

        if target.sold_out_regex and target.sold_out_regex.search(normalized_body):
            return TargetCheck(Availability.SOLD_OUT, purchase_url)

        if target.available_regex.search(normalized_body):
            return TargetCheck(Availability.AVAILABLE, purchase_url)

        return TargetCheck(Availability.UNKNOWN, purchase_url)

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

    def _handle_available(self, target: TargetConfig, purchase_url: str | None) -> None:
        open_url = purchase_url or target.open_url or target.url
        message = f"Tickets may be available for {target.name}: {open_url}"
        logger.warning(message)

        send_webhook(self.config.actions.webhook_url, message, self.config.app.request_timeout_secs)
        self._notify_subscribers(target, purchase_url)

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
            purchase_link_regex=re.compile(target.purchase_link_regex, flags)
            if target.purchase_link_regex
            else None,
        )

    def _notify_subscribers(self, target: TargetConfig, purchase_url: str | None = None) -> None:
        subscribers = self.subscribers.list(target.name)
        if not subscribers:
            logger.warning("no phone subscribers registered for %s", target.name)
            return

        verified_purchase_url = self._verified_purchase_url(target, purchase_url)
        for subscriber in subscribers:
            form_link = self._build_purchase_form_link(target, subscriber, verified_purchase_url)
            message = f"{target.name} may be open. Continue here: {form_link}"
            send_sms_webhook(
                self.config.sms.webhook_url,
                subscriber.phone,
                message,
                self.config.app.request_timeout_secs,
                self.config.sms.dry_run,
            )

    def _build_purchase_form_link(
        self, target: TargetConfig, subscriber: Subscriber, purchase_url: str | None = None
    ) -> str:
        base_url = (
            purchase_url
            or target.purchase_form_url
            or self.config.service.purchase_form_url
            or target.open_url
            or target.url
        )
        query = {
            "phone": subscriber.phone,
            "target": target.name,
            "ticket_url": target.open_url or target.url,
        }
        if subscriber.name:
            query["name"] = subscriber.name
        if target.prefill:
            query.update(target.prefill)

        separator = "&" if urllib.parse.urlparse(base_url).query else "?"
        return f"{base_url}{separator}{urllib.parse.urlencode(query)}"

    @staticmethod
    def _extract_purchase_url(target: CompiledTarget, body: str) -> str | None:
        if target.purchase_link_regex:
            match = target.purchase_link_regex.search(body)
            if match:
                return TicketMonitor._clean_url(match.group(1) if match.groups() else match.group(0))

        match = re.search(r"https://fanparks\.fanparks\.com/booking/[^\"'<>\s]+", body)
        if match:
            return TicketMonitor._clean_url(match.group(0))

        return None

    def _verified_purchase_url(self, target: TargetConfig, purchase_url: str | None) -> str | None:
        if not self.config.service.verify_links:
            return purchase_url

        if purchase_url and self._url_is_alive(purchase_url):
            return purchase_url

        if purchase_url:
            logger.warning("purchase link failed health check: %s", purchase_url)

        fallback_url = target.purchase_form_url or self.config.service.purchase_form_url
        if fallback_url and self._url_is_alive(fallback_url):
            logger.warning("using fallback form link: %s", fallback_url)
            return fallback_url

        if fallback_url:
            logger.warning("fallback form link failed health check: %s", fallback_url)

        open_url = target.open_url or target.url
        if self._url_is_alive(open_url):
            logger.warning("using event page as fallback link: %s", open_url)
            return open_url

        logger.error("all candidate links failed health check for %s", target.name)
        return None

    def _url_is_alive(self, url: str) -> bool:
        for method in ("HEAD", "GET"):
            request = urllib.request.Request(
                url,
                headers={"User-Agent": self.config.app.user_agent},
                method=method,
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self.config.app.request_timeout_secs
                ) as response:
                    return 200 <= response.status < 400
            except urllib.error.HTTPError as error:
                if method == "HEAD" and error.code in {403, 405, 501}:
                    continue
                return 200 <= error.code < 400
            except urllib.error.URLError:
                if method == "HEAD":
                    continue
                return False

        return False

    @staticmethod
    def _clean_url(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        cleaned_query = [
            (key, value)
            for key, value in query
            if key != "_gl" and not key.lower().startswith("utm_")
        ]
        return urllib.parse.urlunparse(
            parsed._replace(query=urllib.parse.urlencode(cleaned_query))
        )
