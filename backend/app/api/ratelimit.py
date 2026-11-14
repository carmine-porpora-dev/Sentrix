import math
import threading
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import ExitStack

from app.models.api_config import RateRule


class RateLimiter:
    def __init__(self, rule: RateRule, clock: Callable[[], float]) -> None:
        self._rule = rule
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._last_sweep = clock()
        self.lock = threading.Lock()  # pubblico: try_acquire_all li prende in blocco

    def _sweep(self, now: float) -> None:
        """Dimentica le chiavi con tutti gli eventi fuori dalla finestra. Chi non torna più (un IP
        che ha sbagliato una volta) altrimenti resterebbe in memoria per sempre; la pulizia costa
        una scansione ogni finestra, non una a ogni richiesta."""
        if now - self._last_sweep < self._rule.window_s:
            return
        self._last_sweep = now
        cutoff = now - self._rule.window_s
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]

    def _wait(self, key: str, now: float) -> int:
        """Secondi da attendere perché `key` torni sotto il limite (0 = può procedere)."""
        hits = self._hits.get(key)
        if hits is None:
            return 0
        while hits and hits[0] <= now - self._rule.window_s:  # scaduti: fuori dalla finestra
            hits.popleft()
        if not hits:
            del self._hits[key]  # tutti scaduti: niente deque vuota lasciata in giro
            return 0
        if len(hits) < self._rule.limit:
            return 0
        return max(1, math.ceil(hits[0] + self._rule.window_s - now))

    def _record(self, key: str, now: float) -> None:
        self._hits.setdefault(key, deque()).append(now)

    def try_acquire(self, key: str) -> int:
        """0 = registrato; altrimenti i secondi da attendere (e non si registra nulla)."""
        return try_acquire_all([(self, key)], self._clock)

    def release(self, key: str) -> None:
        """Toglie l'evento registrato più di recente per `key` (es. un login poi riuscito)."""
        with self.lock:
            hits = self._hits.get(key)
            if hits:
                hits.pop()
                if not hits:
                    del self._hits[key]


def try_acquire_all(pairs: Sequence[tuple[RateLimiter, str]], clock: Callable[[], float]) -> int:
    """Registra un evento su TUTTI i limitatori o su nessuno. 0 = fatto; altrimenti i secondi da
    attendere (il più lungo tra quelli che hanno detto no) e nessun contatore cambia."""
    ordered = sorted({id(limiter): limiter for limiter, _ in pairs}.values(), key=id)
    with ExitStack() as stack:
        for limiter in ordered:  # ordine fisso: due richieste insieme non si bloccano a vicenda
            stack.enter_context(limiter.lock)
        now = clock()
        for limiter in ordered:
            limiter._sweep(now)
        wait = max((limiter._wait(key, now) for limiter, key in pairs), default=0)
        if wait == 0:
            for limiter, key in pairs:
                limiter._record(key, now)
        return wait
