import pytest

from app.api.session import SESSION_COOKIE, SessionManager, _sign
from tests.conftest import FakeClock

LIFETIME_S = 12 * 3600


@pytest.fixture
def manager(clock: FakeClock) -> SessionManager:
    return SessionManager("fake-secret", LIFETIME_S, clock)


def test_emissione_e_verifica(manager: SessionManager, clock: FakeClock) -> None:
    token, session = manager.issue()
    assert session.expires_at == int(clock.now) + LIFETIME_S
    verified = manager.verify(token)
    assert verified == session
    assert manager.lifetime_s == LIFETIME_S


def test_il_cookie_non_contiene_dati_personali(manager: SessionManager) -> None:
    token, session = manager.issue()
    version, sid, expires, signature = token.split(".")
    assert (version, sid, expires) == ("v1", session.sid, str(session.expires_at))
    assert signature  # firma presente
    assert SESSION_COOKIE == "napoli_session"


def test_gli_identificativi_sono_tutti_diversi(manager: SessionManager) -> None:
    sids = {manager.issue()[1].sid for _ in range(200)}
    assert len(sids) == 200


def test_scadenza_esatta(manager: SessionManager, clock: FakeClock) -> None:
    token, session = manager.issue()
    clock.now = session.expires_at - 1
    assert manager.verify(token) is not None
    clock.now = session.expires_at  # allo scadere non vale più
    assert manager.verify(token) is None
    clock.now = session.expires_at + 1
    assert manager.verify(token) is None


def test_altro_segreto_non_valida(manager: SessionManager, clock: FakeClock) -> None:
    token, _ = manager.issue()
    other = SessionManager("fake-altro-segreto", LIFETIME_S, clock)
    assert other.verify(token) is None


def test_ogni_parte_manomessa_invalida(manager: SessionManager) -> None:
    token, session = manager.issue()
    version, sid, expires, signature = token.split(".")
    other_last = "B" if signature[-1] == "A" else "A"  # un carattere DIVERSO, sempre
    tampered = [
        f"v2.{sid}.{expires}.{signature}",  # versione
        f"{version}.{sid}x.{expires}.{signature}",  # identificativo
        f"{version}.{sid}.{int(expires) + 3600}.{signature}",  # scadenza allungata
        f"{version}.{sid}.{expires}.{signature[:-1]}{other_last}",  # firma (ultimo carattere)
        f"{version}.{sid}.{expires}.{signature}A",  # firma più lunga
        f"{version}.{sid}.{expires}.",  # firma vuota
        f"{version}.{sid}.{expires}",  # senza firma
        f"{token}.extra",  # parte in più
    ]
    assert manager.verify(token) == session
    for bad in tampered:
        assert manager.verify(bad) is None, bad


def test_una_versione_sconosciuta_non_vale_nemmeno_se_la_firma_e_giusta(
    manager: SessionManager, clock: FakeClock
) -> None:
    expires = int(clock.now) + 100
    payload = f"v2.qualcuno.{expires}"
    assert manager.verify(f"{payload}.{_sign('fake-secret', payload)}") is None
    good = f"v1.qualcuno.{expires}"
    assert manager.verify(f"{good}.{_sign('fake-secret', good)}") is not None  # il resto è valido


@pytest.mark.parametrize(
    "garbage",
    [
        None,
        "",
        "garbage",
        "...",
        "v1...",
        "v1.a.b.c",
        "v1.a.-5.c",
        "v1.a.1e9.c",
        "v1.a.１２３.c",  # cifre non ASCII
        "è" * 10,
        "x" * 10_000,
    ],
)
def test_cookie_malformati_non_vengono_accettati_e_non_sollevano(
    manager: SessionManager, garbage: str | None
) -> None:
    assert manager.verify(garbage) is None


def test_revoca(manager: SessionManager) -> None:
    first, first_session = manager.issue()
    second, _ = manager.issue()
    manager.revoke(first_session)
    assert manager.verify(first) is None  # firma ancora giusta, ma revocata
    assert manager.verify(second) is not None  # le altre sessioni non si toccano


def test_la_revoca_si_dimentica_alla_scadenza(manager: SessionManager, clock: FakeClock) -> None:
    _, old = manager.issue()
    manager.revoke(old)
    clock.advance(LIFETIME_S + 1)
    _, newer = manager.issue()
    manager.revoke(newer)  # la scrittura ripulisce le revoche ormai inutili
    assert list(manager._revoked) == [newer.sid]


def test_segreto_vuoto_e_un_errore(clock: FakeClock) -> None:
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        SessionManager("", LIFETIME_S, clock)
