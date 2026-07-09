from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from ticket_listener.config import load_config
from ticket_listener.monitor import TicketMonitor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ticket-listener",
        description="Monitor ticket pages and notify when tickets appear available.",
    )
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to TOML config file. Defaults to config.toml.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console log level.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate the config file and exit without monitoring.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    stop_requested = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        config = load_config(Path(args.config))
        if args.check_config:
            logging.getLogger(__name__).info(
                "config OK: %s enabled target(s)", len(config.enabled_targets)
            )
            return 0

        monitor = TicketMonitor(config, should_stop=lambda: stop_requested)
        monitor.run()
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        logging.getLogger(__name__).exception("ticket listener stopped: %s", error)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
