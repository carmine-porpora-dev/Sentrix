import threading

import pytest

from app.api.ratelimit import RateLimiter, try_acquire_all
from app.models.api_config import RateRule
from tests.conftest import FakeClock


def limiter(clock: FakeClock, limit: int = 3, window_s: int = 60) -> RateLimiter:
    clock.now = 1000.0  # un valore esatto in binario: i confini al secondo non ballano
    return RateLimiter(RateRule(limit=limit, window_s=window_s), clock)


def test_passano_i_primi_poi_si_attende(clock: FakeClock) -> None:
    rl = limiter(clock)
    assert [rl.try_acquire("a") for _ in range(3)] == [0, 0, 0]
    assert rl.try_acquire("a") == 60  # il più vecchio è appena entrato: 60 s intere


def test_l_attesa_scende_con_il_tempo_e_si_arrotonda_per_eccesso(clock: FakeClock) -> None:
    rl = limiter(clock)
    for _ in range(3):
        rl.try_acquire("a")
    clock.advance(10)
    assert rl.try_acquire("a") == 50
    clock.advance(49.5)  # mancano 0,5 s: si dice 1, mai 0 (0 vorrebbe dire «passa»)
    assert rl.try_acquire("a") == 1


def test_finestra_scorrevole_al_secondo_esatto(clock: FakeClock) -> None:
    rl = limiter(clock)
    rl.try_acquire("a")  # t = 0
    clock.advance(30)
    rl.try_acquire("a")  # t = 30
    rl.try_acquire("a")  # t = 30
    assert rl.try_acquire("a") == 30  # pieno: il primo esce a t = 60
    clock.advance(29.5)
    assert rl.try_acquire("a") == 1  # t = 59,5: il primo è ancora dentro
    clock.advance(0.5)
    assert rl.try_acquire("a") == 0  # t = 60: il primo è fuori, ne entra uno
    assert rl.try_acquire("a") == 30  # ora dentro ci sono i due di t = 30 e quello di t = 60


def test_un_tentativo_negato_non_si_registra(clock: FakeClock) -> None:
    rl = limiter(clock)
    for _ in range(3):
        rl.try_acquire("a")
    for _ in range(50):
        assert rl.try_acquire("a") > 0  # insistere non allunga l'attesa
    clock.advance(60)
    assert rl.try_acquire("a") == 0


def test_chiavi_indipendenti(clock: FakeClock) -> None:
    rl = limiter(clock)
    for _ in range(3):
        rl.try_acquire("a")
    assert rl.try_acquire("a") > 0
    assert rl.try_acquire("b") == 0


def test_release_toglie_l_ultimo(clock: FakeClock) -> None:
    rl = limiter(clock, limit=1)
    assert rl.try_acquire("a") == 0
    assert rl.try_acquire("a") > 0
    rl.release("a")
    assert rl.try_acquire("a") == 0
    rl.release("sconosciuta")  # nessun errore


def test_gli_ip_che_non_tornano_piu_vengono_dimenticati(clock: FakeClock) -> None:
    rl = limiter(clock)
    for i in range(100):
        rl.try_acquire(f"ip-{i}")
    assert len(rl._hits) == 100
    clock.advance(60)  # tutti fuori dalla finestra
    rl.try_acquire("nuovo")  # basta un accesso qualunque a far partire la pulizia
    assert list(rl._hits) == ["nuovo"]


def test_la_pulizia_non_tocca_chi_e_ancora_dentro_la_finestra(clock: FakeClock) -> None:
    rl = limiter(clock)
    rl.try_acquire("vecchio")
    clock.advance(30)
    rl.try_acquire("recente")
    clock.advance(30)  # t = 60: «vecchio» scade, «recente» ha ancora 30 s
    rl.try_acquire("altro")
    assert set(rl._hits) == {"recente", "altro"}


def test_la_pulizia_costa_una_scansione_per_finestra(clock: FakeClock) -> None:
    rl = limiter(clock)
    rl.try_acquire("a")
    clock.advance(59)
    rl.try_acquire("b")
    assert rl._last_sweep == 1000.0  # troppo presto per ripulire
    clock.advance(1)
    rl.try_acquire("c")
    assert rl._last_sweep == 1060.0


def test_nessuna_deque_vuota_se_un_altro_limitatore_nega(clock: FakeClock) -> None:
    per_session = limiter(clock, limit=3, window_s=60)  # t = 1000, ultima pulizia: 1000
    overall = RateLimiter(RateRule(limit=1, window_s=3600), clock)
    clock.advance(30)
    per_session.try_acquire("s")  # t = 1030
    overall.try_acquire("*")
    clock.advance(30)
    per_session.try_acquire("x")  # t = 1060: la pulizia gira ora (e «s» è ancora dentro)
    assert "s" in per_session._hits
    clock.advance(30)  # t = 1090: l'evento di «s» è scaduto, la prossima pulizia non è dovuta
    assert try_acquire_all([(per_session, "s"), (overall, "*")], clock) > 0  # il globale nega
    assert "s" not in per_session._hits  # esaminata e svuotata: non resta una deque vuota


def test_tutti_o_nessuno(clock: FakeClock) -> None:
    per_session = limiter(clock, limit=3)
    overall = limiter(clock, limit=1)
    pairs = [(per_session, "s"), (overall, "*")]
    assert try_acquire_all(pairs, clock) == 0
    assert try_acquire_all(pairs, clock) == 60  # il globale è pieno
    # …e il contatore della sessione non è salito: ha ancora due posti
    assert per_session.try_acquire("s") == 0
    assert per_session.try_acquire("s") == 0
    assert per_session.try_acquire("s") > 0


def test_attesa_massima_tra_i_limitatori_che_negano(clock: FakeClock) -> None:
    short = limiter(clock, limit=1, window_s=60)
    long = limiter(clock, limit=1, window_s=3600)
    pairs = [(short, "s"), (long, "*")]
    assert try_acquire_all(pairs, clock) == 0
    assert try_acquire_all(pairs, clock) == 3600


def test_stesso_limitatore_con_due_chiavi(clock: FakeClock) -> None:
    rl = limiter(clock, limit=1)
    assert try_acquire_all([(rl, "a"), (rl, "b")], clock) == 0  # nessun blocco su se stesso
    assert try_acquire_all([(rl, "a"), (rl, "c")], clock) == 60


def test_richieste_parallele_non_superano_il_limite(clock: FakeClock) -> None:
    rl = limiter(clock, limit=5)
    start = threading.Barrier(50)
    results: list[int] = []

    def attempt() -> None:
        start.wait()
        results.append(rl.try_acquire("ip"))

    threads = [threading.Thread(target=attempt) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(0) == 5 and len(results) == 50


def test_due_coppie_di_limitatori_in_parallelo_non_si_bloccano(clock: FakeClock) -> None:
    a, b = limiter(clock, limit=100), limiter(clock, limit=100)
    done: list[int] = []

    def forward() -> None:
        for _ in range(200):
            try_acquire_all([(a, "x"), (b, "y")], clock)
        done.append(1)

    def backward() -> None:
        for _ in range(200):
            try_acquire_all([(b, "y"), (a, "x")], clock)  # ordine inverso nella lista
        done.append(1)

    threads = [threading.Thread(target=f) for f in (forward, backward) * 2]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(done) == 4  # nessun deadlock


@pytest.mark.parametrize("limit", [1, 2, 7])
def test_il_limite_e_esatto(clock: FakeClock, limit: int) -> None:
    rl = limiter(clock, limit=limit)
    assert sum(rl.try_acquire("k") == 0 for _ in range(limit + 10)) == limit
