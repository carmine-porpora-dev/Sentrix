import ast
import asyncio
import contextlib
import copy
import json
import logging
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.clock import ROME
from app.data import tomtom
from app.data.tomtom import (
    FLOW_PATH,
    FlowReading,
    TomTomClient,
    TomTomError,
    parse_flow,
    redact,
    to_segment_flow,
)
from app.models.geo import GeoPoint
from app.models.live_config import LiveConfig, TomTomConfig
from app.models.live_segments import LiveSegment

KEY = "fake-tomtom-key-ABC123xyz"
BACKEND = Path(__file__).resolve().parents[2]
FIXTURES = BACKEND / "tests" / "fixtures" / "tomtom"
CONFIG = TomTomConfig(timeout_s=5, retries=1, max_concurrency=5)
RATIO_CLASSES = LiveConfig.from_yaml().flow.ratio_classes
POINT = GeoPoint(lat=40.8325, lon=14.2330)
FETCHED = datetime(2026, 11, 9, 12, 0, 0, tzinfo=ROME)
Handler = Callable[[httpx2.Request], Any]


def real(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((FIXTURES / f"flow_{name}.json").read_text(encoding="utf-8"))
    return body


def client(handler: Handler, config: TomTomConfig = CONFIG) -> TomTomClient:
    return TomTomClient(KEY, config, transport=httpx2.MockTransport(handler))


def answer(body: Any, status: int = 200) -> Handler:
    return lambda request: httpx2.Response(status, json=body)


# --- le tre risposte vere ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "frc", "speeds", "times", "points"),
    [
        ("via_caracciolo", "FRC2", (27, 27), (299, 299), 141),
        ("tangenziale_vomero", "FRC0", (80, 80), (58, 58), 74),
        ("via_marina", "FRC2", (36, 45), (57, 46), 36),
    ],
)
def test_le_risposte_vere_si_leggono(
    name: str, frc: str, speeds: tuple[int, int], times: tuple[int, int], points: int
) -> None:
    reading = parse_flow(real(name))
    assert reading.frc == frc and reading.confidence == 1 and reading.road_closure is False
    assert (reading.current_speed_kmh, reading.free_flow_speed_kmh) == speeds
    assert (reading.current_travel_time_s, reading.free_flow_travel_time_s) == times
    assert len(reading.coordinates) == points


def test_il_primo_punto_e_quello_della_risposta() -> None:
    reading = parse_flow(real("via_caracciolo"))
    assert reading.coordinates[0] == (40.83219722073369, 14.234381279497029)  # (lat, lon)


def test_la_lunghezza_del_segmento_e_quella_della_geometria() -> None:
    # 00 2.4: «segmento di 2.246 m» per Via Caracciolo, calcolato dalla sonda sugli stessi punti
    assert parse_flow(real("via_caracciolo")).length_m() == pytest.approx(2246, abs=2)


async def test_la_richiesta_ha_percorso_punto_e_chiave() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=real("via_marina"))

    async with client(handler) as c:
        reading = await c.fetch(POINT)
    (request,) = seen
    assert request.method == "GET" and request.url.path == FLOW_PATH
    assert request.url.host == "api.tomtom.com"
    assert dict(request.url.params) == {"point": "40.8325,14.233", "key": KEY}
    assert request.headers["user-agent"] == "NapoliUrbanOps/0.1"
    assert request.headers["accept"] == "application/json"
    assert reading.free_flow_speed_kmh == 45


# --- da lettura a misure -----------------------------------------------------------------------

SEGMENT = LiveSegment(id="via_marina", label="Via Marina", lat=40.845665, lon=14.263074)


def test_le_misure_hanno_tipo_unita_e_provenienza() -> None:
    flow = to_segment_flow(SEGMENT, parse_flow(real("via_marina")), FETCHED, RATIO_CLASSES)
    assert (flow.id, flow.label, flow.fetched_at) == ("via_marina", "Via Marina", FETCHED)
    cur, free, ratio = flow.current_speed, flow.free_flow_speed, flow.ratio
    assert (cur.id, free.id, ratio.id) == (
        "m.live.via_marina.current_speed",
        "m.live.via_marina.free_flow_speed",
        "m.live.via_marina.ratio",
    )
    assert (cur.value, free.value, ratio.value) == (36, 45, 0.8)
    assert (cur.unit, free.unit, ratio.unit) == ("km/h", "km/h", "rapporto")
    assert (cur.kind, free.kind, ratio.kind) == ("real", "real", "estimate")  # 08 3
    assert {cur.source, free.source, ratio.source} == {"tomtom.flow"}
    assert ratio.inputs == [cur.id, free.id]  # derivato dalle due misure
    assert cur.as_of == free.as_of == ratio.as_of == FETCHED


def test_la_confidenza_e_la_lunghezza_del_segmento_sono_nelle_assunzioni() -> None:
    flow = to_segment_flow(SEGMENT, parse_flow(real("via_marina")), FETCHED, RATIO_CLASSES)
    notes = flow.current_speed.assumptions
    assert "confidence TomTom: 1" in notes
    assert "classe stradale TomTom FRC2" in notes
    assert any("non del solo punto richiesto" in n for n in notes)
    assert "tomtom flowSegmentData v4" in flow.current_speed.inputs
    assert "punto 40.845665,14.263074" in flow.current_speed.inputs


def test_la_geometria_e_una_linestring_in_lon_lat() -> None:
    reading = parse_flow(real("via_marina"))
    geometry = to_segment_flow(SEGMENT, reading, FETCHED, RATIO_CLASSES).geometry
    assert geometry["type"] == "LineString"
    coordinates = geometry["coordinates"]
    assert isinstance(coordinates, list) and len(coordinates) == 36
    assert coordinates[0] == [14.262713453327933, 40.84562570194135]  # GeoJSON: (lon, lat)


def test_il_rapporto_e_arrotondato_a_tre_decimali() -> None:
    body = real("via_marina")
    body["flowSegmentData"].update({"currentSpeed": 13, "freeFlowSpeed": 21})
    flow = to_segment_flow(SEGMENT, parse_flow(body), FETCHED, RATIO_CLASSES)
    assert flow.ratio.value == 0.619  # 13 ÷ 21 = 0,6190476…


def test_strada_chiusa_e_confidenza_bassa_si_dichiarano() -> None:
    body = real("via_marina")
    body["flowSegmentData"].update({"roadClosure": True, "confidence": 0.62, "currentSpeed": 0})
    flow = to_segment_flow(SEGMENT, parse_flow(body), FETCHED, RATIO_CLASSES)
    assert flow.current_speed.value == 0 and flow.ratio.value == 0
    assert "TomTom segnala la strada chiusa (roadClosure)" in flow.current_speed.assumptions
    assert "confidence TomTom: 0.62" in flow.current_speed.assumptions


# --- risposte con una forma sbagliata ----------------------------------------------------------


def broken(change: Callable[[dict[str, Any]], object]) -> Any:
    body = copy.deepcopy(real("via_marina"))
    change(body["flowSegmentData"])
    return body


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        "testo",
        None,
        {"flowSegmentData": 5},
        broken(lambda d: d.pop("currentSpeed")),
        broken(lambda d: d.pop("freeFlowSpeed")),
        broken(lambda d: d.pop("confidence")),
        broken(lambda d: d.pop("coordinates")),
        broken(lambda d: d.update(currentSpeed="36")),
        broken(lambda d: d.update(currentSpeed=True)),
        broken(lambda d: d.update(currentSpeed=None)),
        broken(lambda d: d.update(currentSpeed=-1)),
        broken(lambda d: d.update(currentSpeed=float("nan"))),
        broken(lambda d: d.update(freeFlowSpeed=0)),
        broken(lambda d: d.update(confidence=2)),
        broken(lambda d: d.update(confidence=-0.1)),
        broken(lambda d: d.update(roadClosure="sì")),
        broken(lambda d: d.update(currentTravelTime="presto")),
        broken(lambda d: d.update(coordinates={"coordinate": []})),
        broken(lambda d: d.update(coordinates={"coordinate": d["coordinates"]["coordinate"][:1]})),
        broken(lambda d: d.update(currentSpeed=float("inf"))),
        broken(lambda d: d.update(freeFlowSpeed=float("inf"))),
        broken(lambda d: d.update(confidence=float("nan"))),
        broken(lambda d: d["coordinates"]["coordinate"][0].update(latitude=float("nan"))),
        broken(lambda d: d["coordinates"]["coordinate"][0].update(longitude=float("inf"))),
        broken(lambda d: d["coordinates"]["coordinate"][0].update(latitude=91)),
        broken(lambda d: d["coordinates"]["coordinate"][0].update(longitude=-181)),
        broken(lambda d: d["coordinates"]["coordinate"][0].pop("latitude")),
        broken(lambda d: d["coordinates"]["coordinate"][0].update(longitude="14.2")),
    ],
)
def test_una_forma_inattesa_e_bad_response(body: Any) -> None:
    with pytest.raises(TomTomError) as caught:
        parse_flow(body)
    assert caught.value.code == "tomtom_bad_response"


def test_i_campi_facoltativi_possono_mancare() -> None:
    body = broken(
        lambda d: [
            d.pop(k) for k in ("frc", "currentTravelTime", "freeFlowTravelTime", "roadClosure")
        ]
    )
    reading = parse_flow(body)
    assert (reading.frc, reading.current_travel_time_s, reading.road_closure) == (None, None, False)


def test_il_messaggio_non_riporta_il_contenuto_della_risposta() -> None:
    body = broken(lambda d: d.update(currentSpeed="SEGRETO-DELLA-RISPOSTA"))
    with pytest.raises(TomTomError) as caught:
        parse_flow(body)
    everything = " ".join(
        [str(caught.value), repr(caught.value), *traceback.format_exception(caught.value)]
    )
    assert "SEGRETO" not in everything  # nemmeno nel traceback: niente catena con il valore
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# --- stati HTTP, errori di rete, tentativi ------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "tomtom_bad_request"),
        (404, "tomtom_bad_request"),
        (422, "tomtom_bad_request"),
        (401, "tomtom_key_rejected"),
        (403, "tomtom_key_rejected"),
        (429, "tomtom_rate_limited"),
        (500, "tomtom_unreachable"),
        (502, "tomtom_unreachable"),
        (503, "tomtom_unreachable"),
        (504, "tomtom_unreachable"),
        (302, "tomtom_bad_response"),
    ],
)
async def test_ogni_stato_ha_il_suo_codice(status: int, code: str) -> None:
    async with client(lambda request: httpx2.Response(status, json={})) as c:
        with pytest.raises(TomTomError) as caught:
            await c.fetch(POINT)
    assert (caught.value.code, caught.value.status) == (code, status)


class Counter:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes, self.calls = list(outcomes), 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return httpx2.Response(outcome, json=real("via_marina") if outcome == 200 else {})


async def test_un_errore_di_rete_o_un_5xx_si_riprova_una_volta() -> None:
    for first in (503, 500, httpx2.ConnectError("no"), httpx2.ReadTimeout("lento")):
        handler = Counter(first, 200)
        async with client(handler) as c:
            assert (await c.fetch(POINT)).current_speed_kmh == 36
        assert handler.calls == 2, first


async def test_dopo_il_tentativo_in_piu_ci_si_arrende() -> None:
    handler = Counter(503)
    async with client(handler) as c:
        with pytest.raises(TomTomError) as caught:
            await c.fetch(POINT)
    assert handler.calls == 2 and caught.value.code == "tomtom_unreachable"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
async def test_un_4xx_non_si_riprova(status: int) -> None:
    handler = Counter(status, 200)
    async with client(handler) as c:
        with pytest.raises(TomTomError):
            await c.fetch(POINT)
    assert handler.calls == 1  # riprovare non cambierebbe la risposta (e consumerebbe quota)


@pytest.mark.parametrize(("retries", "attempts"), [(0, 1), (1, 2), (3, 4)])
async def test_i_tentativi_sono_quelli_della_configurazione(retries: int, attempts: int) -> None:
    handler = Counter(500)
    config = TomTomConfig(timeout_s=5, retries=retries, max_concurrency=5)
    async with client(handler, config) as c:
        with pytest.raises(TomTomError):
            await c.fetch(POINT)
    assert handler.calls == attempts


async def test_un_timeout_e_un_errore_di_connessione_sono_unreachable() -> None:
    for error in (httpx2.ReadTimeout("t"), httpx2.ConnectTimeout("t"), httpx2.ConnectError("c")):
        async with client(Counter(error)) as c:
            with pytest.raises(TomTomError) as caught:
                await c.fetch(POINT)
        assert caught.value.code == "tomtom_unreachable"
        assert str(caught.value) == type(error).__name__  # solo il tipo, mai il testo dell'errore


async def test_una_redirezione_non_si_segue_perche_porterebbe_la_chiave_altrove() -> None:
    hosts: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        hosts.append(request.url.host)
        return httpx2.Response(302, headers={"Location": "https://altro-host.example/x?key=1"})

    async with client(handler) as c:
        with pytest.raises(TomTomError) as caught:
            await c.fetch(POINT)
    assert hosts == ["api.tomtom.com"]  # una sola richiesta: mai verso l'altro host
    assert caught.value.code == "tomtom_bad_response" and caught.value.status == 302


async def test_risposta_200_non_json_o_non_oggetto() -> None:
    cases = [
        lambda r: httpx2.Response(200, text="<html>no</html>"),
        lambda r: httpx2.Response(200, json=[1]),
    ]
    for handler in cases:
        async with client(handler) as c:
            with pytest.raises(TomTomError) as caught:
                await c.fetch(POINT)
        assert caught.value.code == "tomtom_bad_response"


async def test_il_motivo_di_tomtom_si_riporta_oscurato_e_accorciato() -> None:
    reason = f"Point too far key={KEY} oppure {KEY} " + "x" * 400
    body = {"detailedError": {"message": reason}}
    async with client(answer(body, 400)) as c:
        with pytest.raises(TomTomError) as caught:
            await c.fetch(POINT)
    message = str(caught.value)
    assert message.startswith("HTTP 400: Point too far") and "key=***" in message
    assert KEY not in message and len(message) <= tomtom.MAX_ERROR_TEXT
    async with client(answer({"error": "Forbidden"}, 400)) as c:
        with pytest.raises(TomTomError) as plain:
            await c.fetch(POINT)
    assert str(plain.value) == "HTTP 400: Forbidden"


# --- la chiave non compare mai -----------------------------------------------------------------


def failures() -> list[Handler]:
    leaky = httpx2.ConnectError(f"https://api.tomtom.com/x?key={KEY} irraggiungibile")

    def raising(request: httpx2.Request) -> httpx2.Response:
        raise leaky

    return [
        raising,
        answer({"error": f"key={KEY}"}, 400),
        answer({"error": KEY}, 401),
        answer({}, 403),
        answer({}, 429),
        answer({}, 503),
        answer({"flowSegmentData": {"currentSpeed": KEY}}),
        lambda request: httpx2.Response(200, text=KEY),
    ]


async def test_la_chiave_non_esce_da_nessun_errore() -> None:
    for handler in failures():
        c = client(handler)
        async with c:
            with pytest.raises(TomTomError) as caught:
                await c.fetch(POINT)
        error = caught.value
        everything = " ".join(
            [str(error), repr(error), repr(c), *traceback.format_exception(error)]
        )
        assert KEY not in everything, everything
        assert error.__cause__ is None  # niente catena che porti con sé l'URL
        assert error.__context__ is None or error.__suppress_context__


def test_il_repr_del_client_non_mostra_la_chiave() -> None:
    c = TomTomClient(KEY, CONFIG)
    assert KEY not in repr(c) and KEY not in str(c)
    assert "api.tomtom.com" in repr(c)


async def test_la_chiave_non_finisce_nei_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)  # tutto, anche l'INFO con l'URL che httpx2 registrerebbe
    for handler in [answer(real("via_marina")), *failures()]:
        async with client(handler) as c:
            with contextlib.suppress(TomTomError):
                await c.fetch(POINT)
    assert KEY not in caplog.text
    assert KEY not in " ".join(str(r.args) for r in caplog.records)


async def test_se_httpx2_viene_alzato_a_info_la_chiave_e_oscurata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # come farebbe chi accende i log verbosi: caplog lo alza e, a fine test, lo riporta com'era
    caplog.set_level(logging.INFO, logger="httpx2")
    async with client(answer(real("via_marina"))) as c:
        await c.fetch(POINT)
    lines = [r.getMessage() for r in caplog.records if r.name == "httpx2"]
    assert lines, "httpx2 doveva registrare la richiesta"
    assert all(KEY not in line for line in lines) and any("key=***" in line for line in lines)


def test_i_logger_dei_client_sono_tenuti_a_warning() -> None:
    assert logging.getLogger("httpx2").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    for name in ("httpx2", "httpcore"):
        assert any(isinstance(f, tomtom._RedactKeys) for f in logging.getLogger(name).filters)


def test_redact() -> None:
    assert redact("a?point=1,2&key=SEGRETO&x=1") == "a?point=1,2&key=***&x=1"
    assert redact("KEY=abc") == "key=***"
    assert redact("la chiave è SEGRETO ok", "SEGRETO") == "la chiave è *** ok"
    assert redact("niente da oscurare") == "niente da oscurare"


def test_una_chiave_vuota_non_e_ammessa() -> None:
    for empty in ("", "   "):
        with pytest.raises(ValueError, match="TOMTOM_API_KEY"):
            TomTomClient(empty, CONFIG)


# --- concorrenza -------------------------------------------------------------------------------


async def run_batch(count: int, limit: int) -> tuple[int, dict[str, Any]]:
    in_flight = peak = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return httpx2.Response(200, json=real("via_marina"))

    config = TomTomConfig(timeout_s=5, retries=1, max_concurrency=limit)
    points = {f"p{i}": GeoPoint(lat=40.8 + i / 1000, lon=14.2) for i in range(count)}
    async with client(handler, config) as c:
        results = await c.fetch_many(points)
    return peak, results


async def test_al_massimo_cinque_richieste_insieme() -> None:
    peak, results = await run_batch(12, 5)
    assert peak == 5 and len(results) == 12
    assert all(isinstance(r, FlowReading) for r in results.values())


async def test_il_limite_e_quello_della_configurazione() -> None:
    assert (await run_batch(9, 2))[0] == 2
    assert (await run_batch(4, 1))[0] == 1


async def test_fetch_many_non_solleva_e_tiene_l_ordine() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        lat = float(request.url.params["point"].split(",")[0])
        if lat > 40.84:
            return httpx2.Response(429, json={})
        return httpx2.Response(200, json=real("via_marina"))

    points = {
        "uno": GeoPoint(lat=40.81, lon=14.2),
        "due": GeoPoint(lat=40.85, lon=14.2),
        "tre": GeoPoint(lat=40.83, lon=14.2),
    }
    async with client(handler) as c:
        results = await c.fetch_many(points)
    assert list(results) == ["uno", "due", "tre"]
    assert isinstance(results["uno"], FlowReading) and isinstance(results["tre"], FlowReading)
    assert isinstance(results["due"], TomTomError) and results["due"].code == "tomtom_rate_limited"


async def test_fetch_many_senza_punti() -> None:
    async with client(answer({})) as c:
        assert await c.fetch_many({}) == {}


async def test_il_client_si_chiude() -> None:
    c = client(answer(real("via_marina")))
    async with c:
        pass
    assert c._http.is_closed


# --- configurazione ----------------------------------------------------------------------------


def test_la_configurazione_e_quella_della_spec() -> None:
    config = LiveConfig.from_yaml().tomtom
    assert (config.timeout_s, config.retries, config.max_concurrency) == (5, 1, 5)  # 08 3


@pytest.mark.parametrize(
    "text",
    [
        "tomtom: {timeout_s: 0, retries: 1, max_concurrency: 5}",
        "tomtom: {timeout_s: 5, retries: -1, max_concurrency: 5}",
        "tomtom: {timeout_s: 5, retries: 1, max_concurrency: 0}",
        "tomtom: {timeout_s: 5, retries: 1}",
        "tomtom: {timeout_s: 5, retries: 1, max_concurrency: 5, altro: 1}",
        "altro: 1",
    ],
)
def test_configurazione_non_valida(text: str) -> None:
    with pytest.raises(Exception, match="(?i)validation|Extra|required|greater|Field"):
        LiveConfig.from_yaml_text(text)


# --- architettura: due soli moduli hanno un client HTTP (TomTom e WhatsApp) --------------------


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_solo_gli_adattatori_hanno_un_client_http_in_app() -> None:
    """spech 12.1: oltre a TomTom, solo `notifications/whatsapp_client.py` (unica eccezione
    approvata alla regola «nessun invio verso l'esterno»); `operations/` resta senza."""
    clients = {"httpx", "httpx2", "requests", "aiohttp", "urllib.request", "http.client", "urllib3"}
    users = {
        path.relative_to(BACKEND).as_posix()
        for path in (BACKEND / "app").rglob("*.py")
        if imports_of(path) & clients
    }
    assert users == {"app/data/tomtom.py", "app/notifications/whatsapp_client.py"}


def test_l_indirizzo_di_tomtom_sta_in_un_posto_solo() -> None:
    holders = []
    for folder in ("app", "scripts"):
        for path in (BACKEND / folder).rglob("*.py"):
            strings = [
                n.value
                for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            ]
            if any("api.tomtom.com" in s or FLOW_PATH in s for s in strings):
                holders.append(path.relative_to(BACKEND).as_posix())
    assert holders == ["app/data/tomtom.py"]  # la sonda lo importa, non lo ripete


def test_le_fixture_non_contengono_la_chiave() -> None:
    files = sorted(FIXTURES.glob("*.json"))
    assert len(files) == 3
    for path in files:
        text = path.read_text(encoding="utf-8").lower()
        assert "key=" not in text and "apikey" not in text and "tomtom_api_key" not in text
    assert (FIXTURES / "README.md").is_file()
