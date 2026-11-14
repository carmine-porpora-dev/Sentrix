import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.data.paths import REPO_ROOT

SCRIPT = REPO_ROOT / "deploy" / "deploy.sh"
APP_UID = "10001"

# Valori finti: le prove controllano che non compaiano mai nell'output.
ENV_VALUES = {
    "DOMAIN": "demo.example.org",
    "APP_PASSWORD": "pw-finta-12345",
    "SESSION_SECRET": "segreto-finto-67890",
    "GEMINI_API_KEY": "chiave-gemini-finta",
    "GEMINI_MODEL": "modello-finto",
    "TOMTOM_API_KEY": "chiave-tomtom-finta",
    "DATA_DIR": "/data",
    "LLM_MODE": "cache_only",
    "ENV": "production",
}
SECRET_NAMES = ("APP_PASSWORD", "SESSION_SECRET", "GEMINI_API_KEY", "TOMTOM_API_KEY")
SECRET_VALUES = [ENV_VALUES[name] for name in SECRET_NAMES]  # il dominio è pubblico
CHOWN = f"docker run --rm -v /data:/data alpine:3.24.4 chown -R {APP_UID}:{APP_UID} /data"

STUB_DOCKER = """#!/bin/sh
echo "docker $*" >> "$STUB_DIR/calls.log"
case "$1 $2" in
  "image inspect")
    case "$3" in
      *:previous) [ -f "$STUB_DIR/no_previous" ] && exit 1 ;;
      *:latest) [ -f "$STUB_DIR/no_latest" ] && exit 1 ;;
    esac
    exit 0 ;;
  "compose build") [ -f "$STUB_DIR/build_fails" ] && exit 1; exit 0 ;;
  "compose ps") echo cid-di-prova; exit 0 ;;
  "compose logs") echo "riga di log dell'app"; exit 0 ;;
esac
if [ "$1" = inspect ]; then
  queue="$STUB_DIR/health_queue"
  if [ -s "$queue" ]; then
    head -n 1 "$queue"; tail -n +2 "$queue" > "$queue.rest"; mv "$queue.rest" "$queue"
  else
    echo "${STUB_HEALTH_DEFAULT:-healthy}"
  fi
fi
exit 0
"""
STUB_GIT = """#!/bin/sh
echo "git $*" >> "$STUB_DIR/calls.log"
[ "$1" = rev-parse ] && echo abc1234
exit 0
"""
STUB_SLEEP = """#!/bin/sh
echo "sleep $*" >> "$STUB_DIR/calls.log"
exit 0
"""


@dataclass
class Result:
    code: int
    out: str
    calls: list[str]

    def calls_of(self, tool: str) -> list[str]:
        return [c for c in self.calls if c.split()[0] == tool]


class Sandbox:
    """Una «VM» di prova: la cartella del repository con deploy.sh, il .env e i comandi finti."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.stubs = root / "stubs"
        self.stubs.mkdir()
        (root / "deploy").mkdir()
        shutil.copy(SCRIPT, root / "deploy" / "deploy.sh")
        for name, body in (("docker", STUB_DOCKER), ("git", STUB_GIT), ("sleep", STUB_SLEEP)):
            tool = self.stubs / name
            tool.write_text(body, encoding="utf-8")
            tool.chmod(0o755)
        self.write_env(ENV_VALUES)

    def write_env(self, values: dict[str, str]) -> None:
        text = "\n".join(f"{k}={v}" for k, v in values.items())
        (self.root / ".env").write_text("# commento\n" + text + "\n", encoding="utf-8")

    def flag(self, name: str) -> None:
        (self.stubs / name).write_text("", encoding="utf-8")

    def health_queue(self, *statuses: str) -> None:
        (self.stubs / "health_queue").write_text("\n".join(statuses) + "\n", encoding="utf-8")

    def run(self, *args: str, **env: str) -> Result:
        environment = {
            "PATH": f"{self.stubs}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "STUB_DIR": str(self.stubs),
            "HEALTH_WAIT_S": "3",
            "HEALTH_POLL_S": "1",
            **env,
        }
        done = subprocess.run(
            ["sh", str(self.root / "deploy" / "deploy.sh"), *args],
            capture_output=True,
            text=True,
            env=environment,
            cwd=self.root,
            check=False,
        )
        log = self.stubs / "calls.log"
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return Result(done.returncode, done.stdout + done.stderr, calls)


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def test_dry_run_mostra_i_passi_e_non_esegue_nulla(box: Sandbox) -> None:
    result = box.run("--dry-run")
    assert result.code == 0, result.out
    assert result.calls == []  # né git, né docker, né sleep
    steps = [line for line in result.out.splitlines() if line.startswith("[dry-run] ")]
    assert steps == [
        "[dry-run] git fetch --quiet origin main",
        "[dry-run] git reset --hard origin/main",
        f"[dry-run] {CHOWN}",
        "[dry-run] docker compose build app",
        "[dry-run] docker compose up -d",
        "[dry-run] docker image prune -f",
    ]
    assert "DRY RUN" in result.out


def test_dry_run_non_legge_il_env(box: Sandbox) -> None:
    (box.root / ".env").unlink()  # in locale non c'è: il dry-run funziona lo stesso
    assert box.run("--dry-run").code == 0


def test_un_argomento_sconosciuto_non_esegue_nulla(box: Sandbox) -> None:
    result = box.run("--forza")
    assert result.code != 0 and "uso:" in result.out
    assert result.calls == []


def test_deploy_riuscito_nell_ordine_giusto(box: Sandbox) -> None:
    result = box.run()
    assert result.code == 0, result.out
    docker = result.calls_of("docker")
    assert result.calls_of("git")[:2] == [
        "git fetch --quiet origin main",
        "git reset --hard origin/main",
    ]
    # permessi di /data, copia `previous`, build, avvio, e solo dopo la pulizia
    assert docker[0] == CHOWN
    order = [
        "docker image inspect napoli-urban-ops:latest",
        "docker tag napoli-urban-ops:latest napoli-urban-ops:previous",
        "docker compose build app",
        "docker compose up -d",
    ]
    positions = [docker.index(step) for step in order]
    assert positions == sorted(positions)
    assert docker[-1] == "docker image prune -f"
    assert "docker compose up -d --no-build app" not in docker  # nessun ritorno indietro
    assert "commit abc1234" in result.out
    assert "https://demo.example.org/api/health" in result.out


def test_il_primo_deploy_non_ha_una_versione_da_conservare(box: Sandbox) -> None:
    box.flag("no_latest")
    result = box.run()
    assert result.code == 0, result.out
    assert not [c for c in result.calls if c.startswith("docker tag")]


def test_non_stampa_mai_i_valori_del_env(box: Sandbox) -> None:
    for outcome in (box.run(), box.run("--dry-run")):
        for secret in SECRET_VALUES:
            assert secret not in outcome.out
    box.write_env({**ENV_VALUES, "ENV": "local"})  # anche quando il controllo fallisce
    failed = box.run()
    assert failed.code != 0
    for secret in SECRET_VALUES:
        assert secret not in failed.out


def test_senza_env_si_ferma_prima_di_toccare_docker(box: Sandbox) -> None:
    (box.root / ".env").unlink()
    result = box.run()
    assert result.code != 0 and ".env non trovato" in result.out
    assert result.calls_of("docker") == []


@pytest.mark.parametrize(
    "name",
    [
        "DOMAIN",
        "APP_PASSWORD",
        "SESSION_SECRET",
        "GEMINI_MODEL",
        "TOMTOM_API_KEY",
        "LLM_MODE",
        "ENV",
    ],
)
def test_una_variabile_obbligatoria_mancante_o_vuota_ferma_il_deploy(
    box: Sandbox, name: str
) -> None:
    box.write_env({k: v for k, v in ENV_VALUES.items() if k != name})
    assert name in box.run().out  # mancante: il messaggio la nomina
    box.write_env({**ENV_VALUES, name: ""})
    result = box.run()
    assert result.code != 0 and f"mancano o sono vuote: {name}" in result.out
    assert result.calls_of("docker") == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"ENV": "local"}, "ENV deve essere 'production'"),
        ({"LLM_MODE": "sempre"}, "LLM_MODE deve essere"),
        ({"LLM_MODE": "live", "GEMINI_API_KEY": ""}, "LLM_MODE=live richiede GEMINI_API_KEY"),
    ],
)
def test_valori_che_romperebbero_l_applicazione_ferma_il_deploy(
    box: Sandbox, changes: dict[str, str], message: str
) -> None:
    box.write_env({**ENV_VALUES, **changes})
    result = box.run()
    assert result.code != 0 and message in result.out
    assert result.calls_of("docker") == []


def test_la_chiave_gemini_non_serve_in_cache_only(box: Sandbox) -> None:
    box.write_env({k: v for k, v in ENV_VALUES.items() if k != "GEMINI_API_KEY"})
    assert box.run().code == 0


def test_il_env_con_virgolette_vale_come_senza(box: Sandbox) -> None:
    box.write_env({**ENV_VALUES, "ENV": '"production"', "DOMAIN": "'demo.example.org'"})
    assert box.run().code == 0


def test_se_la_build_fallisce_non_si_tocca_la_versione_in_esecuzione(box: Sandbox) -> None:
    box.flag("build_fails")
    result = box.run()
    assert result.code != 0
    assert "la versione in esecuzione non è stata toccata" in result.out
    assert "docker compose up -d" not in result.calls
    assert not [c for c in result.calls if c.startswith("docker tag napoli-urban-ops:previous")]


def test_se_l_app_non_sta_in_salute_si_torna_alla_versione_precedente(box: Sandbox) -> None:
    box.health_queue("unhealthy", "healthy")  # la nuova no, la precedente sì
    result = box.run()
    assert result.code != 0 and "deploy non riuscito" in result.out
    assert "riga di log dell'app" in result.out  # il log dell'app si vede nell'esito del deploy
    docker = result.calls_of("docker")
    back = [
        "docker tag napoli-urban-ops:previous napoli-urban-ops:latest",
        "docker compose up -d --no-build app",
    ]
    assert all(step in docker for step in back)
    assert docker.index(back[0]) < docker.index(back[1])  # prima il tag, poi l'avvio senza build
    assert "versione precedente ripristinata" in result.out
    assert "docker image prune -f" not in docker  # niente pulizia dopo un deploy fallito


def test_un_app_che_resta_in_avvio_oltre_il_tempo_e_un_fallimento(box: Sandbox) -> None:
    result = box.run(STUB_HEALTH_DEFAULT="starting")
    assert result.code != 0 and "non è in salute dopo 3 s" in result.out
    assert "docker compose up -d --no-build app" in result.calls


def test_se_nemmeno_la_precedente_sta_in_salute_lo_dice(box: Sandbox) -> None:
    result = box.run(STUB_HEALTH_DEFAULT="unhealthy")
    assert result.code != 0
    assert "nemmeno la versione precedente è in salute" in result.out


def test_al_primo_deploy_senza_precedente_non_c_e_niente_da_ripristinare(box: Sandbox) -> None:
    box.flag("no_previous")
    result = box.run(STUB_HEALTH_DEFAULT="unhealthy")
    assert result.code != 0 and "è il primo deploy" in result.out
    assert "docker compose up -d --no-build app" not in result.calls


def test_il_branch_si_puo_cambiare(box: Sandbox) -> None:
    result = box.run(DEPLOY_BRANCH="master")
    assert "git reset --hard origin/master" in result.calls


# --- la forma del file -----------------------------------------------------------------------


def test_lo_script_e_posix_eseguibile_e_ha_la_sintassi_valida() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert os.access(SCRIPT, os.X_OK)
    assert subprocess.run(["sh", "-n", str(SCRIPT)], check=False).returncode == 0
    assert "set -eu" in text.splitlines()
    assert "[[" not in text  # niente bash: sulla VM `sh` è dash


def test_lo_script_puo_essere_riscritto_da_git_mentre_gira() -> None:
    """`git reset --hard` può sostituire questo stesso file durante l'esecuzione: la shell deve aver
    già letto tutto. Per questo `main` è una funzione e l'ultima riga lo lancia e chiude."""
    lines = SCRIPT.read_text(encoding="utf-8").rstrip("\n").splitlines()
    assert lines[-1] == 'main "$@"; exit $?'
    assert any(line.startswith("main()") for line in lines)


def test_l_uid_dei_permessi_e_quello_del_container() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"APP_UID={APP_UID}" in SCRIPT.read_text(encoding="utf-8")
    assert f"USER {APP_UID}:{APP_UID}" in dockerfile


def test_l_immagine_di_alpine_e_fissata_e_il_nome_e_quello_del_compose() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'ALPINE_IMAGE="alpine:3.24.4"' in text  # una versione, non `latest`
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "image: napoli-urban-ops:latest" in compose
    assert 'IMAGE="napoli-urban-ops"' in text


def test_le_variabili_obbligatorie_sono_quelle_di_spec_09_senza_i_tetti_facoltativi() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    declared = next(line for line in text.splitlines() if line.startswith("REQUIRED_VARS="))
    names = declared.split('"')[1].split()
    # DATA_DIR non serve: docker-compose.yml la fissa a /data, dove c'è il volume
    assert set(names) == set(ENV_VALUES) - {"GEMINI_API_KEY", "DATA_DIR"}
