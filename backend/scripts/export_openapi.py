import argparse
import json
import sys

from app.data.paths import REPO_ROOT
from app.main import app
from scripts.common import atomic_write_text

OPENAPI_PATH = REPO_ROOT / "docs" / "spec" / "openapi.json"


def render() -> str:
    """Il contratto come testo: stesso contenuto, stesso testo (indentato, UTF-8, a capo finale)."""
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--check", action="store_true", help="non scrive: verifica che sia aggiornato"
    )
    args = parser.parse_args(argv)
    text = render()
    current = OPENAPI_PATH.read_text(encoding="utf-8") if OPENAPI_PATH.is_file() else None
    if args.check:
        if current != text:
            print(
                f"{OPENAPI_PATH} non è aggiornato: esegui "
                "`uv run python -m scripts.export_openapi`",
                file=sys.stderr,
            )
            return 1
        print(f"{OPENAPI_PATH}: aggiornato")
        return 0
    if current == text:
        print(f"{OPENAPI_PATH}: già aggiornato")
        return 0
    atomic_write_text(OPENAPI_PATH, text)
    print(f"{OPENAPI_PATH}: scritto ({len(app.openapi()['paths'])} percorsi)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
