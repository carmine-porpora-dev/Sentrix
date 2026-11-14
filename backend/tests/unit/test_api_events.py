import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.data.seeds import DEFAULT_SEEDS_DIR
from app.main import create_app
from app.models.event import Event
from app.settings import Settings
from tests.conftest import FakeClock, log_in
from tests.support import ctx_of

SERVER_FIELDS = ("revision", "created_at", "updated_at")


def seed_json(name: str = "regate_sep_2026") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DEFAULT_SEEDS_DIR / f"{name}.json").read_text("utf-8"))
    return data


def body_of(event_id: str = "mio_evento", **changes: Any) -> dict[str, Any]:
    """Un corpo valido per POST/PUT: un preset senza i campi del server, con un altro id."""
    body = {k: v for k, v in seed_json().items() if k not in SERVER_FIELDS}
    body["id"] = event_id
    body.update(changes)
    return body


# --- lettura ---------------------------------------------------------------------------------


def test_elenco_con_i_due_preset(authed: TestClient) -> None:
    rows = authed.get("/api/events").json()
    assert {row["id"] for row in rows} == {"regate_sep_2026", "match_2027"}
    for row in rows:
        assert set(row) == {"id", "name", "date", "is_seed", "revision", "updated_at"}
        assert row["is_seed"] is True and row["revision"] == 1


def test_lettura_di_un_preset_e_uguale_al_file(authed: TestClient) -> None:
    served = authed.get("/api/events/match_2027").json()
    on_disk = Event.model_validate(seed_json("match_2027"))
    assert Event.model_validate(served) == on_disk


def test_evento_inesistente_404(authed: TestClient) -> None:
    response = authed.get("/api/events/non_esiste")
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "Evento non trovato",
        "details": {},
    }


# --- creazione -------------------------------------------------------------------------------


def test_creazione(authed: TestClient) -> None:
    response = authed.post("/api/events", json=body_of())
    assert response.status_code == 201
    created = Event.model_validate(response.json())
    assert created.id == "mio_evento" and created.revision == 1
    assert created.created_at == created.updated_at
    assert created.name == seed_json()["name"]
    # si ritrova uguale, ed è un evento dell'utente, non un preset
    assert authed.get("/api/events/mio_evento").json() == response.json()
    row = next(r for r in authed.get("/api/events").json() if r["id"] == "mio_evento")
    assert row["is_seed"] is False


def test_creazione_con_id_esistente_409(authed: TestClient) -> None:
    assert authed.post("/api/events", json=body_of()).status_code == 201
    again = authed.post("/api/events", json=body_of())
    assert again.status_code == 409 and again.json()["error"]["code"] == "EVENT_EXISTS"
    seed_clash = authed.post("/api/events", json=body_of("match_2027"))
    assert seed_clash.status_code == 409  # un preset non si sovrascrive creando


@pytest.mark.parametrize("field", SERVER_FIELDS)
def test_i_campi_del_server_non_si_accettano_nel_corpo(authed: TestClient, field: str) -> None:
    body = body_of()
    body[field] = 1 if field == "revision" else "2026-01-01T00:00:00+01:00"
    response = authed.post("/api/events", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"][0]["path"] == field


def test_errori_per_campo_anche_annidati(authed: TestClient) -> None:
    body = body_of()
    body["attendance"] = {**body["attendance"], "low": 90000}  # low > mid
    body["arrival"] = {**body["arrival"], "peak": "25:99"}
    body["name"] = ""
    response = authed.post("/api/events", json=body)
    assert response.status_code == 400
    fields = {f["path"] for f in response.json()["error"]["details"]["fields"]}
    assert "name" in fields and "arrival.peak" in fields
    assert any(path.startswith("attendance") for path in fields)
    assert authed.get("/api/events/mio_evento").status_code == 404  # niente a metà


def test_corpo_senza_campi_obbligatori(authed: TestClient) -> None:
    response = authed.post("/api/events", json={"id": "vuoto"})
    assert response.status_code == 400
    fields = {f["path"] for f in response.json()["error"]["details"]["fields"]}
    assert {"name", "date", "area_center", "arrival", "departure", "attendance"} <= fields


def test_id_non_valido_400(authed: TestClient) -> None:
    for bad in ("Maiuscole", "con spazi", "1numero", "", "a-b"):
        assert authed.post("/api/events", json=body_of(bad)).status_code == 400, bad


# --- modifica --------------------------------------------------------------------------------


def test_modifica_incrementa_la_revisione_e_conserva_lo_storico(
    app: FastAPI, authed: TestClient
) -> None:
    created = authed.post("/api/events", json=body_of()).json()
    response = authed.put("/api/events/mio_evento", json=body_of(name="Nome nuovo"))
    assert response.status_code == 200
    updated = Event.model_validate(response.json())
    assert (updated.revision, updated.name) == (2, "Nome nuovo")
    assert updated.created_at == Event.model_validate(created).created_at
    assert updated.updated_at >= updated.created_at
    # la revisione superata resta consultabile (i run che l'hanno usata ritrovano l'evento)
    old = ctx_of(app).repo.get_event_revision("mio_evento", 1)
    assert old is not None and old.name == seed_json()["name"]
    assert authed.put("/api/events/mio_evento", json=body_of()).json()["revision"] == 3


def test_modifica_di_un_preset_resta_un_preset(authed: TestClient) -> None:
    body = body_of("match_2027", name="Match modificato")
    assert authed.put("/api/events/match_2027", json=body).json()["revision"] == 2
    row = next(r for r in authed.get("/api/events").json() if r["id"] == "match_2027")
    assert row["is_seed"] is True and row["revision"] == 2


def test_modifica_con_id_diverso_dal_percorso_400(authed: TestClient) -> None:
    authed.post("/api/events", json=body_of())
    response = authed.put("/api/events/mio_evento", json=body_of("altro_id"))
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"][0] == {
        "path": "id",
        "message": "deve coincidere con l'id nel percorso",
        "type": "id_mismatch",
    }
    assert authed.get("/api/events/altro_id").status_code == 404  # non si crea per errore


def test_modifica_di_un_evento_inesistente_404(authed: TestClient) -> None:
    assert authed.put("/api/events/fantasma", json=body_of("fantasma")).status_code == 404


def test_modifica_non_valida_non_cambia_nulla(authed: TestClient) -> None:
    authed.post("/api/events", json=body_of())
    broken = body_of(name="")
    assert authed.put("/api/events/mio_evento", json=broken).status_code == 400
    after = authed.get("/api/events/mio_evento").json()
    assert after["revision"] == 1 and after["name"] == seed_json()["name"]


# --- ripristino ------------------------------------------------------------------------------


def test_ripristino_di_un_preset(authed: TestClient) -> None:
    authed.put("/api/events/match_2027", json=body_of("match_2027", name="Modificato"))
    response = authed.post("/api/events/match_2027/reset")
    assert response.status_code == 200
    restored = Event.model_validate(response.json())
    on_disk = Event.model_validate(seed_json("match_2027"))
    assert restored.revision == 3  # una nuova revisione: la modifica resta nello storico
    assert restored.model_dump(exclude=set(SERVER_FIELDS)) == on_disk.model_dump(
        exclude=set(SERVER_FIELDS)
    )
    assert restored.created_at == on_disk.created_at


def test_ripristino_di_un_evento_dell_utente_409(authed: TestClient) -> None:
    authed.post("/api/events", json=body_of())
    response = authed.post("/api/events/mio_evento/reset")
    assert response.status_code == 409 and response.json()["error"]["code"] == "NOT_A_SEED"


def test_ripristino_di_un_evento_inesistente_404(authed: TestClient) -> None:
    assert authed.post("/api/events/fantasma/reset").status_code == 404


def test_ripristino_se_il_file_del_preset_non_c_e_piu(
    settings: Settings, clock: FakeClock, tmp_path: Path
) -> None:
    seeds = tmp_path / "seeds"
    shutil.copytree(DEFAULT_SEEDS_DIR, seeds)
    with TestClient(create_app(settings, clock=clock, seeds_dir=seeds)) as c:
        log_in(c)
        (seeds / "match_2027.json").unlink()
        response = c.post("/api/events/match_2027/reset")
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "File del preset non trovato"


# --- avvio -----------------------------------------------------------------------------------


def test_i_preset_non_si_ricaricano_se_gia_presenti(settings: Settings, clock: FakeClock) -> None:
    """Riavviare l'app non deve cancellare il lavoro dell'utente su un preset."""
    first = create_app(settings, clock=clock)
    with TestClient(first) as c:
        log_in(c)
        c.put("/api/events/match_2027", json=body_of("match_2027", name="Mio match"))
    second = create_app(settings, clock=clock)
    with TestClient(second) as c:
        log_in(c)
        assert c.get("/api/events/match_2027").json()["name"] == "Mio match"
