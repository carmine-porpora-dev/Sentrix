import base64
import hashlib
import hmac
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass

SESSION_COOKIE = "napoli_session"
_VERSION = "v1"


@dataclass(frozen=True)
class Session:
    sid: str
    expires_at: int  # secondi Unix


def _sign(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class SessionManager:
    def __init__(self, secret: str, lifetime_s: int, clock: Callable[[], float]) -> None:
        if not secret:
            raise ValueError("SESSION_SECRET vuoto: nessuna firma possibile")
        self._secret = secret
        self._lifetime_s = lifetime_s
        self._clock = clock
        self._revoked: dict[str, int] = {}  # sid -> scadenza (poi non serve più ricordarlo)
        self._lock = threading.Lock()

    @property
    def lifetime_s(self) -> int:
        return self._lifetime_s

    def issue(self) -> tuple[str, Session]:
        session = Session(
            sid=secrets.token_urlsafe(16), expires_at=int(self._clock()) + self._lifetime_s
        )
        payload = f"{_VERSION}.{session.sid}.{session.expires_at}"
        return f"{payload}.{_sign(self._secret, payload)}", session

    def verify(self, token: str | None) -> Session | None:
        """La sessione se il cookie è integro, non scaduto e non revocato; altrimenti None."""
        if not token or len(token) > 256 or not token.isascii():
            return None
        parts = token.split(".")
        if len(parts) != 4 or parts[0] != _VERSION or not parts[2].isdigit():
            return None
        version, sid, expires, signature = parts
        payload = f"{version}.{sid}.{expires}"
        if not hmac.compare_digest(signature, _sign(self._secret, payload)):
            return None
        session = Session(sid=sid, expires_at=int(expires))
        if session.expires_at <= self._clock():
            return None
        with self._lock:
            if session.sid in self._revoked:
                return None
        return session

    def revoke(self, session: Session) -> None:
        now = self._clock()
        with self._lock:
            self._revoked = {s: e for s, e in self._revoked.items() if e > now}
            self._revoked[session.sid] = session.expires_at
