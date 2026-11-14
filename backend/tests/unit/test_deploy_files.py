import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.data.paths import REPO_ROOT
from app.settings import Settings

DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
START = REPO_ROOT / "backend" / "scripts" / "start.sh"
COMPOSE = REPO_ROOT / "docker-compose.yml"
CADDYFILE = REPO_ROOT / "deploy" / "Caddyfile"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy.yml"

# Nomi delle variabili che portano segreti (spech 6.7): nell'immagine non devono comparire.
SECRET_NAMES = ("APP_PASSWORD", "SESSION_SECRET", "GEMINI_API_KEY", "TOMTOM_API_KEY")
APP_UID = "10001"
APP_PORT = "8000"  # la porta del server: start.sh, health check di Compose e Caddyfile la nominano


def instructions(path: Path = DOCKERFILE) -> list[tuple[str, str]]:
    """(ISTRUZIONE, argomenti) del Dockerfile, con le righe continuate con `\\` riunite."""
    text = re.sub(r"\\\n", " ", path.read_text(encoding="utf-8"))
    found: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keyword, _, args = line.partition(" ")
            found.append((keyword.upper(), args.strip()))
    return found


def of_kind(keyword: str) -> list[str]:
    return [args for kind, args in instructions() if kind == keyword]


# --- Dockerfile ------------------------------------------------------------------------------


def test_ogni_immagine_di_base_ha_una_versione_fissata() -> None:
    images = [args.split()[0] for args in of_kind("FROM")]
    copied = [
        args.split()[0].removeprefix("--from=")
        for args in of_kind("COPY")
        if args.startswith("--from=") and "/" in args.split()[0]
    ]
    assert len(images) == 2  # stadio dell'interfaccia e stadio del backend
    for image in images + copied:
        _, _, tag = image.rpartition(":")
        assert ":" in image and tag not in ("latest", ""), image


def test_nessun_segreto_nell_immagine() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    for name in SECRET_NAMES:
        assert name not in text, f"{name} nel Dockerfile"
    assert not [args for kind, args in instructions() if kind == "ARG"]  # nulla a build time
    for args in of_kind("COPY") + of_kind("ADD"):
        assert not re.search(r"(^|[\s/])\.env\b", args), args


def test_il_contesto_di_build_esclude_segreti_e_dati() -> None:
    patterns = [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    for required in (".env", ".env.*", "!.env.example", "/data/", ".git/", "**/node_modules/"):
        assert required in patterns, required


def test_il_server_gira_senza_privilegi_con_uid_fisso() -> None:
    assert of_kind("USER") == [f"{APP_UID}:{APP_UID}"]
    create = " ".join(of_kind("RUN"))
    assert f"groupadd --gid {APP_UID}" in create
    assert f"useradd --uid {APP_UID} --gid {APP_UID}" in create
    # /data deve appartenere a quell'utente: il volume vuoto è scrivibile al primo avvio
    assert "chown app:app /data" in create
    # si diventa l'utente solo dopo averlo creato (e dopo aver installato le dipendenze come root)
    kinds = [kind for kind, _ in instructions()]
    last_run = len(kinds) - 1 - kinds[::-1].index("RUN")
    assert kinds.index("USER") > last_run


def test_dipendenze_esattamente_come_nel_lock_e_solo_di_produzione() -> None:
    assert "uv sync --frozen --no-dev" in " ".join(of_kind("RUN"))
    assert "npm ci" in " ".join(of_kind("RUN"))
    assert "DATA_DIR=/data" in " ".join(of_kind("ENV"))


def test_le_cartelle_copiate_esistono() -> None:
    for args in of_kind("COPY"):
        if args.startswith("--from="):
            continue
        *sources, _destination = args.split()
        for source in sources:
            assert (REPO_ROOT / source).exists(), f"COPY {source}: non esiste"


def test_il_comando_avvia_start_sh_e_il_file_c_e() -> None:
    assert of_kind("CMD") == ['["sh", "scripts/start.sh"]']
    assert START.is_file()


# --- scripts/start.sh ------------------------------------------------------------------------


def test_start_sh_e_eseguibile_e_la_sintassi_e_valida() -> None:
    assert os.access(START, os.X_OK)
    sh = shutil.which("sh")
    assert sh is not None
    assert subprocess.run([sh, "-n", str(START)], check=False).returncode == 0


def test_start_sh_lancia_un_solo_server_e_si_ferma_a_sigterm() -> None:
    lines = [
        line.strip()
        for line in START.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "set -eu" in lines
    # exec: il server è il processo 1 del container e riceve SIGTERM
    assert lines[-1] == "exec uvicorn app.main:app --host 0.0.0.0 --port 8000"
    assert not any("--workers" in line or "--reload" in line for line in lines)


def test_start_sh_prepara_i_dati_in_background_e_il_server_parte_subito() -> None:
    lines = [
        line.strip()
        for line in START.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    bootstrap = [i for i, line in enumerate(lines) if "scripts.bootstrap_data" in line]
    assert len(bootstrap) == 1
    assert bootstrap[0] < len(lines) - 1  # lanciato prima dell'exec del server...
    # ...ma con `&`: una rete che non risponde (osmnx resta fermo a lungo) non ritarda il server
    assert lines[bootstrap[0]] == "python -m scripts.bootstrap_data &"


@pytest.mark.parametrize("name", SECRET_NAMES)
def test_start_sh_non_nomina_i_segreti(name: str) -> None:
    assert name not in START.read_text(encoding="utf-8")


# --- docker-compose.yml e Caddyfile ----------------------------------------------------------


def compose_services() -> dict[str, dict[str, object]]:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    assert isinstance(services, dict)
    return services


def test_compose_ha_solo_app_e_caddy() -> None:
    assert set(compose_services()) == {"app", "caddy"}


def test_l_app_non_e_raggiungibile_da_fuori_e_ha_le_chiavi_solo_lei() -> None:
    app, caddy = compose_services()["app"], compose_services()["caddy"]
    assert "ports" not in app  # la porta del server non è pubblicata: ci arriva solo Caddy
    assert app["env_file"] == ".env"
    assert "env_file" not in caddy  # Caddy non vede chiavi né password
    assert set(caddy["environment"]) == {"DOMAIN"}  # type: ignore[call-overload]
    text = COMPOSE.read_text(encoding="utf-8")
    for name in SECRET_NAMES:
        assert name not in text, f"{name} in docker-compose.yml"


def test_i_dati_della_vm_sono_montati_in_data_e_il_server_ha_un_init() -> None:
    app = compose_services()["app"]
    assert app["volumes"] == ["${DATA_HOST_DIR:-/data}:/data"]  # sulla VM: /data
    assert app["init"] is True  # raccoglie lo script dei dati avviato in background
    # i dati stanno nel volume anche con un DATA_DIR vuoto o sbagliato nel .env (env_file)
    # e l'accesso è libero (regola dell'hackathon, 14/11/2026) salvo `PUBLIC_ACCESS=false` nel .env
    assert app["environment"] == {"DATA_DIR": "/data", "PUBLIC_ACCESS": "${PUBLIC_ACCESS:-true}"}
    assert app["image"] == "napoli-urban-ops:latest"  # il nome che deploy.sh ritagga `previous`
    assert (REPO_ROOT / "Dockerfile").is_file() and app["build"] == {"context": "."}


def test_i_servizi_ripartono_da_soli_dopo_un_riavvio_della_vm() -> None:
    for name, service in compose_services().items():
        assert service["restart"] == "unless-stopped", name


def test_il_health_check_interroga_la_porta_del_server() -> None:
    check = compose_services()["app"]["healthcheck"]
    assert f"127.0.0.1:{APP_PORT}/api/health" in " ".join(check["test"])  # type: ignore[index]
    assert f"--port {APP_PORT}" in START.read_text(encoding="utf-8")


def test_caddy_ha_https_un_tag_fisso_e_i_certificati_in_volumi() -> None:
    caddy = compose_services()["caddy"]
    _, _, tag = str(caddy["image"]).rpartition(":")
    assert tag not in ("", "latest") and tag[0].isdigit()
    assert caddy["ports"] == ["80:80", "443:443"]
    assert caddy["depends_on"] == ["app"]
    assert "./deploy/Caddyfile:/etc/caddy/Caddyfile:ro" in caddy["volumes"]  # type: ignore[operator]
    assert {"caddy_data:/data", "caddy_config:/config"} <= set(caddy["volumes"])  # type: ignore[call-overload]
    declared = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["volumes"]
    assert set(declared) == {"caddy_data", "caddy_config"}
    assert CADDYFILE.is_file()


def test_il_caddyfile_serve_il_dominio_e_inoltra_all_app() -> None:
    lines = [
        line.strip()
        for line in CADDYFILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines == [
        "{$DOMAIN} {",
        "encode zstd gzip",
        f"reverse_proxy app:{APP_PORT}",
        "}",
    ]


# --- .github/workflows/deploy.yml ------------------------------------------------------------


def workflow() -> dict[object, object]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def workflow_jobs() -> dict[str, dict[str, object]]:
    return workflow()["jobs"]  # type: ignore[return-value]


def test_il_workflow_parte_al_push_sul_ramo_principale_e_a_mano() -> None:
    triggers = workflow()[True]  # PyYAML legge la chiave `on` come True
    assert triggers["push"] == {"branches": ["main"]}  # type: ignore[index]
    assert "workflow_dispatch" in triggers  # type: ignore[operator]


def test_il_deploy_aspetta_i_test_ed_e_uno_alla_volta() -> None:
    assert set(workflow_jobs()) == {"test", "deploy"}
    assert workflow_jobs()["deploy"]["needs"] == "test"
    assert workflow()["concurrency"] == {"group": "deploy", "cancel-in-progress": False}
    assert workflow()["permissions"] == {"contents": "read"}


def test_i_test_del_workflow_sono_la_suite_veloce_e_la_build_dell_interfaccia() -> None:
    steps = workflow_jobs()["test"]["steps"]
    commands = " ".join(str(step.get("run", "")) for step in steps)  # type: ignore[attr-defined]
    assert "uv sync --frozen" in commands and "uv run pytest" in commands
    assert "npm ci" in commands and "npm run build" in commands
    # niente `-m` qui: quali test sono «veloci» lo dice addopts in pyproject.toml, in un posto solo
    assert "-m " not in commands


def test_le_azioni_sono_fissate_al_commit_di_una_versione() -> None:
    uses = re.findall(r"uses:\s*(\S+)", WORKFLOW.read_text(encoding="utf-8"))
    assert len(uses) == 3  # checkout, uv, node
    for action in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", action), action


def test_da_github_passano_solo_i_tre_secret_della_vm() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"VM_HOST", "VM_USER", "VM_SSH_KEY"}
    for name in SECRET_NAMES:
        assert name not in text, f"{name} nel workflow"


def test_i_secret_arrivano_ai_comandi_solo_dall_ambiente() -> None:
    """`${{ secrets.X }}` in un `run:` finirebbe nel testo dello script (iniezione di comandi)."""
    for job in workflow_jobs().values():
        for step in job["steps"]:  # type: ignore[attr-defined]
            assert "secrets." not in str(step.get("run", ""))


def test_il_deploy_lancia_lo_script_sulla_vm_dal_clone_del_repository() -> None:
    steps = workflow_jobs()["deploy"]["steps"]
    commands = " ".join(str(step.get("run", "")) for step in steps)  # type: ignore[attr-defined]
    assert '"$VM_USER@$VM_HOST"' in commands
    assert "$HOME/napoli-urban-ops/deploy/deploy.sh" in commands  # il clone della guida (B2)
    assert "chmod 600 ~/.ssh/deploy_key" in commands


def test_il_workflow_usa_le_stesse_versioni_dell_immagine() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    text = WORKFLOW.read_text(encoding="utf-8")
    uv = re.search(r"ghcr.io/astral-sh/uv:([\d.]+)", dockerfile)
    node = re.search(r"FROM node:(\d+)\.", dockerfile)
    assert uv and node
    assert f'version: "{uv.group(1)}"' in text
    assert f"node-version: {node.group(1)}" in text


# --- .env.example ----------------------------------------------------------------------------


def env_example_names() -> set[str]:
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    return {line.partition("=")[0] for line in lines if "=" in line and not line.startswith("#")}


def test_env_example_ha_le_variabili_che_il_compose_e_il_deploy_si_aspettano() -> None:
    names = env_example_names()
    compose = COMPOSE.read_text(encoding="utf-8")
    used = set(re.findall(r"\$\{(\w+)", compose))  # DOMAIN, DATA_HOST_DIR, PUBLIC_ACCESS
    assert used == {"DOMAIN", "DATA_HOST_DIR", "PUBLIC_ACCESS"}
    assert used <= names
    script = (REPO_ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    declared = next(line for line in script.splitlines() if line.startswith("REQUIRED_VARS="))
    assert set(declared.split('"')[1].split()) <= names


def test_env_example_non_ha_valori() -> None:
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            assert line.partition("=")[2] == "", line  # nessun valore, nessun segreto


def test_i_dati_del_container_provato_in_locale_non_vanno_in_git_ne_nel_contesto() -> None:
    for name in (".gitignore", ".dockerignore"):
        assert "/data-docker/" in (REPO_ROOT / name).read_text(encoding="utf-8").splitlines()


def test_sulla_vm_l_accesso_e_libero_e_si_torna_alla_password_con_una_riga() -> None:
    """Regola dell'hackathon (14/11/2026): tutto pubblico. Acceso di default nel compose, spento
    di default nell'applicazione (locale e test), documentato in `.env.example`."""
    app = compose_services()["app"]
    assert app["environment"]["PUBLIC_ACCESS"] == "${PUBLIC_ACCESS:-true}"  # type: ignore[index]
    assert "PUBLIC_ACCESS" in env_example_names()
    assert Settings.from_env({}).public_access is False
