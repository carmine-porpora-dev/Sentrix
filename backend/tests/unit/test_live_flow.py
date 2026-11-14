import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.data.live_flow import (
    KEY_MISSING,
    LIVE_VIEW_REQUIRED,
    NO_DATA,
    LiveFlowService,
    build_live_flow,
    summarize,
)
from app.data.tomtom import TomTomClient, congestion_class
from app.main import create_app
from app.models.geo import GeoPoint
from app.models.live_config import LiveConfig, TomTomConfig
from app.models.live_segments import LiveSegment
from app.settings import Settings
from tests.conftest import FakeClock, log_in
from tests.orchestrator_support import engines_with

KEY = "fake-tomtom-key-ABC123xyz"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tomtom"
TTL = 300
CLASSES = (0.8, 0.6, 0.4)
LIMIT = 10_000  # più dei tratti che i test chiedono: la soglia non scatta se non la si prova
SEGMENTS = [
    LiveSegment(id=f"tratto_{n}", label=f"Tratto {n}", lat=40.83 + n / 1000, lon=14.23)
    for n in range(3)
]


def body(speed: float = 30.0) -> dict[str, Any]:
    raw = next(FIXTURES.glob("flow_*.json")).read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(raw)
    data["flowSegmentData"]["currentSpeed"] = speed
    return data


class Tomtom:
    """Un TomTom finto: conta le richieste e risponde con ciò che gli si dice."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.status = 200
        self.speed = 30.0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request.url.params["point"])
        if self.status != 200:
            return httpx2.Response(self.status, json={"error": "boom"})
        return httpx2.Response(200, json=body(self.speed))


def make(
    tomtom: Tomtom | None, clock: Callable[[], float], *, segments: list[LiveSegment] | None = None
) -> LiveFlowService:
    client = (
        TomTomClient(
            KEY,
            TomTomConfig(timeout_s=5, retries=0, max_concurrency=5),
            transport=httpx2.MockTransport(tomtom),
        )
        if tomtom is not None
        else None
    )
    return LiveFlowService(
        SEGMENTS if segments is None else segments,
        client,
        ttl_s=TTL,
        clock=clock,
        ratio_classes=CLASSES,
        daily_limit=LIMIT,
    )


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- l'header: senza `X-View: live` TomTom non si chiama -----------------------------------------


def test_senza_la_vista_live_non_si_chiama_tomtom(clock: FakeClock) -> None:
    tomtom = Tomtom()
    service = make(tomtom, clock)
    response = run(service.flow(live_view=False))
    assert tomtom.calls == []
    assert response.mode == "unavailable" and response.segments == []
    assert response.degraded_reason == LIVE_VIEW_REQUIRED


def test_dalla_vista_live_i_tratti_scaduti_si_chiedono_a_tomtom(clock: FakeClock) -> None:
    tomtom = Tomtom()
    response = run(make(tomtom, clock).flow(live_view=True))
    assert len(tomtom.calls) == len(SEGMENTS)
    assert response.mode == "fresh" and response.degraded_reason is None
    assert [s.id for s in response.segments] == [s.id for s in SEGMENTS]  # nell'ordine del file
    first = response.segments[0]
    assert first.label == "Tratto 0"
    assert (first.current_speed.kind, first.ratio.kind) == ("real", "estimate")
    assert first.current_speed.source == "tomtom.flow"


# --- la cache di 5 minuti ------------------------------------------------------------------------


def test_la_cache_di_cinque_minuti_si_rispetta(clock: FakeClock) -> None:
    tomtom = Tomtom()
    service = make(tomtom, clock)
    run(service.flow(live_view=True))
    clock.advance(TTL - 1)
    second = run(service.flow(live_view=True))
    assert len(tomtom.calls) == len(SEGMENTS)  # nessuna chiamata nuova
    assert second.mode == "cached"
    clock.advance(1)  # ora ha 300 s: scaduta
    third = run(service.flow(live_view=True))
    assert len(tomtom.calls) == 2 * len(SEGMENTS)
    assert third.mode == "fresh"


def test_la_cache_vale_anche_senza_la_vista_live(clock: FakeClock) -> None:
    """Chi non è in vista LIVE legge ciò che c'è, e non cambia la cache né chiama TomTom."""
    tomtom = Tomtom()
    service = make(tomtom, clock)
    run(service.flow(live_view=True))
    response = run(service.flow(live_view=False))
    assert response.mode == "cached" and len(tomtom.calls) == len(SEGMENTS)


def test_ogni_tratto_porta_l_ora_in_cui_e_stato_chiesto(clock: FakeClock) -> None:
    tomtom = Tomtom()
    service = make(tomtom, clock)
    first = run(service.flow(live_view=True)).segments[0].fetched_at
    clock.advance(TTL)
    second = run(service.flow(live_view=True)).segments[0].fetched_at
    assert (second - first).total_seconds() == pytest.approx(TTL, abs=1e-3)
    assert all(m.as_of == second for m in (run(service.flow(live_view=False)).segments[0].ratio,))


def test_aggiorna_solo_i_tratti_scaduti(clock: FakeClock) -> None:
    tomtom = Tomtom()
    service = make(tomtom, clock)
    run(service.flow(live_view=True))  # tutti a 0 s
    clock.advance(200)
    # un tratto in più, che non c'era: solo lui è «scaduto» (non ha mai avuto un dato)
    extra = LiveSegment(id="nuovo", label="Nuovo", lat=40.9, lon=14.3)
    service._segments = (*service._segments, extra)  # noqa: SLF001 (i tratti sono di config)
    tomtom.calls.clear()
    response = run(service.flow(live_view=True))
    assert len(tomtom.calls) == 1 and response.mode == "fresh"


# --- errori e snapshot ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "reason"),
    [(500, "tomtom_unreachable"), (429, "tomtom_rate_limited"), (403, "tomtom_key_rejected")],
)
def test_un_errore_di_tomtom_restituisce_lo_snapshot(
    clock: FakeClock, status: int, reason: str
) -> None:
    tomtom = Tomtom()
    service = make(tomtom, clock)
    first = run(service.flow(live_view=True))
    clock.advance(TTL + 60)
    tomtom.status = status
    response = run(service.flow(live_view=True))
    assert response.mode == "snapshot" and response.degraded_reason == reason
    # l'ultimo dato noto, con la sua ora (mostrato come REALE «ultimo dato disponibile»)
    assert [s.fetched_at for s in response.segments] == [s.fetched_at for s in first.segments]
    assert {s.current_speed.kind for s in response.segments} == {"real"}


def test_senza_snapshot_un_errore_e_unavailable(clock: FakeClock) -> None:
    tomtom = Tomtom()
    tomtom.status = 500
    response = run(make(tomtom, clock).flow(live_view=True))
    assert response.mode == "unavailable" and response.segments == []
    assert response.degraded_reason == "tomtom_unreachable"


def test_senza_chiave_si_dice_chiave_mancante(clock: FakeClock) -> None:
    service = make(None, clock)
    response = run(service.flow(live_view=True))
    assert (response.mode, response.degraded_reason) == ("unavailable", KEY_MISSING)


def test_senza_chiave_ma_con_uno_snapshot_si_mostra_lo_snapshot(clock: FakeClock) -> None:
    tomtom = Tomtom()
    service = make(tomtom, clock)
    run(service.flow(live_view=True))
    service._client = None  # noqa: SLF001 (la chiave sparisce dopo il primo dato)
    clock.advance(TTL + 1)
    response = run(service.flow(live_view=True))
    assert (response.mode, response.degraded_reason) == ("snapshot", KEY_MISSING)
    assert len(response.segments) == len(SEGMENTS)


def test_un_errore_su_alcuni_tratti_usa_lo_snapshot_solo_per_quelli(clock: FakeClock) -> None:
    """Due tratti aggiornati e uno no: tre tratti, modo «snapshot», il motivo è quello di TomTom."""
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        point = request.url.params["point"]
        if calls["n"] > len(SEGMENTS) and point.startswith("40.832"):
            return httpx2.Response(500, json={})
        return httpx2.Response(200, json=body(30))

    client = TomTomClient(
        KEY,
        TomTomConfig(timeout_s=5, retries=0, max_concurrency=5),
        transport=httpx2.MockTransport(handler),
    )
    service = LiveFlowService(
        SEGMENTS, client, ttl_s=TTL, clock=clock, ratio_classes=CLASSES, daily_limit=LIMIT
    )
    first = run(service.flow(live_view=True))
    clock.advance(TTL + 1)
    response = run(service.flow(live_view=True))
    assert (response.mode, response.degraded_reason) == ("snapshot", "tomtom_unreachable")
    ages = {s.id: s.fetched_at for s in response.segments}
    old = {s.id: s.fetched_at for s in first.segments}
    assert ages["tratto_2"] == old["tratto_2"]  # quello che non ha risposto: l'ultimo dato
    assert ages["tratto_0"] > old["tratto_0"] and ages["tratto_1"] > old["tratto_1"]
    # il riepilogo porta l'ora del dato più recente che usa (la media e i conteggi sono di tutti)
    derived = [m for m in response.summary if not m.id.endswith("slowest_speed")]
    assert {m.as_of for m in derived} == {max(ages.values())}


def test_senza_nessun_dato_ne_snapshot_il_motivo_c_e_sempre(clock: FakeClock) -> None:
    service = make(Tomtom(), clock, segments=[])  # nessun tratto: niente da mostrare
    response = run(service.flow(live_view=True))
    assert response.mode == "unavailable" and response.degraded_reason == NO_DATA


# --- più utenti, un solo aggiornamento -----------------------------------------------------------


def test_piu_utenti_in_vista_live_fanno_un_solo_aggiornamento(clock: FakeClock) -> None:
    tomtom = Tomtom()
    service = make(tomtom, clock)

    async def together() -> list[Any]:
        return list(await asyncio.gather(*(service.flow(live_view=True) for _ in range(6))))

    responses = run(together())
    assert len(tomtom.calls) == len(SEGMENTS)  # non 6 × i tratti
    assert sorted(r.mode for r in responses) == ["cached"] * 5 + ["fresh"]


# --- la chiave non esce da nessuna parte ---------------------------------------------------------


def test_la_chiave_non_compare_in_nessun_log_ne_risposta(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    tomtom = Tomtom()
    service = make(tomtom, clock)
    ok = run(service.flow(live_view=True))
    clock.advance(TTL + 1)
    tomtom.status = 403
    failed = run(service.flow(live_view=True))
    for response in (ok, failed):
        assert KEY not in response.model_dump_json()
    assert KEY not in caplog.text
    assert KEY not in repr(service)


# --- la costruzione dalle impostazioni -----------------------------------------------------------


def settings(**changes: Any) -> Settings:
    fields: dict[str, Any] = {"env": "local", "data_dir": Path("/nonexistent"), **changes}
    return Settings(**fields)


def test_senza_chiave_o_senza_che_le_impostazioni_la_dicano_non_c_e_il_client(
    clock: FakeClock,
) -> None:
    config = LiveConfig.from_yaml()
    for present, env in (
        (False, {"TOMTOM_API_KEY": KEY}),
        (True, {}),
        (True, {"TOMTOM_API_KEY": " "}),
    ):
        service = build_live_flow(
            settings(tomtom_key_present=present), clock, config=config, environ=env
        )
        assert service._client is None  # noqa: SLF001


def test_con_la_chiave_il_client_c_e_e_la_cache_e_quella_di_config(clock: FakeClock) -> None:
    config = LiveConfig.from_yaml()
    service = build_live_flow(
        settings(tomtom_key_present=True), clock, config=config, environ={"TOMTOM_API_KEY": KEY}
    )
    assert service._client is not None  # noqa: SLF001
    assert service._ttl_s == config.flow.cache_ttl_s == 300  # noqa: SLF001
    assert len(service._segments) == 14  # noqa: SLF001 (08 2: i 14 tratti)
    assert KEY not in repr(service) and KEY not in repr(service._client)  # noqa: SLF001
    run(service.aclose())
    assert GeoPoint(lat=40.0, lon=14.0)  # (nessun effetto: il client non ha chiamato nessuno)


# --- la soglia giornaliera (08 6) ----------------------------------------------------------------


def limited(
    tomtom: Tomtom, clock: FakeClock, limit: int, path: Path | None = None
) -> LiveFlowService:
    client = TomTomClient(
        KEY,
        TomTomConfig(timeout_s=5, retries=0, max_concurrency=5),
        transport=httpx2.MockTransport(tomtom),
    )
    return LiveFlowService(
        SEGMENTS,
        client,
        ttl_s=TTL,
        clock=clock,
        ratio_classes=CLASSES,
        daily_limit=limit,
        snapshot_path=path,
    )


def test_oltre_la_soglia_giornaliera_non_si_chiama_piu_e_si_mostra_lo_snapshot(
    clock: FakeClock,
) -> None:
    tomtom = Tomtom()
    service = limited(tomtom, clock, limit=len(SEGMENTS))  # basta per un solo giro
    first = run(service.flow(live_view=True))
    assert first.mode == "fresh" and len(tomtom.calls) == len(SEGMENTS)
    clock.advance(TTL + 1)
    second = run(service.flow(live_view=True))
    assert len(tomtom.calls) == len(SEGMENTS)  # nessuna chiamata nuova
    assert (second.mode, second.degraded_reason) == ("snapshot", "tomtom_daily_limit")
    assert [s.fetched_at for s in second.segments] == [s.fetched_at for s in first.segments]


def test_la_soglia_lascia_passare_quanti_tratti_restano(clock: FakeClock) -> None:
    """Tetto di 4 e tre tratti: il primo giro ne usa 3, il secondo ne può chiedere solo 1."""
    tomtom = Tomtom()
    service = limited(tomtom, clock, limit=4)
    run(service.flow(live_view=True))
    clock.advance(TTL + 1)
    tomtom.calls.clear()
    response = run(service.flow(live_view=True))
    assert len(tomtom.calls) == 1
    assert (response.mode, response.degraded_reason) == ("snapshot", "tomtom_daily_limit")
    ages = [s.fetched_at for s in response.segments]
    assert len(set(ages)) == 2  # uno aggiornato, due all'ultimo dato


def test_a_mezzanotte_di_roma_il_contatore_riparte(clock: FakeClock) -> None:
    tomtom = Tomtom()
    service = limited(tomtom, clock, limit=len(SEGMENTS))
    run(service.flow(live_view=True))
    clock.advance(TTL + 1)
    assert run(service.flow(live_view=True)).degraded_reason == "tomtom_daily_limit"
    clock.advance(24 * 3600)  # il giorno dopo
    again = run(service.flow(live_view=True))
    assert again.mode == "fresh" and again.degraded_reason is None


def test_con_il_tetto_a_zero_non_si_chiama_mai(clock: FakeClock) -> None:
    tomtom = Tomtom()
    response = run(limited(tomtom, clock, limit=0).flow(live_view=True))
    assert tomtom.calls == []
    assert (response.mode, response.degraded_reason) == ("unavailable", "tomtom_daily_limit")


def test_un_errore_di_tomtom_conta_come_richiesta_fatta(clock: FakeClock) -> None:
    """La quota di TomTom si consuma anche con un errore: si conta ciò che si chiede."""
    tomtom = Tomtom()
    tomtom.status = 500
    service = limited(tomtom, clock, limit=len(SEGMENTS))
    run(service.flow(live_view=True))
    assert len(tomtom.calls) == len(SEGMENTS)
    run(service.flow(live_view=True))
    assert len(tomtom.calls) == len(SEGMENTS)  # il tetto è già pieno


# --- lo snapshot su disco (08 5) -----------------------------------------------------------------


def test_lo_snapshot_si_scrive_a_ogni_aggiornamento_senza_la_chiave(
    clock: FakeClock, tmp_path: Path
) -> None:
    path = tmp_path / "tomtom" / "snapshot.json"
    tomtom = Tomtom()
    response = run(limited(tomtom, clock, 100, path).flow(live_view=True))
    text = path.read_text(encoding="utf-8")
    assert KEY not in text and "key=" not in text
    saved = json.loads(text)["segments"]
    assert [s["id"] for s in saved] == [s.id for s in SEGMENTS]
    assert saved[0]["current_speed"]["kind"] == "real"
    assert saved[0]["fetched_at"] == response.segments[0].fetched_at.isoformat()
    assert [p.name for p in path.parent.iterdir()] == ["snapshot.json"]  # nessun file di ripiego


def test_dopo_un_riavvio_senza_rete_si_mostra_l_ultimo_dato_con_la_sua_ora(
    clock: FakeClock, tmp_path: Path
) -> None:
    path = tmp_path / "snapshot.json"
    first = run(limited(Tomtom(), clock, 100, path).flow(live_view=True))
    clock.advance(3600)  # un'ora dopo, riavvio e nessuna chiave
    restarted = LiveFlowService(
        SEGMENTS,
        None,
        ttl_s=TTL,
        clock=clock,
        ratio_classes=CLASSES,
        daily_limit=LIMIT,
        snapshot_path=path,
    )
    response = run(restarted.flow(live_view=True))
    assert (response.mode, response.degraded_reason) == ("snapshot", KEY_MISSING)
    assert [s.fetched_at for s in response.segments] == [s.fetched_at for s in first.segments]
    assert response.segments[0].current_speed.kind == "real"  # REALE, «ultimo dato disponibile»


def test_un_riavvio_entro_cinque_minuti_riusa_il_dato_come_cache(
    clock: FakeClock, tmp_path: Path
) -> None:
    path = tmp_path / "snapshot.json"
    run(limited(Tomtom(), clock, 100, path).flow(live_view=True))
    clock.advance(60)
    tomtom = Tomtom()
    restarted = limited(tomtom, clock, 100, path)
    response = run(restarted.flow(live_view=True))
    assert response.mode == "cached" and tomtom.calls == []


@pytest.mark.parametrize(
    "content", ["", "non json", "[]", '{"segments": 3}', '{"segments": [{"id": 1}]}']
)
def test_uno_snapshot_illeggibile_si_ignora(
    clock: FakeClock, tmp_path: Path, caplog: pytest.LogCaptureFixture, content: str
) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(content, encoding="utf-8")
    service = LiveFlowService(
        SEGMENTS,
        None,
        ttl_s=TTL,
        clock=clock,
        ratio_classes=CLASSES,
        daily_limit=LIMIT,
        snapshot_path=path,
    )
    response = run(service.flow(live_view=True))
    assert (response.mode, response.segments) == ("unavailable", [])
    assert "non si legge" in caplog.text


def test_senza_snapshot_su_disco_non_si_scrive_nulla(clock: FakeClock, tmp_path: Path) -> None:
    service = limited(Tomtom(), clock, 100)  # nessun percorso: solo in memoria
    run(service.flow(live_view=True))
    assert list(tmp_path.iterdir()) == []


def test_un_disco_che_non_scrive_non_ferma_live(
    clock: FakeClock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "tomtom"
    blocker.write_text("un file dove serve una cartella", encoding="utf-8")
    response = run(limited(Tomtom(), clock, 100, blocker / "snapshot.json").flow(live_view=True))
    assert response.mode == "fresh"
    assert "non si scrive" in caplog.text


def test_il_percorso_e_il_flag_vengono_dalle_impostazioni(clock: FakeClock, tmp_path: Path) -> None:
    config = LiveConfig.from_yaml()
    on = build_live_flow(settings(data_dir=tmp_path), clock, config=config, environ={})
    off = build_live_flow(
        settings(data_dir=tmp_path, live_snapshot_persist=False), clock, config=config, environ={}
    )
    assert on._snapshot_path == tmp_path / "tomtom" / "snapshot.json"  # noqa: SLF001
    assert off._snapshot_path is None  # noqa: SLF001
    limit = build_live_flow(
        settings(data_dir=tmp_path, tomtom_daily_limit=7), clock, config=config, environ={}
    )
    assert limit._daily_limit == 7  # noqa: SLF001


# --- l'endpoint -----------------------------------------------------------------------------------


def test_l_endpoint_chiama_tomtom_solo_con_x_view_live(
    settings: Settings, clock: FakeClock
) -> None:
    tomtom = Tomtom()
    app = create_app(settings, clock=clock, engines=engines_with(()), live_flow=make(tomtom, clock))
    with TestClient(app) as client:
        log_in(client)
        quiet = client.get("/api/live/flow")
        assert tomtom.calls == []
        assert (quiet.json()["mode"], quiet.json()["degraded_reason"]) == (
            "unavailable",
            "live_view_required",
        )
        live = client.get("/api/live/flow", headers={"X-View": "live"})
        assert live.status_code == 200 and live.json()["mode"] == "fresh"
        assert len(live.json()["segments"]) == len(SEGMENTS) and len(tomtom.calls) == len(SEGMENTS)
        again = client.get("/api/live/flow", headers={"X-View": "live"})
        assert again.json()["mode"] == "cached" and len(tomtom.calls) == len(SEGMENTS)
        plain = client.get("/api/live/flow")  # senza l'header legge la cache, e non chiama
        assert plain.json()["mode"] == "cached" and len(tomtom.calls) == len(SEGMENTS)
        assert KEY not in live.text


def test_l_endpoint_vuole_la_sessione(settings: Settings, clock: FakeClock) -> None:
    app = create_app(
        settings, clock=clock, engines=engines_with(()), live_flow=make(Tomtom(), clock)
    )
    with TestClient(app) as client:
        assert client.get("/api/live/flow", headers={"X-View": "live"}).status_code == 401


# --- le classi e il riepilogo della fascia LIVE ---------------------------------------------------


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (1.4, 0),
        (1.0, 0),
        (0.8, 0),
        (0.7999, 1),
        (0.6, 1),
        (0.5999, 2),
        (0.4, 2),
        (0.3999, 3),
        (0.0, 3),
    ],
)
def test_la_classe_dal_rapporto(ratio: float, expected: int) -> None:
    """Sotto una soglia si scende di classe, alla soglia no: 0,8 è ancora «scorrevole»."""
    assert congestion_class(ratio, CLASSES) == expected


@pytest.mark.parametrize(
    "ratio_classes",
    [
        "[0.8, 0.8, 0.4]",
        "[0.4, 0.6, 0.8]",
        "[1.2, 0.6, 0.4]",
        "[0.8, 0.6, 0]",
        "[0.8, 0.6]",
        "[0.8, 0.6, 0.4, 0.2]",
    ],
)
def test_le_soglie_della_configurazione_devono_essere_tre_e_decrescenti(ratio_classes: str) -> None:
    text = (
        "tomtom: {timeout_s: 5, retries: 1, max_concurrency: 5}\n"
        f"flow: {{cache_ttl_s: 300, ratio_classes: {ratio_classes}}}\n"
    )
    with pytest.raises(Exception, match="(?i)ratio_classes|validation|tuple|decrescenti"):
        LiveConfig.from_yaml_text(text)
    ok = LiveConfig.from_yaml_text(text.replace(ratio_classes, "[0.8, 0.6, 0.4]"))
    assert ok.flow.ratio_classes == (0.8, 0.6, 0.4)


def speeds_by_latitude(speeds: dict[str, float]) -> Callable[[httpx2.Request], httpx2.Response]:
    """Un TomTom che dà a ogni tratto la sua velocità (la chiave è l'inizio della latitudine)."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        point = request.url.params["point"]
        speed = next(v for k, v in speeds.items() if point.startswith(k))
        return httpx2.Response(200, json=body(speed))

    return handler


def three_speeds(clock: FakeClock) -> LiveFlowService:
    client = TomTomClient(
        KEY,
        TomTomConfig(timeout_s=5, retries=0, max_concurrency=5),
        transport=httpx2.MockTransport(
            speeds_by_latitude({"40.83,": 40, "40.8309": 20, "40.832": 5})
        ),
    )
    return LiveFlowService(
        SEGMENTS, client, ttl_s=TTL, clock=clock, ratio_classes=CLASSES, daily_limit=LIMIT
    )


def test_ogni_tratto_ha_la_sua_classe_dal_rapporto_con_il_flusso_libero(clock: FakeClock) -> None:
    response = run(three_speeds(clock).flow(live_view=True))
    free = response.segments[0].free_flow_speed.value
    for segment in response.segments:
        ratio = float(segment.ratio.value)
        assert ratio == pytest.approx(float(segment.current_speed.value) / float(free), abs=0.002)
        assert segment.congestion_class == congestion_class(ratio, CLASSES)
    assert (
        len({s.congestion_class for s in response.segments}) >= 2
    )  # velocità diverse, classi diverse


def test_il_riepilogo_dice_media_conteggi_e_tratto_piu_lento(clock: FakeClock) -> None:
    response = run(three_speeds(clock).flow(live_view=True))
    by_part = {m.id.rsplit(".", 1)[1]: m for m in response.summary}
    speeds = [float(s.current_speed.value) for s in response.segments]
    assert list(by_part) == [
        "mean_speed", "mean_ratio", "slowed_count", "slowest_speed", "covered_count",
    ]  # fmt: skip
    assert by_part["mean_speed"].value == round(sum(speeds) / 3, 1)
    assert by_part["slowed_count"].value == sum(s.congestion_class >= 1 for s in response.segments)
    assert by_part["slowest_speed"].value == min(speeds) == 5.0
    assert by_part["covered_count"].value == 3
    # provenienza: STIME per ciò che è derivato, REALE per la velocità di un tratto; ora del dato
    kinds = {part: m.kind for part, m in by_part.items()}
    assert kinds == {
        "mean_speed": "estimate", "mean_ratio": "estimate", "slowed_count": "estimate",
        "slowest_speed": "real", "covered_count": "estimate",
    }  # fmt: skip
    assert all(m.id.startswith("m.live.summary.") for m in response.summary)
    assert {m.as_of for m in response.summary} == {response.segments[0].fetched_at}
    assert by_part["mean_speed"].inputs == [s.current_speed.id for s in response.segments]
    assert "Tratto 2" in by_part["slowest_speed"].method  # dice quale
    assert by_part["slowest_speed"].inputs == [response.segments[2].current_speed.id]
    assert "3 tratti su 3" in by_part["mean_speed"].assumptions[0]


def test_il_riepilogo_dello_snapshot_porta_l_ora_del_dato_piu_recente(clock: FakeClock) -> None:
    tomtom = Tomtom()
    service = make(tomtom, clock)
    first = run(service.flow(live_view=True))
    clock.advance(TTL + 1)
    tomtom.status = 500
    response = run(service.flow(live_view=True))
    assert response.mode == "snapshot" and response.summary
    assert {m.as_of for m in response.summary} == {first.segments[0].fetched_at}


def test_senza_tratti_il_riepilogo_e_vuoto(clock: FakeClock) -> None:
    assert summarize([], total=14) == []
    unavailable = run(make(None, clock).flow(live_view=True))
    assert unavailable.summary == []


def test_un_riepilogo_dei_tratti_che_ci_sono_dice_quanti_su_quanti(clock: FakeClock) -> None:
    service = three_speeds(clock)
    full = run(service.flow(live_view=True))
    partial = summarize(full.segments[:2], total=3)
    covered = next(m for m in partial if m.id.endswith("covered_count"))
    assert covered.value == 2 and "2 tratti su 3" in covered.assumptions[0]


def test_uno_snapshot_di_prima_delle_classi_non_si_legge_e_si_ignora(
    clock: FakeClock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "snapshot.json"
    first = run(limited(Tomtom(), clock, 100, path).flow(live_view=True))
    document = json.loads(path.read_text(encoding="utf-8"))
    for item in document["segments"]:
        del item["congestion_class"]
    path.write_text(json.dumps(document), encoding="utf-8")
    service = LiveFlowService(
        SEGMENTS,
        None,
        ttl_s=TTL,
        clock=clock,
        ratio_classes=CLASSES,
        daily_limit=LIMIT,
        snapshot_path=path,
    )
    assert run(service.flow(live_view=True)).segments == []
    assert "non si legge" in caplog.text
    assert first.segments  # (il primo giro c'era)
