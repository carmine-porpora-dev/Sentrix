from pathlib import Path

import networkx as nx
import osmnx as ox

# Convenzione del file: un attributo assente è semplicemente assente dall'arco (GraphML non ha
# None).
EDGE_DTYPES: dict[str, type] = {"length_m": float, "lanes": int, "maxspeed_kmh": int}


def load_osm_graph(path: Path) -> nx.MultiDiGraph:
    """Il grafo `drive` con `length_m` float e `lanes`/`maxspeed_kmh` interi dove presenti."""
    return ox.load_graphml(path, edge_dtypes=EDGE_DTYPES)
