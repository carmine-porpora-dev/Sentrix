import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from app.agents.runner import AgentRunner
from app.data.map_data import MapData
from app.data.paths import DataPaths
from app.data.seeds import load_seed_events, read_seed_events
from app.db.repository import Repository
from app.llm.cache import (
    DEFAULT_DEMO_CACHE_DIR,
    DemoCacheError,
    DemoCacheFile,
    export_demo_cache,
    import_demo_cache,
    read_demo_file,
)
from app.llm.client import (
    InvalidResponse,
    LlmBackend,
    LlmClient,
    LlmOutcome,
    LlmRequest,
    LlmUnavailable,
)
from app.llm.factory import gemini_backend
from app.llm.gemini import TokenUsage
from app.models.agents_config import AgentsConfig
from app.models.catalog import CatalogConfig
from app.models.config import EngineConfig
from app.models.llm_config import LlmConfig
from app.models.run import AttendanceLevel, Run
from app.operations.center import OperationsCenter
from app.operations.registry import DepartmentRegistry
from app.orchestrator.engines import Engines
from app.orchestrator.service import EngineProvider, EnginesUnavailable, new_run
from app.orchestrator.state_machine import Orchestrator
from app.settings import Settings, SettingsError, load_env_file
from scripts.common import atomic_write_text

LEVEL: AttendanceLevel = "mid"
PING_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


class MeteredBackend(LlmBackend, Protocol):
    """Il servizio e il conto dei token che ha consumato (`GeminiBackend` e, nei test, un finto)."""

    usage: TokenUsage


class WarmError(Exception):
    """Un evento che non si può riscaldare, o una cache che non copre un run: il messaggio dice
    perché."""


class RecordingClient(LlmClient):
    """Un client che ricorda le chiavi delle risposte dell'LLM (o della cache) e i ripieghi sui
    testi di riserva, con il motivo."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.keys: list[str] = []
        self.fallbacks: list[str] = []

    async def complete[T](self, request: LlmRequest[T]) -> LlmOutcome[T]:
        outcome = await super().complete(request)
        if outcome.origin == "template":
            self.fallbacks.append(f"{request.agent} ({outcome.degraded or 'senza motivo'})")
        else:
            self.keys.append(outcome.key)
        return outcome

    def reset(self) -> None:
        self.keys.clear()
        self.fallbacks.clear()


async def _no_wait(_seconds: float) -> None:
    """I dipartimenti simulati non aspettano: qui si riscalda, non si fa una demo."""
    await asyncio.sleep(0)


async def run_event(
    event_id: str,
    *,
    client: LlmClient,
    repo: Repository,
    engines: Engines,
    config: AgentsConfig,
    catalog: CatalogConfig,
) -> Run:
    event = repo.get_event(event_id)
    if event is None:
        raise WarmError(f"Evento '{event_id}' non trovato")
    run = new_run(event, LEVEL, client.mode)
    repo.add_run(run)
    center = OperationsCenter(
        repo,
        DepartmentRegistry.from_yaml(),
        add_runs_default=EngineConfig.from_yaml().transit.add_runs_default,
        sleep=_no_wait,
    )
    orchestrator = Orchestrator(
        repo=repo,
        center=center,
        runner=AgentRunner(client, config, catalog),
        engines=engines,
        config=config,
    )
    final = await orchestrator.execute(run.id)
    await center.settle()
    return final


async def warm_event(
    event_id: str,
    *,
    client: RecordingClient,
    repo: Repository,
    engines: Engines,
    config: AgentsConfig,
    catalog: CatalogConfig,
) -> DemoCacheFile:
    """Un run vero dell'evento e le risposte che ha usato. `WarmError` se il run non finisce o se
    anche un solo testo non viene dall'LLM."""
    client.reset()
    run = await run_event(
        event_id, client=client, repo=repo, engines=engines, config=config, catalog=catalog
    )
    if run.state != "DONE":
        raise WarmError(f"{event_id}: il run è finito in {run.state}: {run.error}")
    if client.fallbacks:
        raise WarmError(
            f"{event_id}: testi che non vengono dall'LLM: {', '.join(client.fallbacks)}"
        )
    try:
        return export_demo_cache(repo, event_id=event_id, model=client.model, keys=client.keys)
    except DemoCacheError as exc:
        raise WarmError(f"{event_id}: {exc}") from exc


async def check_coverage(
    file: DemoCacheFile,
    *,
    engines: Engines,
    config: AgentsConfig,
    catalog: CatalogConfig,
) -> list[str]:
    """I testi che un run NUOVO dell'evento non troverebbe nella cache demo (`[]` = coperto): lo
    rifà in `cache_only`, senza servizio e senza spendere, con un database vuoto e la cache
    importata. Ogni voce è «agente (motivo)»."""
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "demo"
        directory.mkdir()
        (directory / f"{file.event_id}.json").write_text(file.model_dump_json(), encoding="utf-8")
        repo = Repository(Path(tmp) / "verifica.sqlite")
        load_seed_events(repo)
        import_demo_cache(repo, directory)
        client = RecordingClient(
            mode="cache_only",
            model=file.model,
            daily_limit=0,
            config=LlmConfig.from_yaml(),
            repo=repo,
        )
        run = await run_event(
            file.event_id, client=client, repo=repo, engines=engines, config=config, catalog=catalog
        )
        problems = list(client.fallbacks)
        if run.state != "DONE":
            problems.append(f"run in {run.state}: {run.error}")
        return problems


def _parse_ping(raw: str) -> bool:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise InvalidResponse("non è JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        raise InvalidResponse("manca il campo booleano 'ok'")
    return bool(data["ok"])


async def preflight(client: LlmClient) -> None:
    """Una chiamata minuscola: la chiave e il modello rispondono? Conta nel tetto."""
    outcome = await client.complete(
        LlmRequest(
            agent="preflight",
            prompt_version="preflight@1",
            system="Rispondi solo con un oggetto JSON conforme allo schema.",
            payload={"ping": True},
            schema=PING_SCHEMA,
            parse=_parse_ping,
        )
    )
    if outcome.origin == "template":
        raise WarmError(
            f"il servizio non risponde ({outcome.degraded}): controlla GEMINI_API_KEY e "
            "GEMINI_MODEL; non è stato fatto nient'altro"
        )


def _usage_line(usage: TokenUsage) -> str:
    return (
        f"{usage.calls} chiamate riuscite · ingresso {usage.prompt} token · uscita {usage.output} "
        f"token · ragionamento {usage.thoughts} token"
    )


async def warm_all(
    event_ids: Sequence[str],
    *,
    settings: Settings,
    api_key: str,
    out_dir: Path,
    engines: Engines,
    backend: MeteredBackend | None = None,
) -> int:
    config, catalog = AgentsConfig.from_yaml(), CatalogConfig.from_yaml()
    llm_config = LlmConfig.from_yaml()
    backend = backend or gemini_backend(api_key, llm_config)
    print(
        f"Modello {settings.gemini_model} · eventi {', '.join(event_ids)} · livello {LEVEL} · "
        f"tetto {settings.llm_daily_call_limit} chiamate · destinazione {out_dir}"
    )
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp) / "warm.sqlite")  # un solo database: il tetto vale per tutti
        load_seed_events(repo)
        client = RecordingClient(
            mode="live",
            model=settings.gemini_model,
            daily_limit=settings.llm_daily_call_limit,
            config=llm_config,
            repo=repo,
            backend=backend,
        )
        try:
            await preflight(client)
            print(f"Prova del servizio riuscita · {_usage_line(backend.usage)}")
            for event_id in event_ids:
                file = await warm_event(
                    event_id,
                    client=client,
                    repo=repo,
                    engines=engines,
                    config=config,
                    catalog=catalog,
                )
                holes = await check_coverage(file, engines=engines, config=config, catalog=catalog)
                if holes:
                    raise WarmError(
                        f"{event_id}: la cache appena registrata non copre un run nuovo: "
                        + ", ".join(holes)
                    )
                atomic_write_text(
                    out_dir / f"{event_id}.json", file.model_dump_json(indent=2) + "\n"
                )
                print(
                    f"{event_id}: {len(file.entries)} voci scritte, verifica in cache_only "
                    f"riuscita · totale {_usage_line(backend.usage)}"
                )
        except (WarmError, LlmUnavailable) as exc:
            print(f"ERRORE: {exc}", file=sys.stderr)
            print(f"Consumo fino a qui: {_usage_line(backend.usage)}", file=sys.stderr)
            return 1
    print(f"Fatto. Consumo: {_usage_line(backend.usage)}")
    return 0


async def verify_all(event_ids: Sequence[str], *, directory: Path, engines: Engines) -> int:
    """La cache demo copre un run nuovo di ogni evento? Nessuna chiamata."""
    config, catalog = AgentsConfig.from_yaml(), CatalogConfig.from_yaml()
    failed = 0
    for event_id in event_ids:
        path = directory / f"{event_id}.json"
        try:
            file = read_demo_file(path)
        except DemoCacheError as exc:
            print(f"{event_id}: {exc}", file=sys.stderr)
            failed += 1
            continue
        holes = await check_coverage(file, engines=engines, config=config, catalog=catalog)
        print(f"{event_id}: {'coperto' if not holes else 'BUCHI: ' + ', '.join(holes)}")
        failed += bool(holes)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--events", nargs="+", help="default: tutti gli eventi seed")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_DEMO_CACHE_DIR)
    parser.add_argument(
        "--verify-only", action="store_true", help="solo la verifica in cache_only, senza chiamate"
    )
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if environ is None:
        load_env_file()
        environ = os.environ
    try:
        settings = Settings.from_env(environ)
    except SettingsError as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 2
    api_key = environ.get("GEMINI_API_KEY", "").strip()
    if not args.verify_only and (not api_key or not settings.gemini_model):
        print(
            "ERRORE: servono GEMINI_API_KEY e GEMINI_MODEL nell'ambiente (.env): "
            "non è stato fatto nulla",
            file=sys.stderr,
        )
        return 2
    seeds = [event.id for event in read_seed_events()]
    event_ids = args.events or seeds
    unknown = [e for e in event_ids if e not in seeds]
    if unknown:
        print(
            f"ERRORE: eventi non seed: {', '.join(unknown)} (seed: {', '.join(seeds)})",
            file=sys.stderr,
        )
        return 2
    try:
        engines = EngineProvider(
            MapData(DataPaths(settings.data_dir)), AgentsConfig.from_yaml().labels.route_classes
        ).get()
    except EnginesUnavailable as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 2
    if args.verify_only:
        return asyncio.run(verify_all(event_ids, directory=args.out_dir, engines=engines))
    return asyncio.run(
        warm_all(
            event_ids, settings=settings, api_key=api_key, out_dir=args.out_dir, engines=engines
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
