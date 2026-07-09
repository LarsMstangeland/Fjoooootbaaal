from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import re


@dataclass(frozen=True)
class Subscriber:
    phone: str
    name: str | None = None
    target: str | None = None


class SubscriberStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self, target_name: str | None = None) -> list[Subscriber]:
        subscribers = self._read()
        if target_name is None:
            return subscribers
        return [
            subscriber
            for subscriber in subscribers
            if subscriber.target is None or subscriber.target == target_name
        ]

    def add(self, subscriber: Subscriber) -> None:
        normalized = Subscriber(
            phone=normalize_phone(subscriber.phone),
            name=subscriber.name,
            target=subscriber.target,
        )
        subscribers = [
            existing for existing in self._read() if existing.phone != normalized.phone
        ]
        subscribers.append(normalized)
        self._write(subscribers)

    def _read(self) -> list[Subscriber]:
        if not self.path.exists():
            return []

        with self.path.open("r", encoding="utf-8") as file:
            raw = json.load(file)

        return [
            Subscriber(
                phone=str(item["phone"]),
                name=str(item["name"]) if item.get("name") else None,
                target=str(item["target"]) if item.get("target") else None,
            )
            for item in raw
        ]

    def _write(self, subscribers: list[Subscriber]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump([asdict(subscriber) for subscriber in subscribers], file, indent=2)
            file.write("\n")


def normalize_phone(phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", phone.strip())
    if not cleaned:
        raise ValueError("phone number cannot be empty")
    if cleaned.count("+") > 1 or ("+" in cleaned and not cleaned.startswith("+")):
        raise ValueError("phone number can only contain a leading +")
    if len(cleaned.replace("+", "")) < 7:
        raise ValueError("phone number is too short")
    return cleaned
