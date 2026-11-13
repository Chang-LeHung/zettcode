"""The gateway's counters, in the text format Prometheus reads.

Everything here is in memory and starts again at zero with the process, which is how a counter is meant to behave: a
scraper sees a restart as a reset. Labels are only ever values the code chose (a route's name, a status class, a role),
never what a client sent, so a client cannot make the table grow by asking for strange paths.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

#: The upper edges, in seconds, of the request-time histogram.
BUCKETS = (0.005, 0.025, 0.1, 0.25, 1.0, 2.5, 10.0)


def _label(value: object) -> str:
    """Return a label value escaped for the exposition format."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Metrics:
    """Counters and one histogram, rendered by :meth:`render`."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started = clock()
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self._logins: dict[str, int] = defaultdict(int)
        self._seconds: dict[str, list[int]] = {}
        self._seconds_sum: dict[str, float] = defaultdict(float)
        self._sockets = 0
        self._sockets_opened = 0

    def request(self, route: str, method: str, status: int, seconds: float) -> None:
        """Count one answered request and how long it took."""
        with self._lock:
            self._requests[(route, method, f"{status // 100}xx")] += 1
            counts = self._seconds.setdefault(route, [0] * (len(BUCKETS) + 1))
            for index, edge in enumerate(BUCKETS):
                if seconds <= edge:
                    counts[index] += 1
            counts[-1] += 1  # +Inf is the total
            self._seconds_sum[route] += seconds

    def login(self, outcome: str) -> None:
        """Count a sign-in attempt: ``read``, ``write``, ``failed`` or ``locked``."""
        with self._lock:
            self._logins[outcome] += 1

    def socket_opened(self) -> None:
        with self._lock:
            self._sockets += 1
            self._sockets_opened += 1

    def socket_closed(self) -> None:
        with self._lock:
            self._sockets = max(0, self._sockets - 1)

    def render(self, gauges: dict[str, float] | None = None, info: dict[str, str] | None = None) -> str:
        """Return the exposition text; ``gauges`` are values read at scrape time, ``info`` becomes one labelled line."""
        out: list[str] = []

        def family(name: str, kind: str, help_text: str) -> None:
            out.extend((f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"))

        with self._lock:
            family("zettcode_gateway_info", "gauge", "The gateway's version.")
            labels = ",".join(f'{key}="{_label(value)}"' for key, value in sorted((info or {}).items()))
            out.append(f"zettcode_gateway_info{{{labels}}} 1")
            family("zettcode_gateway_uptime_seconds", "gauge", "Seconds since the gateway started.")
            out.append(f"zettcode_gateway_uptime_seconds {self._clock() - self._started:.3f}")
            family("zettcode_gateway_requests_total", "counter", "Answered API requests by route, method and status.")
            for (route, method, status), count in sorted(self._requests.items()):
                out.append(
                    f'zettcode_gateway_requests_total{{route="{_label(route)}",method="{method}",status="{status}"}} {count}'
                )
            family("zettcode_gateway_request_seconds", "histogram", "How long API requests took, by route.")
            for route, counts in sorted(self._seconds.items()):
                name = _label(route)
                for edge, count in zip(BUCKETS, counts, strict=False):  # counts has one more: the +Inf total
                    out.append(f'zettcode_gateway_request_seconds_bucket{{route="{name}",le="{edge}"}} {count}')
                out.append(f'zettcode_gateway_request_seconds_bucket{{route="{name}",le="+Inf"}} {counts[-1]}')
                out.append(f'zettcode_gateway_request_seconds_sum{{route="{name}"}} {self._seconds_sum[route]:.6f}')
                out.append(f'zettcode_gateway_request_seconds_count{{route="{name}"}} {counts[-1]}')
            family("zettcode_gateway_logins_total", "counter", "Sign-in attempts by outcome.")
            for outcome, count in sorted(self._logins.items()):
                out.append(f'zettcode_gateway_logins_total{{outcome="{outcome}"}} {count}')
            family("zettcode_gateway_event_sockets", "gauge", "Event sockets open now.")
            out.append(f"zettcode_gateway_event_sockets {self._sockets}")
            family("zettcode_gateway_event_sockets_opened_total", "counter", "Event sockets accepted since the start.")
            out.append(f"zettcode_gateway_event_sockets_opened_total {self._sockets_opened}")
        for name, value in sorted((gauges or {}).items()):
            family(f"zettcode_gateway_{name}", "gauge", name.replace("_", " ").capitalize() + ".")
            out.append(f"zettcode_gateway_{name} {value:g}")
        return "\n".join(out) + "\n"


def route_name(handler: Callable[..., Any]) -> str:
    """Return the label a handler's requests are counted under: its function name, which the code chose."""
    return getattr(handler, "__name__", "handler")
