import asyncio
import logging
from datetime import datetime
from pathlib import Path

import pytest

from app.clock import ROME
from app.db.repository import Repository
from app.llm.client import InvalidResponse, LlmUnavailable
from app.models.llm_config import LlmConfig
from tests.llm_support import (
    SCHEMA,
    FakeBackend,
    make_client,
    make_llm_repo,
    make_request,
)

GOOD = '{"text": "Incrocio critico a Piazza Vittoria"}'
OTHER = '{"text": "Seconda risposta"}'


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return make_llm_repo(tmp_path)


# --- modalità --------------------------------------------------------------------------------


async def test_template_non_chiama_nessuno_e_non_e_un_guasto(repo: Repository) -> None:
    backend = FakeBackend(GOOD)
    client = make_client(repo, backend, mode="template")
    outcome = await client.complete(make_request())
    assert outcome.value is None
    assert (outcome.origin, outcome.validation, outcome.degraded) == ("template", "fallback", None)
    assert outcome.calls == 0 and backend.calls == []


async def test_template_ignora_anche_la_cache(repo: Repository) -> None:
    client = make_client(repo, FakeBackend(), mode="template")
    repo.put_llm_response(client.key_for(make_request()), GOOD)
    assert (await client.complete(make_request())).value is None


async def test_live_chiama_valida_e_registra(repo: Repository) -> None:
    backend = FakeBackend(GOOD)
    client = make_client(repo, backend)
    request = make_request()
    outcome = await client.complete(request)
    assert outcome.value == "Incrocio critico a Piazza Vittoria"
    assert (outcome.origin, outcome.validation, outcome.degraded) == ("llm", "ok", None)
    assert outcome.calls == 1
    assert repo.get_llm_response(client.key_for(request)) == GOOD  # registrata: già validata
    (call,) = backend.calls
    assert call["model"] == "gemini-test" and call["system"] == "Sei il Traffic Agent."
    assert call["temperature"] == 0 and call["schema"] == SCHEMA
    assert call["contents"] == '{"incrocio":"Piazza Vittoria","vc":1.08}'  # input canonico


async def test_un_secondo_identico_non_richiama_l_llm(repo: Repository) -> None:
    backend = FakeBackend(GOOD)
    client = make_client(repo, backend)
    await client.complete(make_request())
    again = await client.complete(make_request())
    assert (again.origin, again.validation, again.calls) == ("llm_cache", "ok", 0)
    assert again.value == "Incrocio critico a Piazza Vittoria"
    assert len(backend.calls) == 1


async def test_cache_only_usa_la_cache_e_se_manca_ripiega_sui_template(repo: Repository) -> None:
    backend = FakeBackend(GOOD)
    client = make_client(repo, backend, mode="cache_only")
    miss = await client.complete(make_request())
    assert miss.value is None
    assert (miss.origin, miss.validation, miss.degraded) == ("template", "fallback", "cache_miss")
    repo.put_llm_response(client.key_for(make_request()), GOOD)
    hit = await client.complete(make_request())
    assert (hit.origin, hit.value) == ("llm_cache", "Incrocio critico a Piazza Vittoria")
    assert backend.calls == []  # mai una chiamata, in cache_only


async def test_una_voce_in_cache_non_piu_valida_e_come_se_mancasse(repo: Repository) -> None:
    """Una cache demo scritta con validatori più larghi: oggi non passa, non si usa."""
    stale = make_client(repo, FakeBackend(), mode="cache_only")
    repo.put_llm_response(stale.key_for(make_request()), '{"text": "  "}')
    outcome = await stale.complete(make_request())
    assert (outcome.value, outcome.degraded) == (None, "cache_invalid")
    # in live si ripete la chiamata e la voce buona sostituisce quella vecchia
    backend = FakeBackend(GOOD)
    live = make_client(repo, backend)
    fresh = await live.complete(make_request())
    assert (fresh.origin, fresh.value) == ("llm", "Incrocio critico a Piazza Vittoria")
    assert repo.get_llm_response(live.key_for(make_request())) == GOOD


@pytest.mark.parametrize(("model", "has_backend"), [(None, True), ("gemini-test", False)])
async def test_live_senza_modello_o_senza_chiave_ripiega_sui_template(
    repo: Repository, model: str | None, has_backend: bool
) -> None:
    client = make_client(repo, FakeBackend() if has_backend else None, model=model)
    outcome = await client.complete(make_request())
    assert (outcome.value, outcome.degraded) == (None, "not_configured")


# --- la chiave della cache ----------------------------------------------------------------------


async def test_la_chiave_cambia_con_modello_prompt_schema_e_input(repo: Repository) -> None:
    base = make_client(repo, None)
    key = base.key_for(make_request())
    assert len(key) == 64 and all(c in "0123456789abcdef" for c in key)
    assert make_client(repo, None, model="altro-modello").key_for(make_request()) != key
    assert base.key_for(make_request(prompt_version="traffic@2")) != key
    assert base.key_for(make_request(schema={**SCHEMA, "title": "x"})) != key
    assert base.key_for(make_request({"incrocio": "Piazza Vittoria", "vc": 1.09})) != key


async def test_la_chiave_non_dipende_dall_ordine_delle_chiavi_dell_input(repo: Repository) -> None:
    client = make_client(repo, None)
    one = make_request({"a": 1, "b": {"x": 1, "y": 2}})
    two = make_request({"b": {"y": 2, "x": 1}, "a": 1})
    assert client.key_for(one) == client.key_for(two)


# --- nuovo tentativo e testi di riserva -----------------------------------------------------------


async def test_risposta_non_valida_un_nuovo_tentativo_con_il_motivo_nel_prompt(
    repo: Repository,
) -> None:
    backend = FakeBackend("non è json", GOOD)
    client = make_client(repo, backend)
    outcome = await client.complete(make_request())
    assert (outcome.origin, outcome.validation, outcome.calls) == ("llm", "retried", 2)
    assert outcome.value == "Incrocio critico a Piazza Vittoria"
    first, second = backend.calls
    assert "risposta precedente non era valida" not in first["contents"]
    assert "La risposta precedente non era valida" in second["contents"]
    assert "non è un JSON con 'text'" in second["contents"]  # il motivo, dal validatore
    assert repo.get_llm_response(client.key_for(make_request())) == GOOD  # la valida, non la prima


async def test_due_risposte_non_valide_ripiegano_sui_template_e_non_si_registra_niente(
    repo: Repository,
) -> None:
    backend = FakeBackend("no", '{"text": ""}')
    client = make_client(repo, backend)
    outcome = await client.complete(make_request())
    assert (outcome.value, outcome.validation, outcome.degraded) == (
        None,
        "fallback",
        "invalid_response",
    )
    assert (outcome.origin, outcome.calls) == ("template", 2)
    assert repo.get_llm_response(client.key_for(make_request())) is None


async def test_i_tentativi_sono_quelli_della_configurazione(repo: Repository) -> None:
    for retries, expected_calls in ((0, 1), (2, 3)):
        backend = FakeBackend("no", "no", "no")
        config = LlmConfig(timeout_s=0.2, temperature=0, retries=retries)
        outcome = await make_client(repo, backend, config=config).complete(make_request())
        assert (outcome.calls, len(backend.calls)) == (expected_calls, expected_calls)


async def test_un_timeout_ripiega_subito_senza_nuovi_tentativi(repo: Repository) -> None:
    backend = FakeBackend(5.0)  # risponde dopo 5 s; il limite è 0,2 s
    outcome = await make_client(repo, backend).complete(make_request())
    assert (outcome.value, outcome.degraded, outcome.calls) == (None, "timeout", 1)
    assert len(backend.calls) == 1  # il run ha 120 s in tutto: niente altri tentativi


async def test_un_errore_del_servizio_ripiega_senza_nuovi_tentativi(repo: Repository) -> None:
    backend = FakeBackend(LlmUnavailable("ServerError 503"))
    outcome = await make_client(repo, backend).complete(make_request())
    assert (outcome.value, outcome.degraded, outcome.calls) == (None, "llm_error", 1)


async def test_il_parse_decide_che_cosa_e_valido(repo: Repository) -> None:
    def strict(raw: str) -> str:
        raise InvalidResponse("manca l'evidenza ev_1")

    backend = FakeBackend(GOOD, GOOD)
    outcome = await make_client(repo, backend).complete(make_request(parse=strict))
    assert outcome.degraded == "invalid_response"
    assert "manca l'evidenza ev_1" in backend.calls[1]["contents"]


# --- tetto giornaliero --------------------------------------------------------------------------


async def test_il_tetto_giornaliero_ferma_le_chiamate_e_ripiega(repo: Repository) -> None:
    backend = FakeBackend()
    client = make_client(repo, backend, limit=2)
    results = [await client.complete(make_request({"n": n})) for n in range(3)]
    assert [r.degraded for r in results] == [None, None, "budget"]
    assert results[2].value is None and results[2].calls == 0
    assert len(backend.calls) == 2
    assert repo.llm_calls("2026-11-11") == 2  # il conteggio è nel database, non in memoria


async def test_anche_il_nuovo_tentativo_conta_per_il_tetto(repo: Repository) -> None:
    backend = FakeBackend("no", GOOD)
    outcome = await make_client(repo, backend, limit=1).complete(make_request())
    assert (outcome.degraded, outcome.calls) == ("budget", 1)
    assert len(backend.calls) == 1


async def test_il_tetto_vale_per_giorno(repo: Repository) -> None:
    backend = FakeBackend()
    days = [datetime(2026, 11, 11, 23, 59, tzinfo=ROME), datetime(2026, 11, 12, 0, 1, tzinfo=ROME)]
    now = {"value": days[0]}
    client = make_client(repo, backend, limit=1, clock=lambda: now["value"])
    assert (await client.complete(make_request({"n": 1}))).degraded is None
    assert (await client.complete(make_request({"n": 2}))).degraded == "budget"
    now["value"] = days[1]  # il giorno dopo
    assert (await client.complete(make_request({"n": 3}))).degraded is None
    assert (repo.llm_calls("2026-11-11"), repo.llm_calls("2026-11-12")) == (1, 1)


async def test_il_tetto_vale_anche_con_agenti_in_parallelo(repo: Repository) -> None:
    backend = FakeBackend()
    client = make_client(repo, backend, limit=3)
    results = await asyncio.gather(*(client.complete(make_request({"n": n})) for n in range(10)))
    assert sum(r.calls for r in results) == 3 and len(backend.calls) == 3
    assert sorted(r.degraded or "" for r in results).count("budget") == 7


async def test_la_cache_non_conta_per_il_tetto(repo: Repository) -> None:
    client = make_client(repo, FakeBackend(), limit=1)
    await client.complete(make_request())
    for _ in range(5):
        assert (await client.complete(make_request())).origin == "llm_cache"
    assert repo.llm_calls("2026-11-11") == 1


# --- log ----------------------------------------------------------------------------------------


async def test_il_log_ha_durata_esito_e_chiave_abbreviata_e_niente_altro(
    repo: Repository, caplog: pytest.LogCaptureFixture
) -> None:
    request = make_request({"incrocio": "SEGRETO-DELL-INPUT"}, system="PROMPT-RISERVATO")
    client = make_client(repo, FakeBackend('{"text": "RISPOSTA-VISIBILE-SOLO-ALL-UTENTE"}'))
    with caplog.at_level(logging.DEBUG, logger="app.llm"):
        await client.complete(request)
    text = "\n".join(record.getMessage() for record in caplog.records)
    key = client.key_for(request)
    assert "agent=traffic" in text and "esito=llm/ok" in text and f"chiave={key[:12]}" in text
    assert "ms=" in text and key not in text  # la chiave intera non serve nel log
    for forbidden in ("SEGRETO-DELL-INPUT", "PROMPT-RISERVATO", "RISPOSTA-VISIBILE"):
        assert forbidden not in text
