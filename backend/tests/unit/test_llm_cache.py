import json
import threading
from datetime import datetime
from pathlib import Path

import pytest

from app.clock import ROME
from app.db.repository import Repository
from app.llm.cache import (
    DEMO_CACHE_VERSION,
    DemoCacheError,
    cache_key,
    canonical_json,
    export_demo_cache,
    import_demo_cache,
)
from tests.llm_support import make_llm_repo


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return make_llm_repo(tmp_path)


def write_demo(directory: Path, name: str, entries: list[dict[str, str]], **fields: object) -> Path:
    directory.mkdir(exist_ok=True)
    body = {"version": DEMO_CACHE_VERSION, "event_id": "match_2027", "model": "m", **fields}
    path = directory / name
    path.write_text(json.dumps({**body, "entries": entries}), encoding="utf-8")
    return path


# --- chiave --------------------------------------------------------------------------------------


def test_json_canonico() -> None:
    assert canonical_json({"b": [1, 2], "a": "è"}) == '{"a":"è","b":[1,2]}'
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


def test_la_chiave_e_lo_sha256_dei_quattro_pezzi() -> None:
    key = cache_key("m", "traffic@1", {"type": "object"}, {"x": 1})
    again = cache_key("m", "traffic@1", {"type": "object"}, {"x": 1})
    assert key == again and len(key) == 64
    for other in (
        cache_key("n", "traffic@1", {"type": "object"}, {"x": 1}),
        cache_key("m", "traffic@2", {"type": "object"}, {"x": 1}),
        cache_key("m", "traffic@1", {"type": "array"}, {"x": 1}),
        cache_key("m", "traffic@1", {"type": "object"}, {"x": 2}),
    ):
        assert other != key


def test_pezzi_diversi_non_si_confondono_se_concatenati() -> None:
    """«ab» + «c» e «a» + «bc» sono la stessa stringa concatenata, ma non la stessa chiave."""
    assert cache_key("ab", "c", {}, {}) != cache_key("a", "bc", {}, {})


# --- archivio ------------------------------------------------------------------------------------


def test_scrittura_e_lettura(repo: Repository) -> None:
    assert repo.get_llm_response("k") is None
    assert repo.put_llm_response("k", '{"a":1}') is True
    assert repo.get_llm_response("k") == '{"a":1}'


def test_overwrite_sostituisce_e_overwrite_falso_no(repo: Repository) -> None:
    repo.put_llm_response("k", "uno")
    assert repo.put_llm_response("k", "due", overwrite=False) is False
    assert repo.get_llm_response("k") == "uno"
    assert repo.put_llm_response("k", "tre") is True
    assert repo.get_llm_response("k") == "tre"


def test_il_contatore_non_supera_il_tetto_nemmeno_con_thread_in_parallelo(
    repo: Repository,
) -> None:
    granted: list[bool] = []

    def call() -> None:
        granted.append(repo.try_count_llm_call("2026-11-11", 5))

    threads = [threading.Thread(target=call) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert granted.count(True) == 5 and repo.llm_calls("2026-11-11") == 5


def test_tetto_zero_non_lascia_passare_niente(repo: Repository) -> None:
    assert repo.try_count_llm_call("2026-11-11", 0) is False
    assert repo.llm_calls("2026-11-11") == 0


def test_il_contatore_ricorda_dopo_un_riavvio(tmp_path: Path) -> None:
    first = make_llm_repo(tmp_path)
    first.try_count_llm_call("2026-11-11", 10)
    first.try_count_llm_call("2026-11-11", 10)
    second = Repository(tmp_path / "llm.sqlite")  # un processo nuovo sullo stesso file
    assert second.llm_calls("2026-11-11") == 2


# --- cache demo ----------------------------------------------------------------------------------


def test_importa_le_voci_di_tutti_i_file(repo: Repository, tmp_path: Path) -> None:
    directory = tmp_path / "demo_cache"
    write_demo(directory, "match_2027.json", [{"key": "a", "response_json": "1"}])
    write_demo(
        directory,
        "regate.json",
        [{"key": "b", "response_json": "2"}, {"key": "c", "response_json": "3"}],
    )
    assert import_demo_cache(repo, directory) == 3
    assert [repo.get_llm_response(k) for k in "abc"] == ["1", "2", "3"]


def test_non_sovrascrive_cio_che_c_e_gia_e_si_puo_ripetere(
    repo: Repository, tmp_path: Path
) -> None:
    repo.put_llm_response("a", "gia-nel-database")
    directory = tmp_path / "demo_cache"
    write_demo(directory, "x.json", [{"key": "a", "response_json": "dal-file"}])
    assert import_demo_cache(repo, directory) == 0
    assert repo.get_llm_response("a") == "gia-nel-database"
    assert import_demo_cache(repo, directory) == 0  # idempotente


def test_una_cartella_che_non_c_e_e_una_cache_vuota(repo: Repository, tmp_path: Path) -> None:
    assert import_demo_cache(repo, tmp_path / "non_esiste") == 0


@pytest.mark.parametrize(
    "content",
    [
        "non json",
        "[]",
        '{"version": 1}',
        '{"version": 1, "event_id": "e", "model": "m", "entries": [{}]}',
    ],
)
def test_un_file_malformato_e_un_errore_non_una_voce_persa(
    repo: Repository, tmp_path: Path, content: str
) -> None:
    directory = tmp_path / "demo_cache"
    directory.mkdir()
    (directory / "rotto.json").write_text(content, encoding="utf-8")
    with pytest.raises(DemoCacheError, match="rotto.json"):
        import_demo_cache(repo, directory)


def test_una_versione_diversa_e_un_errore(repo: Repository, tmp_path: Path) -> None:
    directory = tmp_path / "demo_cache"
    write_demo(directory, "x.json", [], version=99)
    with pytest.raises(DemoCacheError, match="versione 99"):
        import_demo_cache(repo, directory)


def test_esporta_e_reimporta_le_stesse_voci(repo: Repository, tmp_path: Path) -> None:
    repo.put_llm_response("a", "1")
    repo.put_llm_response("b", "2")
    repo.put_llm_response("non-usata", "9")
    exported = export_demo_cache(
        repo, event_id="match_2027", model="gemini-x", keys=["b", "a", "b"]
    )
    assert exported.version == DEMO_CACHE_VERSION and exported.model == "gemini-x"
    assert [e.key for e in exported.entries] == ["b", "a"]  # nell'ordine dato, senza doppioni
    directory = tmp_path / "demo_cache"
    directory.mkdir()
    (directory / "match_2027.json").write_text(exported.model_dump_json(), encoding="utf-8")
    fresh = make_llm_repo(tmp_path / "altro")
    assert import_demo_cache(fresh, directory) == 2
    assert (fresh.get_llm_response("a"), fresh.get_llm_response("b")) == ("1", "2")
    assert fresh.get_llm_response("non-usata") is None


def test_esportare_una_chiave_che_manca_e_un_errore(repo: Repository) -> None:
    repo.put_llm_response("a", "1")
    with pytest.raises(DemoCacheError, match="non presenti"):
        export_demo_cache(repo, event_id="e", model="m", keys=["a", "mancante-0123456789"])


def test_la_data_di_registrazione_si_puo_dare(repo: Repository) -> None:
    moment = datetime(2026, 11, 11, 9, 0, tzinfo=ROME)
    repo.put_llm_response("k", "v", at=moment)
    with repo._connection() as conn:
        stored = conn.execute("SELECT created_at FROM llm_cache").fetchone()[0]
    assert stored == moment.isoformat()
