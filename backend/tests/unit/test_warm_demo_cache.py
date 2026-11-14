import json
from pathlib import Path
from typing import Any

import pytest

from app.data.seeds import load_seed_events
from app.db.repository import Repository
from app.llm.cache import read_demo_file
from app.llm.client import LlmUnavailable
from app.llm.gemini import TokenUsage
from app.models.llm_config import LlmConfig
from app.settings import Settings
from scripts.warm_demo_cache import (
    RecordingClient,
    WarmError,
    check_coverage,
    main,
    warm_all,
    warm_event,
)
from tests.agents_support import CATALOG, CONFIG
from tests.orchestrator_support import LIVE_ANSWERS, RoutingBackend, StubEngines, engines_with

TWO = ((1001, "Piazza Vittoria", 1.2), (1002, "Piazza Sannazaro", 1.2))


class MeteredRouting(RoutingBackend):
    """Il servizio finto con il conto dei token, come `GeminiBackend`."""

    def __init__(self, answers: dict[str, str] | None = None) -> None:
        super().__init__(LIVE_ANSWERS if answers is None else answers)
        self.usage = TokenUsage()
        self.requests = 0

    async def generate(self, **kwargs: Any) -> str:
        self.requests += 1
        if "ping" in kwargs["contents"]:
            return '{"ok": true}'
        text = await super().generate(**kwargs)
        self.usage.add(None)
        return text


class FailingBackend(MeteredRouting):
    async def generate(self, **kwargs: Any) -> str:
        raise LlmUnavailable("nessuna rete")


def settings_for(tmp_path: Path, limit: int = 30) -> Settings:
    return Settings(
        env="local",
        data_dir=tmp_path / "data",
        app_password=None,
        session_secret=None,
        llm_mode="live",
        gemini_model="modello-prova",
        llm_daily_call_limit=limit,
    )


def fixtures(
    tmp_path: Path, backend: MeteredRouting, limit: int = 30
) -> tuple[Repository, RecordingClient]:
    repo = Repository(tmp_path / "warm.sqlite")
    load_seed_events(repo)
    client = RecordingClient(
        mode="live",
        model="modello-prova",
        daily_limit=limit,
        config=LlmConfig.from_yaml(),
        repo=repo,
        backend=backend,
    )
    return repo, client


def engines() -> StubEngines:
    return engines_with(TWO)


async def warmed(tmp_path: Path, backend: MeteredRouting | None = None, limit: int = 30):  # type: ignore[no-untyped-def]
    backend = backend or MeteredRouting()
    repo, client = fixtures(tmp_path, backend, limit)
    return await warm_event(
        "match_2027", client=client, repo=repo, engines=engines(), config=CONFIG, catalog=CATALOG
    )


# --- le risposte registrate ---------------------------------------------------------------------


async def test_si_registrano_le_risposte_dei_sei_testi_del_run(tmp_path: Path) -> None:
    """Domanda, Traffic, Transit, piano, ripianificazione dopo il rifiuto e avviso."""
    file = await warmed(tmp_path)
    assert (file.event_id, file.model, file.version) == ("match_2027", "modello-prova", 1)
    assert len(file.entries) == 6
    assert len({e.key for e in file.entries}) == 6 and all(len(e.key) == 64 for e in file.entries)
    assert json.loads(file.entries[0].response_json)["text"]  # la risposta, non l'input


async def test_un_run_nuovo_con_un_altro_id_e_coperto_dalla_cache(tmp_path: Path) -> None:
    """Il punto della cache demo: la chiave non dipende dall'id del run, che è casuale."""
    file = await warmed(tmp_path)
    assert await check_coverage(file, engines=engines(), config=CONFIG, catalog=CATALOG) == []


@pytest.mark.parametrize("index", range(6))
async def test_una_voce_mancante_si_segnala(tmp_path: Path, index: int) -> None:
    file = await warmed(tmp_path)
    holey = file.model_copy(
        update={"entries": [e for i, e in enumerate(file.entries) if i != index]}
    )
    holes = await check_coverage(holey, engines=engines(), config=CONFIG, catalog=CATALOG)
    assert holes and all("(cache_miss)" in hole for hole in holes), holes


async def test_il_modello_e_parte_della_chiave(tmp_path: Path) -> None:
    file = await warmed(tmp_path)
    other = file.model_copy(update={"model": "un-altro-modello"})
    holes = await check_coverage(other, engines=engines(), config=CONFIG, catalog=CATALOG)
    assert len(holes) >= 1 and all("cache_miss" in hole for hole in holes)


# --- quando non si esporta ----------------------------------------------------------------------


async def test_un_testo_che_non_viene_dall_llm_non_si_esporta(tmp_path: Path) -> None:
    backend = MeteredRouting({**LIVE_ANSWERS, "Sei il Traffic Agent": "non json"})
    with pytest.raises(
        WarmError,
        match=r"match_2027: testi che non vengono dall'LLM: traffic \(invalid_response\)",
    ):
        await warmed(tmp_path, backend)


async def test_il_tetto_di_chiamate_vale_anche_per_il_riscaldamento(tmp_path: Path) -> None:
    with pytest.raises(WarmError, match=r"\(budget\)"):
        await warmed(tmp_path, limit=3)


async def test_un_run_che_finisce_in_errore_non_si_esporta(tmp_path: Path) -> None:
    backend = MeteredRouting()
    repo, client = fixtures(tmp_path, backend)
    broken = engines()
    broken.fail_road = ValueError("Grafo mancante")
    with pytest.raises(WarmError, match="il run è finito in ERROR: ValueError: Grafo mancante"):
        await warm_event(
            "match_2027", client=client, repo=repo, engines=broken, config=CONFIG, catalog=CATALOG
        )


async def test_un_evento_che_non_c_e(tmp_path: Path) -> None:
    repo, client = fixtures(tmp_path, MeteredRouting())
    with pytest.raises(WarmError, match="'fantasma' non trovato"):
        await warm_event(
            "fantasma", client=client, repo=repo, engines=engines(), config=CONFIG, catalog=CATALOG
        )


# --- l'intero script ----------------------------------------------------------------------------


async def test_due_eventi_due_file_e_il_consumo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = MeteredRouting()
    out = tmp_path / "demo_cache"
    code = await warm_all(
        ["match_2027", "regate_sep_2026"],
        settings=settings_for(tmp_path),
        api_key="fake-chiave",
        out_dir=out,
        engines=engines(),
        backend=backend,
    )
    captured = capsys.readouterr()
    text = captured.out
    assert code == 0, captured.err
    assert sorted(p.name for p in out.glob("*.json")) == ["match_2027.json", "regate_sep_2026.json"]
    assert read_demo_file(out / "match_2027.json").model == "modello-prova"
    assert "Modello modello-prova" in text and "tetto 30 chiamate" in text
    assert "verifica in cache_only riuscita" in text and "ragionamento 0 token" in text
    assert "fake-chiave" not in text  # la chiave non si stampa


async def test_la_prova_del_servizio_fallita_ferma_tutto(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "demo_cache"
    code = await warm_all(
        ["match_2027"],
        settings=settings_for(tmp_path),
        api_key="k",
        out_dir=out,
        engines=engines(),
        backend=FailingBackend(),
    )
    err = capsys.readouterr().err
    assert (
        code == 1 and "il servizio non risponde" in err and "non è stato fatto nient'altro" in err
    )
    assert not out.exists() or list(out.glob("*.json")) == []


async def test_al_primo_errore_non_si_prosegue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = MeteredRouting({**LIVE_ANSWERS, "Sei il Traffic Agent": "non json"})
    out = tmp_path / "demo_cache"
    code = await warm_all(
        ["match_2027", "regate_sep_2026"],
        settings=settings_for(tmp_path),
        api_key="k",
        out_dir=out,
        engines=engines(),
        backend=backend,
    )
    err = capsys.readouterr().err
    assert code == 1 and "match_2027: testi che non vengono dall'LLM" in err
    assert "Consumo fino a qui" in err
    assert list(out.glob("*.json")) == []  # né il file dell'evento fallito né quello dopo
    assert backend.agents.count("Sei il Traffic Agent") == 2  # prima chiamata + nuovo tentativo


# --- avvio dalla riga di comando ----------------------------------------------------------------


def test_senza_chiave_o_modello_non_si_fa_nulla(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    for env in ({}, {"GEMINI_API_KEY": "k"}, {"GEMINI_MODEL": "m"}):
        assert main([], {"DATA_DIR": str(tmp_path), **env}) == 2
        assert "servono GEMINI_API_KEY e GEMINI_MODEL" in capsys.readouterr().err


def test_un_evento_non_seed_si_rifiuta(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    env = {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "m", "DATA_DIR": str(tmp_path)}
    assert main(["--events", "fantasma"], env) == 2
    assert "eventi non seed: fantasma" in capsys.readouterr().err


def test_senza_i_dati_dei_motori_non_si_chiama_niente(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    env = {"GEMINI_API_KEY": "k", "GEMINI_MODEL": "m", "DATA_DIR": str(tmp_path)}
    assert main([], env) == 2
    assert "I dati dei motori non sono disponibili" in capsys.readouterr().err


def test_la_verifica_non_vuole_ne_chiave_ne_modello(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main(["--verify-only"], {"DATA_DIR": str(tmp_path)})  # niente chiave: non serve
    err = capsys.readouterr().err
    assert code == 2 and "I dati dei motori non sono disponibili" in err and "GEMINI" not in err


def test_un_ambiente_non_valido_e_un_errore(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([], {"LLM_DAILY_CALL_LIMIT": "molti"}) == 2
    assert "LLM_DAILY_CALL_LIMIT" in capsys.readouterr().err
