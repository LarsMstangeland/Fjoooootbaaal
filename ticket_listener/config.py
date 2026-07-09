from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import tomllib
import re


@dataclass(frozen=True)
class AppConfig:
    interval_secs: int = 15
    request_timeout_secs: int = 10
    user_agent: str = "ticket-listener/0.1 (+personal availability monitor)"


@dataclass(frozen=True)
class ActionConfig:
    open_browser: bool = True
    notify_once_per_target: bool = True
    webhook_url: str | None = None


@dataclass(frozen=True)
class ServiceConfig:
    subscribers_path: str = "subscribers.json"
    purchase_form_url: str | None = None
    verify_links: bool = True


@dataclass(frozen=True)
class SmsConfig:
    provider: str = "webhook"
    webhook_url: str | None = None
    twilio_account_sid_env: str = "TWILIO_ACCOUNT_SID"
    twilio_auth_token_env: str = "TWILIO_AUTH_TOKEN"
    twilio_from_env: str = "TWILIO_FROM"
    dry_run: bool = True


@dataclass(frozen=True)
class TargetConfig:
    name: str
    url: str
    available_regex: str
    enabled: bool = True
    sold_out_regex: str | None = None
    open_url: str | None = None
    purchase_form_url: str | None = None
    purchase_link_regex: str | None = None
    prefill: dict[str, str] | None = None


@dataclass(frozen=True)
class Config:
    app: AppConfig
    actions: ActionConfig
    service: ServiceConfig
    sms: SmsConfig
    targets: list[TargetConfig]
    config_dir: Path

    @property
    def enabled_targets(self) -> list[TargetConfig]:
        return [target for target in self.targets if target.enabled]

    def resolve_path(self, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.config_dir / candidate


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.example.toml to config.toml first."
        )

    with path.open("rb") as file:
        raw = tomllib.load(file)

    app = _load_app(raw.get("app", {}))
    actions = _load_actions(raw.get("actions", {}))
    service = _load_service(raw.get("service", {}))
    sms = _load_sms(raw.get("sms", {}))
    targets = [_load_target(item) for item in raw.get("targets", [])]

    config = Config(
        app=app,
        actions=actions,
        service=service,
        sms=sms,
        targets=targets,
        config_dir=path.resolve().parent,
    )
    _validate_config(config)
    if not config.enabled_targets:
        raise ValueError("No enabled targets configured.")

    return config


def _load_app(raw: dict[str, Any]) -> AppConfig:
    return AppConfig(
        interval_secs=int(raw.get("interval_secs", 15)),
        request_timeout_secs=int(raw.get("request_timeout_secs", 10)),
        user_agent=str(
            raw.get("user_agent", "ticket-listener/0.1 (+personal availability monitor)")
        ),
    )


def _load_actions(raw: dict[str, Any]) -> ActionConfig:
    webhook_url = raw.get("webhook_url")
    return ActionConfig(
        open_browser=bool(raw.get("open_browser", True)),
        notify_once_per_target=bool(raw.get("notify_once_per_target", True)),
        webhook_url=str(webhook_url) if webhook_url else None,
    )


def _load_service(raw: dict[str, Any]) -> ServiceConfig:
    purchase_form_url = raw.get("purchase_form_url")
    return ServiceConfig(
        subscribers_path=str(raw.get("subscribers_path", "subscribers.json")),
        purchase_form_url=str(purchase_form_url) if purchase_form_url else None,
        verify_links=bool(raw.get("verify_links", True)),
    )


def _load_sms(raw: dict[str, Any]) -> SmsConfig:
    webhook_url = raw.get("webhook_url")
    return SmsConfig(
        provider=str(raw.get("provider", "webhook")),
        webhook_url=str(webhook_url) if webhook_url else None,
        twilio_account_sid_env=str(raw.get("twilio_account_sid_env", "TWILIO_ACCOUNT_SID")),
        twilio_auth_token_env=str(raw.get("twilio_auth_token_env", "TWILIO_AUTH_TOKEN")),
        twilio_from_env=str(raw.get("twilio_from_env", "TWILIO_FROM")),
        dry_run=bool(raw.get("dry_run", True)),
    )


def _load_target(raw: dict[str, Any]) -> TargetConfig:
    required = ["name", "url", "available_regex"]
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"Target is missing required keys: {', '.join(missing)}")

    sold_out_regex = raw.get("sold_out_regex")
    open_url = raw.get("open_url")
    purchase_form_url = raw.get("purchase_form_url")
    purchase_link_regex = raw.get("purchase_link_regex")
    prefill = raw.get("prefill", {})
    return TargetConfig(
        name=str(raw["name"]),
        url=str(raw["url"]),
        available_regex=str(raw["available_regex"]),
        enabled=bool(raw.get("enabled", True)),
        sold_out_regex=str(sold_out_regex) if sold_out_regex else None,
        open_url=str(open_url) if open_url else None,
        purchase_form_url=str(purchase_form_url) if purchase_form_url else None,
        purchase_link_regex=str(purchase_link_regex) if purchase_link_regex else None,
        prefill={str(key): str(value) for key, value in prefill.items()} if prefill else None,
    )


def _validate_config(config: Config) -> None:
    if config.app.interval_secs < 5:
        raise ValueError("app.interval_secs must be at least 5 seconds")
    if config.app.request_timeout_secs < 1:
        raise ValueError("app.request_timeout_secs must be at least 1 second")
    if config.sms.provider not in {"webhook", "twilio"}:
        raise ValueError("sms.provider must be either 'webhook' or 'twilio'")
    if not config.sms.dry_run and config.sms.provider == "webhook" and not config.sms.webhook_url:
        raise ValueError("sms.webhook_url is required when sms.provider is webhook")

    urls = [config.service.purchase_form_url, config.sms.webhook_url, config.actions.webhook_url]
    for target in config.targets:
        urls.extend([target.url, target.open_url, target.purchase_form_url])
        if target.purchase_link_regex:
            try:
                re.compile(target.purchase_link_regex)
            except re.error as error:
                raise ValueError(f"Invalid purchase_link_regex for {target.name}: {error}") from error

    for url in [item for item in urls if item]:
        _validate_http_url(url)


def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")
