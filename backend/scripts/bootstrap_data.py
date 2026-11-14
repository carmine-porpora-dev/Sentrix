import argparse
import sys
import traceback
from collections.abc import Callable, Mapping
from pathlib import Path

from app.data.paths import DataPaths
from scripts import prepare_gtfs, prepare_osm, prepare_pmtiles
from scripts.common import add_data_dir_arg, default_data_dir

Step = Callable[[list[str]], int]  # il `main(argv)` di uno script dati

# Un passo per ogni chiave di `DataPaths.present()`, nell'ordine in cui compaiono in `/api/health`.
STEPS: Mapping[str, Step] = {
    "osm": prepare_osm.main,
    "gtfs": prepare_gtfs.main,
    "pmtiles": prepare_pmtiles.main,
}


def _say(message: str) -> None:
    print(f"[bootstrap_data] {message}", flush=True)


def bootstrap(data_dir: Path, steps: Mapping[str, Step] = STEPS) -> dict[str, bool]:
    """Lancia lo script di ogni dato assente e dice, alla fine, quali dati ci sono. Non solleva:
    un passo che fallisce (eccezione, `SystemExit` o dato ancora assente) viene scritto nel log e
    gli altri proseguono."""
    paths = DataPaths(data_dir)
    for name, step in steps.items():
        if paths.present()[name]:
            _say(f"{name}: presente, niente da fare")
            continue
        _say(f"{name}: assente, lo preparo (può volerci qualche minuto)")
        try:
            code = step(["--data-dir", str(data_dir)])
        except (Exception, SystemExit):  # un solo passo fallito non ferma gli altri
            _say(f"{name}: NON riuscito\n{traceback.format_exc().rstrip()}")
            continue
        if not paths.present()[name]:
            _say(f"{name}: NON riuscito (lo script è uscito con {code} e il dato non c'è)")
        else:
            _say(f"{name}: pronto")
    present = paths.present()
    missing = [name for name, ok in present.items() if not ok]
    if missing:
        _say(
            f"mancano: {', '.join(missing)}. L'applicazione parte lo stesso, in modo degradato "
            "(/api/health lo dice). Riavvia per riprovare, oppure copia i file in " + str(data_dir)
        )
    return present


def main(argv: list[str] | None = None, steps: Mapping[str, Step] = STEPS) -> int:
    parser = argparse.ArgumentParser(description="Prepara i dati mancanti di DATA_DIR.")
    add_data_dir_arg(parser)
    args = parser.parse_args(argv)
    present = bootstrap(args.data_dir or default_data_dir(), steps)
    return 0 if all(present.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
