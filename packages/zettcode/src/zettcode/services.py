"""``zettcode start|stop|restart [broker|gateway|all]``: the background processes as one set.

``zettcode broker`` and ``zettcode gateway`` each manage their own process and keep their own flags. These three words
are the short way to the same actions, and add ``all``, which is both in the order that works: the gateway is a client
of the broker, so it stops first and starts last.

* ``start all``: the broker, then the gateway (with the settings it last ran with, or the defaults).
* ``stop all``: the gateway, then the broker.
* ``restart all``: the gateway stops, the broker restarts (and the background agents on it with it, after the usual
  question unless ``-y``), and the gateway starts again with the settings it was running with, so a token or a port is
  not lost.

The target defaults to ``all``. A gateway's own flags (``--port``, ``--token``...) belong to ``zettcode gateway``.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from zettcode.broker import cli as broker_cli
from zettcode.broker.files import broker_dir
from zettcode.daemon.companions import DaemonCompanions
from zettcode.gateway import cli as gateway_cli
from zettcode.gateway import runfile
from zettcode.gateway.settings import Settings, default_directory

#: One thing to do to one process; it is told whether a restart may skip its question.
Step = Callable[[bool], int]

TARGETS = ("broker", "gateway", "all")


def build_parser(action: str) -> argparse.ArgumentParser:
    """Return the parser for one action: which process, and whether to skip the question a restart may ask."""
    parser = argparse.ArgumentParser(
        prog=f"zettcode {action}",
        description=f"{action.capitalize()} the session broker, the web gateway, or both (the default).",
    )
    parser.add_argument("target", nargs="?", choices=TARGETS, default="all", help="what to act on (default: all)")
    if action == "restart":
        parser.add_argument(
            "-y",
            "--yes",
            action="store_true",
            help="do not ask before stopping and starting again the background agents running on the broker",
        )
    return parser


def services_program(action: str, argv: list[str]) -> int:
    """Run ``action`` on the named process or on both; the exit status is the first failure's, else 0."""
    args = build_parser(action).parse_args(argv)
    assume_yes = bool(getattr(args, "yes", False))
    steps = plan(action, args.target)
    status = 0
    for step in steps:
        outcome = step(assume_yes)
        status = status or outcome
        if outcome and action == "start" and args.target == "all":
            # The gateway is a client of the broker: one on a broker that did not start would only fail too. A stop
            # carries on, so that a gateway that cannot be identified does not keep the broker running.
            break
    return status


def plan(action: str, target: str) -> list[Step]:
    """Return the steps, in order, that ``action`` on ``target`` takes; each is called with ``assume_yes``."""
    broker = {"start": _broker_start, "stop": _broker_stop, "restart": _broker_restart}[action]
    gateway = {"start": _gateway_start, "stop": _gateway_stop, "restart": _gateway_restart}[action]
    if target == "broker":
        return [broker]
    if target == "gateway":
        return [gateway]
    if action == "start":
        return [broker, gateway]
    if action == "stop":
        return [gateway, broker]
    return [_restart_all]


# -- the broker ---------------------------------------------------------------------------------------------------
def _broker_start(assume_yes: bool) -> int:
    return broker_cli.start(broker_dir())


def _broker_stop(assume_yes: bool) -> int:
    return broker_cli.stop(broker_dir())


def _broker_restart(assume_yes: bool) -> int:
    return broker_cli.restart(broker_dir(), DaemonCompanions(), assume_yes=assume_yes)


# -- the gateway --------------------------------------------------------------------------------------------------
def _recorded() -> Settings | None:
    """Return the settings the running gateway was started with, or ``None`` when no record says."""
    record = runfile.read(default_directory())
    return record.settings if record is not None else None


def _gateway_start(assume_yes: bool) -> int:
    return gateway_cli.start(gateway_cli.settings_from([], base=_recorded()))


def _gateway_stop(assume_yes: bool) -> int:
    return gateway_cli.stop(default_directory())


def _gateway_restart(assume_yes: bool) -> int:
    return gateway_cli.restart(gateway_cli.settings_from([], base=_recorded()))


def _restart_all(assume_yes: bool) -> int:
    """Restart both: the gateway steps aside, the broker restarts, and the gateway returns with what it had.

    The gateway's settings are read before it stops, because stopping removes the record they are kept in.
    """
    settings = gateway_cli.settings_from([], base=_recorded())
    status = gateway_cli.stop(default_directory(), quiet=True)
    if status:
        return status
    status = _broker_restart(assume_yes)
    # The gateway comes back either way: a broker that was left as it was (the person said no, or it would not stop)
    # still has a page worth serving, and a gateway left down by a refused restart would be a surprise.
    started = gateway_cli.start(settings)
    return status or started


__all__ = ["TARGETS", "build_parser", "plan", "services_program"]
