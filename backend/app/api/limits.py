"""Rate limits: token buckets per connection and per IP, plus penalties for abusive clients."""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from app.config import Settings

TimeFn = Callable[[], float]
_MAX_TRACKED_IPS = 5000
_INVALID_WINDOW_S = 300.0
_MESSAGE_WINDOW_S = 10.0
_MINUTE_S = 60.0


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: float, time_fn: TimeFn = time.monotonic) -> None:
        self._rate = rate_per_s
        self._burst = burst
        self._time = time_fn
        self._tokens = burst
        self._last = time_fn()

    def allow(self, cost: float = 1.0) -> bool:
        now = self._time()
        self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False


class WindowCounter:
    """Sum of amounts recorded during the last `window_s` seconds."""

    def __init__(self, window_s: float, time_fn: TimeFn = time.monotonic) -> None:
        self._window = window_s
        self._time = time_fn
        self._events: deque[tuple[float, float]] = deque()

    def _prune(self) -> None:
        cutoff = self._time() - self._window
        while self._events and self._events[0][0] <= cutoff:
            self._events.popleft()

    def total(self) -> float:
        self._prune()
        return sum(amount for _, amount in self._events)

    def add(self, amount: float = 1.0) -> float:
        self._prune()
        self._events.append((self._time(), amount))
        return self.total()


class ConnectionLimits:
    """Limits for one WebSocket connection."""

    def __init__(self, settings: Settings, time_fn: TimeFn = time.monotonic) -> None:
        per_10s = settings.messages_per_10s
        self._messages = TokenBucket(per_10s / _MESSAGE_WINDOW_S, per_10s, time_fn)
        self._audio = WindowCounter(_MINUTE_S, time_fn)
        self._invalid = WindowCounter(_MINUTE_S, time_fn)
        self._audio_budget = settings.audio_seconds_per_minute
        self._invalid_limit = settings.invalid_before_close

    def allow_message(self) -> bool:
        return self._messages.allow()

    def allow_audio(self, seconds: float) -> bool:
        if self._audio.total() + seconds > self._audio_budget:
            return False
        self._audio.add(seconds)
        return True

    def note_invalid(self) -> bool:
        """Record an invalid message; True means the connection should be closed."""
        return self._invalid.add() >= self._invalid_limit


class AdmitResult(StrEnum):
    OK = "ok"
    PENALIZED = "penalized"
    RATE_LIMITED = "rate_limited"
    TOO_MANY_FOR_IP = "too_many_for_ip"


@dataclass
class _IpState:
    connects: TokenBucket
    messages: TokenBucket
    invalid: WindowCounter
    active: int = 0
    penalty_until: float = field(default=0.0)


class IpRegistry:
    """Per-IP limits: connection rate and count, aggregate message rate, penalty for abuse."""

    def __init__(self, settings: Settings, time_fn: TimeFn = time.monotonic) -> None:
        self._s = settings
        self._time = time_fn
        self._ips: dict[str, _IpState] = {}

    def _get(self, ip: str) -> _IpState:
        state = self._ips.get(ip)
        if state is None:
            if len(self._ips) >= _MAX_TRACKED_IPS:
                self._evict_idle()
            s = self._s
            burst = s.messages_per_10s * s.max_calls_per_ip
            state = _IpState(
                connects=TokenBucket(s.connects_per_minute_per_ip / _MINUTE_S, s.connect_burst, self._time),
                messages=TokenBucket(burst / _MESSAGE_WINDOW_S, burst, self._time),
                invalid=WindowCounter(_INVALID_WINDOW_S, self._time),
            )
            self._ips[ip] = state
        return state

    def _evict_idle(self) -> None:
        now = self._time()
        idle = [ip for ip, st in self._ips.items() if st.active == 0 and st.penalty_until <= now]
        for ip in idle[: max(1, len(idle) // 2)]:
            del self._ips[ip]

    def admit(self, ip: str) -> AdmitResult:
        state = self._get(ip)
        if self._time() < state.penalty_until:
            return AdmitResult.PENALIZED
        if state.active >= self._s.max_calls_per_ip:
            return AdmitResult.TOO_MANY_FOR_IP
        if not state.connects.allow():
            return AdmitResult.RATE_LIMITED
        state.active += 1
        return AdmitResult.OK

    def release(self, ip: str) -> None:
        state = self._ips.get(ip)
        if state is not None:
            state.active = max(0, state.active - 1)

    def allow_message(self, ip: str) -> bool:
        return self._get(ip).messages.allow()

    def note_invalid(self, ip: str) -> None:
        state = self._get(ip)
        if state.invalid.add() >= self._s.ip_penalty_invalid:
            state.penalty_until = self._time() + self._s.ip_penalty_seconds
