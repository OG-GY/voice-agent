"""Rate limits, with a fake clock so they are instant and exact."""

from collections.abc import Callable

from app.api.limits import (
    AdmitResult,
    ConnectionLimits,
    IpRegistry,
    TokenBucket,
    WindowCounter,
)
from app.config import Settings


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_allows_a_burst_then_refills() -> None:
    t = FakeTime()
    bucket = TokenBucket(rate_per_s=1.0, burst=3, time_fn=t)
    assert [bucket.allow() for _ in range(4)] == [True, True, True, False]
    t.now += 2
    assert [bucket.allow() for _ in range(3)] == [True, True, False]


def test_window_counter_forgets_old_events() -> None:
    t = FakeTime()
    counter = WindowCounter(60, t)
    counter.add(5)
    t.now += 30
    assert counter.add(2) == 7
    t.now += 31
    assert counter.total() == 2


def test_many_small_messages_hit_the_connection_limit(make_settings: Callable[..., Settings]) -> None:
    t = FakeTime()
    limits = ConnectionLimits(make_settings(messages_per_10s=5), t)
    assert [limits.allow_message() for _ in range(7)] == [True] * 5 + [False] * 2


def test_audio_is_limited_by_seconds_not_by_count(make_settings: Callable[..., Settings]) -> None:
    limits = ConnectionLimits(make_settings(audio_seconds_per_minute=60), FakeTime())
    assert limits.allow_audio(25) and limits.allow_audio(25)
    assert not limits.allow_audio(25)  # three clips of 25 s exceed 60 s in a minute
    assert limits.allow_audio(10)


def test_invalid_messages_eventually_close_the_connection(
    make_settings: Callable[..., Settings],
) -> None:
    limits = ConnectionLimits(make_settings(invalid_before_close=3), FakeTime())
    assert [limits.note_invalid() for _ in range(3)] == [False, False, True]


def test_one_ip_cannot_hold_too_many_calls(make_settings: Callable[..., Settings]) -> None:
    ips = IpRegistry(make_settings(max_calls_per_ip=2), FakeTime())
    assert ips.admit("1.2.3.4") is AdmitResult.OK
    assert ips.admit("1.2.3.4") is AdmitResult.OK
    assert ips.admit("1.2.3.4") is AdmitResult.TOO_MANY_FOR_IP
    assert ips.admit("5.6.7.8") is AdmitResult.OK  # other addresses are unaffected
    ips.release("1.2.3.4")
    assert ips.admit("1.2.3.4") is AdmitResult.OK


def test_new_connections_are_rate_limited_per_ip(make_settings: Callable[..., Settings]) -> None:
    t = FakeTime()
    ips = IpRegistry(make_settings(connect_burst=2, max_calls_per_ip=10), t)
    first, second = ips.admit("1.2.3.4"), ips.admit("1.2.3.4")
    ips.release("1.2.3.4")
    ips.release("1.2.3.4")
    assert (first, second) == (AdmitResult.OK, AdmitResult.OK)
    assert ips.admit("1.2.3.4") is AdmitResult.RATE_LIMITED


def test_an_abusive_ip_is_penalized_for_a_while(make_settings: Callable[..., Settings]) -> None:
    t = FakeTime()
    ips = IpRegistry(make_settings(ip_penalty_invalid=3, ip_penalty_seconds=60), t)
    for _ in range(3):
        ips.note_invalid("1.2.3.4")
    assert ips.admit("1.2.3.4") is AdmitResult.PENALIZED
    t.now += 61
    assert ips.admit("1.2.3.4") is AdmitResult.OK


def test_messages_from_many_connections_share_the_ip_budget(
    make_settings: Callable[..., Settings],
) -> None:
    ips = IpRegistry(make_settings(messages_per_10s=2, max_calls_per_ip=2), FakeTime())
    allowed = [ips.allow_message("1.2.3.4") for _ in range(6)]
    assert allowed == [True] * 4 + [False] * 2
