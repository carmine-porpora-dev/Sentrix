import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# <radice del repository> (questo file è backend/app/data/paths.py)
REPO_ROOT = Path(__file__).resolve().parents[3]

GRAPH_FILENAME = "graph_drive.graphml"  # rete stradale OSM (scripts/prepare_osm.py)
FEED_NAME = "anm"  # cartella del feed GTFS estratto (scripts/prepare_gtfs.py)
PMTILES_FILENAME = "napoli.pmtiles"  # mappa di base (scripts/prepare_pmtiles.py)
DATABASE_FILENAME = "napoli.db"  # database SQLite dell'applicazione


def default_data_dir(environ: Mapping[str, str] | None = None) -> Path:
    """`DATA_DIR` se impostata (vuota o di soli spazi = non impostata), altrimenti
    <radice del repository>/data."""
    configured = (os.environ if environ is None else environ).get("DATA_DIR", "").strip()
    return Path(configured) if configured else REPO_ROOT / "data"


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def osm_graph(self) -> Path:
        return self.root / "osm" / GRAPH_FILENAME

    @property
    def gtfs_dir(self) -> Path:
        return self.root / "gtfs"

    @property
    def gtfs_feed(self) -> Path:
        return self.gtfs_dir / FEED_NAME

    @property
    def live_snapshot(self) -> Path:
        """L'ultimo dato LIVE per tratto (08 5): senza chiave, solo se `LIVE_SNAPSHOT_PERSIST`."""
        return self.root / "tomtom" / "snapshot.json"

    @property
    def pmtiles(self) -> Path:
        return self.root / "tiles" / PMTILES_FILENAME

    def present(self) -> dict[str, bool]:
        """Quali dati acquisiti ci sono (gli stessi nomi di `/api/health`): chi li legge e chi li
        prepara (`scripts/bootstrap_data.py`) ne hanno una sola definizione."""
        return {
            "osm": self.osm_graph.is_file(),
            "gtfs": self.gtfs_feed.is_dir(),
            "pmtiles": self.pmtiles.is_file(),
        }

    @property
    def database(self) -> Path:
        return self.root / DATABASE_FILENAME

    @property
    def out_dir(self) -> Path:
        """Dove la riga di comando del motore scrive i risultati (`app.engine.cli`)."""
        return self.root / "out"
