"""In-memory failed-login throttle for the review gateway.

Verbatim lift of the sovalius-dispatch gateway's LoginThrottle (itself a port
of the rack's N-6 hardening control) — kept in this package so the review
gateway stays an isolated trust domain. Lives on app.state (not a module
global) because it holds mutable runtime state and must be injectable /
resettable in tests.

Failures are counted per username *and* per client IP over a sliding window;
crossing ``max_failures`` inside ``window_sec`` locks that key out
(``lockout_sec`` for IP keys, ``user_lockout_sec`` for username keys). A
successful login clears the username's failure history but deliberately NOT
the IP's — an attacker rotating usernames from one address still locks out.

State is in-process only: the gateway is single-process, and losing the table
on restart is acceptable for this control. All methods are thread-safe.
``clock`` is injectable for tests.
"""

from __future__ import annotations

import threading
import time

DEFAULT_THROTTLE_MAX_FAILURES = 5
DEFAULT_THROTTLE_WINDOW_SEC = 60.0
DEFAULT_THROTTLE_LOCKOUT_SEC = 15 * 60.0
# Username lockouts are deliberately shorter than IP lockouts: usernames are
# guessable from the outside, so a hard long lockout would hand an
# unauthenticated attacker a cheap denial-of-service against known accounts.
DEFAULT_THROTTLE_USER_LOCKOUT_SEC = 5 * 60.0
# Hard ceiling on tracked keys — both username and IP key components are
# attacker-controlled, so the dicts must be bounded.
_THROTTLE_MAX_TRACKED_KEYS = 4096


class LoginThrottle:
    """In-memory failed-login throttle with lockout (see module docstring)."""

    def __init__(
        self,
        max_failures: int = DEFAULT_THROTTLE_MAX_FAILURES,
        window_sec: float = DEFAULT_THROTTLE_WINDOW_SEC,
        lockout_sec: float = DEFAULT_THROTTLE_LOCKOUT_SEC,
        user_lockout_sec: float = DEFAULT_THROTTLE_USER_LOCKOUT_SEC,
        clock=time.monotonic,
    ) -> None:
        self.max_failures = int(max_failures)
        self.window_sec = float(window_sec)
        self.lockout_sec = float(lockout_sec)
        self.user_lockout_sec = float(user_lockout_sec)
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    @staticmethod
    def _keys(username: str, ip: str) -> tuple:
        keys = []
        if username:
            keys.append(f"u:{username.lower()}")
        if ip:
            keys.append(f"ip:{ip}")
        return tuple(keys)

    def retry_after(self, username: str, ip: str) -> float:
        """Seconds until this user/IP may try again. 0 = not locked."""
        now = self._clock()
        remaining = 0.0
        with self._lock:
            for key in self._keys(username, ip):
                until = self._locked_until.get(key, 0.0)
                if until > now:
                    remaining = max(remaining, until - now)
        return remaining

    def record_failure(self, username: str, ip: str) -> bool:
        """Register a failed attempt. Returns True if a lockout started."""
        now = self._clock()
        locked = False
        with self._lock:
            for key in self._keys(username, ip):
                window = [
                    t for t in self._failures.get(key, [])
                    if now - t < self.window_sec
                ]
                window.append(now)
                if len(window) >= self.max_failures:
                    duration = (
                        self.user_lockout_sec
                        if key.startswith("u:")
                        else self.lockout_sec
                    )
                    self._locked_until[key] = now + duration
                    self._failures.pop(key, None)
                    locked = True
                else:
                    self._failures[key] = window
            self._prune_locked(now)
        return locked

    def _prune_locked(self, now: float) -> None:
        """Bound both dicts — every key component is attacker-controlled.

        Stale entries (expired lockouts, failure windows with no recent
        activity) are dropped once either dict crosses the cap; if live entries
        alone still exceed it, the oldest failure windows are evicted (an
        attacker spraying that many distinct keys defeats per-key tracking
        anyway).
        """
        if len(self._locked_until) > _THROTTLE_MAX_TRACKED_KEYS:
            self._locked_until = {
                k: v for k, v in self._locked_until.items() if v > now
            }
        if len(self._failures) > _THROTTLE_MAX_TRACKED_KEYS:
            self._failures = {
                k: w for k, w in self._failures.items()
                if w and now - w[-1] < self.window_sec
            }
            overflow = len(self._failures) - _THROTTLE_MAX_TRACKED_KEYS
            if overflow > 0:
                for k in sorted(
                    self._failures, key=lambda k: self._failures[k][-1]
                )[:overflow]:
                    self._failures.pop(k, None)

    def record_success(self, username: str, ip: str) -> None:
        """Clear the username's failure state after a successful login.

        Deliberately keeps the IP key — an attacker rotating usernames from one
        address still trips the per-IP lockout.
        """
        if not username:
            return
        key = f"u:{username.lower()}"
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)
