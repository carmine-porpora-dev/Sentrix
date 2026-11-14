import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.data.paths import REPO_ROOT
from app.data.seeds import read_seed_events
from app.models.catalog import CatalogConfig
from app.models.config import EngineConfig
from app.models.departments import DepartmentsConfig
from app.models.event import Event
from app.models.live_config import LiveConfig
from app.models.live_segments import LiveSegmentsConfig
from scripts import export_api_fixtures as export
from scripts.export_api_fixtures import MANIFEST, OUTPUT_DIR, build, validate

OPENAPI = json.loads((REPO_ROOT / "docs" / "spec" / "openapi.json").read_text(encoding="utf-8"))
MANIFEST_DATA: dict[str, Any] = json.loads((OUTPUT_DIR / MANIFEST).read_text(encoding="utf-8"))
# Dove sta lo studio: ogni coordinata del mock deve cadere qui (bbox del grafo, F0-05).
WEST, SOUTH, EAST, NORTH = 14.14, 40.80, 14.30, 40.90


def load(path: str) -> Any:
    return json.loads((OUTPUT_DIR / path).read_text(encoding="utf-8"))


def all_json() -> dict[str, Any]:
    return {p: load(p) for p in MANIFEST_DATA["files"] if p.endswith(".json")}


def walk(value: Any) -> Any:
    """Ogni dizionario annidato in un documento JSON."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def measured_in(value: Any) -> list[dict[str, Any]]:
    keys = {"id", "value", "unit", "kind", "source", "method", "inputs", "assumptions", "as_of"}
    return [d for d in walk(value) if set(d) == keys]


def metric_value(iteration: int, suffix: str) -> float:
    metrics = load(f"run_metrics/iteration_{iteration}.json")["metrics"]
    (found,) = [m for m in metrics if m["id"].endswith(suffix)]
    return found["value"]


# --- generazione e modelli ---------------------------------------------------------------------


def test_i_file_salvati_sono_aggiornati(capsys: pytest.CaptureFixture[str]) -> None:
    """Se questo fallisce: `cd backend && uv run python -m scripts.export_api_fixtures`."""
    assert export.main(["--check"]) == 0, capsys.readouterr().err


def test_la_generazione_e_deterministica() -> None:
    first, second = build(), build()
    assert {p: f.text for p, f in first.items()} == {p: f.text for p, f in second.items()}


def test_ogni_file_salvato_valida_con_il_suo_modello() -> None:
    assert validate(OUTPUT_DIR) == []


def test_nessun_file_orfano_e_nessuno_mancante() -> None:
    on_disk = {str(p.relative_to(OUTPUT_DIR)) for p in OUTPUT_DIR.rglob("*") if p.is_file()}
    assert on_disk == set(MANIFEST_DATA["files"]) | {MANIFEST}


def test_la_validazione_si_accorge_di_un_file_rotto(tmp_path: Path) -> None:
    for path, fixture in build().items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(fixture.text, encoding="utf-8")
    assert validate(tmp_path) == []
    broken = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    broken["status"] = "forse"
    (tmp_path / "health.json").write_text(json.dumps(broken), encoding="utf-8")
    (tmp_path / "run_created.json").unlink()
    problems = validate(tmp_path)
    assert any(p.startswith("health.json: HealthResponse") for p in problems)
    assert "run_created.json: manca" in problems


def test_i_modelli_rifiutano_un_valore_non_valido_anche_se_una_copia() -> None:
    """Le fixture si rivalidano dal JSON: un `model_copy` non può far passare uno stato assurdo."""
    world = export.World()
    broken = world.run_view(77).run.model_copy(update={"state": "ERROR", "error": None})
    with pytest.raises(Exception, match="error"):
        export._json("RunView", world.run_view(77).model_copy(update={"run": broken}))


# --- contratto OpenAPI -------------------------------------------------------------------------


def schema_name(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[1]
    if schema.get("type") == "array":
        return f"list[{schema_name(schema['items'])}]"
    raise AssertionError(schema)


def operations() -> dict[str, dict[str, Any]]:
    return {
        op["operationId"]: op for methods in OPENAPI["paths"].values() for op in methods.values()
    }


def test_ogni_operazione_ha_le_sue_fixture() -> None:
    assert len(operations()) == 29
    for operation_id, operation in operations().items():
        entries = MANIFEST_DATA["operations"].get(operation_id, [])
        if operation_id == "pmtiles":
            assert entries == []  # è un file binario: si serve quello vero
            assert "pmtiles" in MANIFEST_DATA["binary"]
            continue
        successes = [code for code in operation["responses"] if code.startswith("2")]
        assert {str(e["status"]) for e in entries} >= set(successes), operation_id


def test_stato_e_schema_di_ogni_fixture_sono_quelli_dell_openapi() -> None:
    for operation_id, entries in MANIFEST_DATA["operations"].items():
        responses = operations()[operation_id]["responses"]
        for entry in entries:
            declared = responses[str(entry["status"])]
            allowed = {
                "text/csv" if media == "text/csv" else schema_name(body["schema"])
                for media, body in declared["content"].items()
            }
            assert entry["schema"] in allowed, (operation_id, entry)


def test_ogni_errore_del_contratto_ha_un_esempio() -> None:
    declared = {
        int(code)
        for operation in operations().values()
        for code in operation["responses"]
        if int(code) >= 400
    }
    assert declared <= {int(code) for code in MANIFEST_DATA["errors"]}
    assert "500" in MANIFEST_DATA["errors"]  # non nel contratto, ma l'interfaccia deve gestirlo
    for status, path in MANIFEST_DATA["errors"].items():
        document = load(path)
        assert set(document["error"]) == {"code", "message", "details"}
        assert path.startswith(f"errors/{status}_")


# --- provenienza: di esempio, dichiarato -------------------------------------------------------


def test_ogni_numero_dichiara_di_essere_di_esempio() -> None:
    found = 0
    for path, document in all_json().items():
        for item in measured_in(document):
            found += 1
            if item["id"].endswith(".event.attendance"):
                # l'affluenza dell'Evento non è un valore di esempio: è il dato dell'Evento, scritto
                # dalla stessa funzione del backend vero (`attendance_measured`)
                assert item["source"].startswith("Evento "), (path, item["id"])
                continue
            assert item["source"].startswith("mock.fixture"), (path, item["id"])
            assert any("esempio" in a for a in item["assumptions"]), (path, item["id"])
            assert "esempio" in item["method"], (path, item["id"])
    assert found > 400  # le metriche, i delta e i tratti LIVE sono stati visti davvero


def test_tutti_e_tre_i_tipi_di_dato_sono_rappresentati() -> None:
    kinds = {item["kind"] for doc in all_json().values() for item in measured_in(doc)}
    assert kinds == {"real", "estimate", "simulated"}  # i tre badge dell'interfaccia


def test_gli_id_delle_metriche_sono_unici_in_ogni_risposta() -> None:
    for it in (0, 1, 2):
        ids = [m["id"] for m in load(f"run_metrics/iteration_{it}.json")["metrics"]]
        # 38 metriche del motore; in più l'affluenza dell'Evento (iterazione 0) e l'effetto locale
        # delle misure stradali entrate in vigore (2 numeri per misura: act_001 all'1, act_004 al 2)
        assert len(ids) == len(set(ids)) == 38 + {0: 1, 1: 2, 2: 2}[it]
        assert all(f".it{it}." in i for i in ids)


def test_il_motore_non_e_mai_una_previsione() -> None:
    """Principio 6: nei testi mai «previsione» (né «previsto») riferito al motore."""
    for path in MANIFEST_DATA["files"]:
        text = (OUTPUT_DIR / path).read_text(encoding="utf-8").lower()
        assert not re.search(r"\bprevision|\bprevist", text), path


def test_nessun_indirizzo_esterno() -> None:
    """Principio 3: nessun ente reale come destinatario, nessun host fuori dal progetto."""
    for path in MANIFEST_DATA["files"]:
        text = (OUTPUT_DIR / path).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, path
    for dept in load("vdept_registry.json")["departments"]:
        assert dept["endpoint"] == f"internal://{dept['id']}"


# --- la scena di 04 7 -------------------------------------------------------------------------


def final_view() -> dict[str, Any]:
    return load("run_view/step_13_done.json")


def test_il_run_finale_racconta_il_rifiuto_e_la_ripianificazione() -> None:
    view = final_view()
    run = view["run"]
    assert (run["state"], run["iteration"], run["replans"]) == ("DONE", 2, 1)
    assert run["event_id"] == "match_2027" and run["ended_at"] and run["error"] is None
    plan = {p["seq"]: p for p in view["plan"]}
    assert {s: p["status"] for s, p in plan.items()} == {
        1: "accepted", 2: "replaced", 3: "accepted", 4: "accepted", 5: "accepted", 6: "discarded",
    }  # fmt: skip
    assert plan[2]["replaced_by"] == 4 and plan[2]["action_id"] == "act_002"
    assert plan[6]["note"].startswith("R2:")  # lo scarto in RECONCILE è motivato
    requests = {r["request"]["action_id"]: r for r in view["requests"]}
    rejected = requests["act_002"]["request"]
    assert (rejected["state"], rejected["reject_code"]) == ("REJECTED", "UNAVAILABLE")
    reason = rejected["reject_reason"]
    assert "6 totali, 6 già impegnate" in reason and "21:00–23:00" in reason  # 5 dell'evento + 1
    alternative = requests["act_004"]["request"]
    assert alternative["alternative_of"] == "act_002"
    assert (alternative["type"], alternative["department"], alternative["state"]) == (
        "signal_plan_change", "traffic_control", "ACCEPTED",
    )  # fmt: skip
    assert all(r["request"]["simulation"] is True for r in requests.values())
    assert plan[1]["recommendation"]["measure_type"] == "traffic_post"
    assert plan[1]["recommendation"]["department"] == "municipal_police"


def test_le_iterazioni_migliorano_solo_dove_ci_sono_misure() -> None:
    for suffix in (
        "departure.veh_hours",
        "departure.od_time.mean",
        "departure.critical_edges.count",
        "departure.critical_edges.km",
    ):
        values = [metric_value(it, suffix) for it in (0, 1, 2)]
        assert values[0] > values[1] > values[2], (suffix, values)
    for suffix in ("arrival.veh_hours", "arrival.od_time.mean", "arrival.critical_edges.count"):
        # 05 3: le finestre senza misure copiano i risultati dell'iterazione precedente
        assert len({metric_value(it, suffix) for it in (0, 1, 2)}) == 1, suffix


def test_il_tempo_od_medio_e_la_media_delle_cinque_coppie() -> None:
    pairs = [p.id for p in EngineConfig.from_yaml().demand.od_pairs]
    assert len(pairs) == 5
    for it in (0, 1, 2):
        for window in ("arrival", "departure"):
            times = [metric_value(it, f"{window}.od_time.{pair}") for pair in pairs]
            assert metric_value(it, f"{window}.od_time.mean") == pytest.approx(
                sum(times) / 5, abs=0.06
            )


def test_i_delta_sono_differenze_vere() -> None:
    assert load("run_metrics/iteration_0.json")["deltas"] == []
    for it in (1, 2):
        document = load(f"run_metrics/iteration_{it}.json")
        now = {m["id"].split(f"it{it}.")[1]: m["value"] for m in document["metrics"]}
        previous = {m["id"].split(f"it{it - 1}.")[1]: m["value"]
                    for m in load(f"run_metrics/iteration_{it - 1}.json")["metrics"]}  # fmt: skip
        base = {
            m["id"].split("it0.")[1]: m["value"]
            for m in load("run_metrics/iteration_0.json")["metrics"]
        }
        assert len(document["deltas"]) == 38
        for delta in document["deltas"]:
            tail = delta["metric_id"].split(f"it{it}.")[1]
            assert delta["vs_previous"]["value"] == pytest.approx(
                now[tail] - previous[tail], abs=0.011
            )
            assert delta["vs_baseline"]["value"] == pytest.approx(now[tail] - base[tail], abs=0.011)
            assert delta["vs_previous"]["kind"] in ("simulated", "estimate", "real")


def test_le_evidenze_citate_esistono() -> None:
    known = {
        m["id"] for it in (0, 1, 2) for m in load(f"run_metrics/iteration_{it}.json")["metrics"]
    }
    cited: list[str] = []
    for step in MANIFEST_DATA["run_sequence"]:
        view = load(step["run_view"])
        for agent in view["agents"]:
            for finding in agent["findings"]:
                cited += finding["evidence_ids"]
        for item in view["plan"]:
            cited += item["recommendation"]["evidence_ids"]
        for decision in load(step["decisions"]):
            cited += [r for r in decision["refs"] if r.startswith("m.")]
    assert cited and set(cited) <= known, sorted(set(cited) - known)


def test_i_finding_e_le_misure_vengono_dal_catalogo() -> None:
    catalog, departments = CatalogConfig.from_yaml(), DepartmentsConfig.from_yaml()
    known_departments = {d.id for d in departments.departments}
    view = final_view()
    for agent in view["agents"]:
        for finding in agent["findings"]:
            assert finding["trigger"] in catalog.trigger_ids
    for item in view["plan"]:
        rec = item["recommendation"]
        measure = catalog.measure(rec["measure_type"])
        assert measure is not None and measure.department == rec["department"]
        assert rec["department"] in known_departments
    for entry in view["requests"]:
        request = entry["request"]
        department = departments.department(request["department"])
        assert department is not None and request["type"] in department.request_types


# --- la sequenza dei fotogrammi ----------------------------------------------------------------

ALLOWED = {  # 05 3, scritto a mano
    ("INTAKE", "ANALYZE"), ("ANALYZE", "RECONCILE"), ("RECONCILE", "PLAN"), ("PLAN", "DISPATCH"),
    ("DISPATCH", "AWAIT"), ("AWAIT", "VERIFY"), ("VERIFY", "REPLAN"), ("VERIFY", "DONE"),
    ("REPLAN", "DISPATCH"),
}  # fmt: skip


def test_la_sequenza_rispetta_la_macchina_a_stati() -> None:
    steps = MANIFEST_DATA["run_sequence"]
    states = [s["state"] for s in steps]
    assert states[0] == "INTAKE" and states[-1] == "DONE"
    assert [s["step"] for s in steps] == list(range(len(steps)))
    for before, after in zip(states, states[1:], strict=False):
        assert before == after or (before, after) in ALLOWED, (before, after)
    assert states.count("DISPATCH") == 2 and "REPLAN" in states  # un solo giro di ripianificazione


def test_ogni_fotogramma_e_coerente_e_non_torna_indietro() -> None:
    previous = {"iteration": -1, "replans": -1, "decisions": -1, "requests": -1, "timeline": -1}
    for step in MANIFEST_DATA["run_sequence"]:
        view, decisions = load(step["run_view"]), load(step["decisions"])
        run = view["run"]
        assert view["timeline"][-1]["state"] == run["state"] == step["state"]
        assert [d["seq"] for d in decisions] == list(range(1, len(decisions) + 1))
        now = {
            "iteration": run["iteration"],
            "replans": run["replans"],
            "decisions": len(decisions),
            "requests": len(view["requests"]),
            "timeline": len(view["timeline"]),
        }
        assert all(now[k] >= previous[k] for k in now), (step["step"], now, previous)
        previous = now
        ready = step["iterations_available"]
        assert ready == list(range(len(ready))) and len(ready) <= run["iteration"] + 1
        assert (ready == []) == (run["state"] in ("INTAKE", "ANALYZE"))  # it0 nasce in ANALYZE


def test_le_transizioni_di_ogni_richiesta_sono_valide() -> None:
    entries = final_view()["requests"]
    seen_ids: list[int] = []
    for entry in entries:
        events, request = entry["events"], entry["request"]
        assert events[0]["from_state"] is None and events[0]["to_state"] == "CREATED"
        for before, after in zip(events, events[1:], strict=False):
            assert after["from_state"] == before["to_state"]
            assert after["at"] >= before["at"]
        assert events[-1]["to_state"] == request["state"]
        seen_ids += [e["id"] for e in events]
        assert (request["state"] == "REJECTED") == bool(
            request["reject_code"] and request["reject_reason"]
        )
    assert len(seen_ids) == len(set(seen_ids))  # id unici su tutte le richieste


def test_gli_agenti_attraversano_gli_stati_dell_interfaccia() -> None:
    seen: dict[str, set[str]] = {}
    for step in MANIFEST_DATA["run_sequence"]:
        for agent in load(step["run_view"])["agents"]:
            seen.setdefault(agent["agent"], set()).add(agent["state"])
    assert seen["event_demand"] == {"waiting", "running", "done"}
    assert seen["transit"] == {"waiting", "running", "done_fallback"}  # testo di riserva (07 6)
    assert {"waiting", "running", "done"} <= seen["operations"]
    final = {a["agent"]: a for a in final_view()["agents"]}
    assert final["transit"]["text_origin"] == "template"
    assert all(a["text"] for a in final.values())


# --- varianti per gli stati d'errore ------------------------------------------------------------


def test_varianti_per_gli_stati_da_gestire() -> None:
    human = load("run_view_variant_human_decision.json")
    item = next(p for p in human["plan"] if p["status"] == "human_decision_required")
    assert item["note"] and item["action_id"] == "act_003"
    request = next(r for r in human["requests"] if r["request"]["action_id"] == "act_003")[
        "request"
    ]
    assert (request["state"], request["reject_code"]) == ("REJECTED", "NO_EXTENSION_LEFT")
    failed = load("run_view_variant_error.json")
    assert (
        failed["run"]["state"] == "ERROR" and failed["run"]["error"] and failed["run"]["ended_at"]
    )
    assert any(a["state"] == "error" for a in failed["agents"])
    assert load("run_view_variant_degraded.json")["degraded"] == ["gtfs"]
    assert load("health_degraded.json")["degraded"] == ["osm"]


# --- livelli della mappa -----------------------------------------------------------------------


def positions(geometry: dict[str, Any]) -> list[list[float]]:
    coordinates = geometry["coordinates"]
    if geometry["type"] == "Point":
        return [coordinates]
    if geometry["type"] == "LineString":
        return coordinates
    return coordinates[0]


def test_ogni_geometria_cade_nell_area_di_studio() -> None:
    checked = 0
    for path, document in all_json().items():
        for feature in (d for d in walk(document) if d.get("type") == "Feature"):
            for lon, lat in positions(feature["geometry"]):
                assert WEST <= lon <= EAST and SOUTH <= lat <= NORTH, (path, feature.get("id"))
                checked += 1
    assert checked > 200  # le geometrie sono state viste davvero


def test_i_sette_livelli_per_ogni_iterazione() -> None:
    for it in (0, 1, 2):
        for layer in export.LAYERS:
            document = load(f"run_layers/{layer}_it{it}.json")
            assert document["type"] == "FeatureCollection"
            assert document["features"] or (layer, it) == ("requests", 0)  # nessuna richiesta prima


def test_le_chiusure_sono_quelle_del_seed() -> None:
    seed = next(e for e in read_seed_events() if e.id == "match_2027")
    expected = {k for closure in seed.closures for k in closure.edge_keys}
    in_layer = {
        f["properties"]["edge_key"] for f in load("run_layers/closures_it1.json")["features"]
    }
    assert in_layer == expected == {f["id"] for f in load("event_resolve_preview.json")["features"]
                                    if f["properties"]["kind"] == "closure"}  # fmt: skip
    assert Event.model_validate(load("event_match_2027.json")) == seed


def test_il_layer_degli_archi_e_coerente_con_le_metriche() -> None:
    config = EngineConfig.from_yaml().metrics
    for it in (0, 1, 2):
        features = [f["properties"] for f in load(f"run_layers/edges_vc_it{it}.json")["features"]]
        open_edges = [p for p in features if not p["closed"]]
        critical = [p for p in open_edges if p["vc"] > config.vc_critical_threshold]
        assert metric_value(it, "departure.critical_edges.count") == len(critical)
        assert metric_value(it, "departure.critical_edges.km") == pytest.approx(
            sum(p["length_m"] for p in critical) / 1000, abs=0.05
        )
        for p in features:
            assert p["vc_class"] == sum(1 for limit in config.vc_classes if p["vc"] >= limit)
            assert p["closed"] == (p["vc"] == 0.0)
        intersections = load(f"run_layers/critical_intersections_it{it}.json")["features"]
        for feature in intersections:
            rank = feature["properties"]["rank"]
            assert feature["properties"]["vc"] == metric_value(
                it, f"departure.critical_intersection.{rank}.vc"
            )


def test_i_livelli_cambiano_con_le_misure() -> None:
    def vcs(it: int) -> dict[str, float]:
        features = load(f"run_layers/edges_vc_it{it}.json")["features"]
        return {f["id"]: f["properties"]["vc"] for f in features}

    first, last = vcs(0), vcs(2)
    assert first.keys() == last.keys()
    assert any(last[k] < first[k] for k in first) and not any(last[k] > first[k] for k in first)
    requests = [len(load(f"run_layers/requests_it{it}.json")["features"]) for it in (0, 1, 2)]
    assert requests[0] == 0 < requests[1]


def test_l_area_dell_evento_e_un_poligono_chiuso_attorno_al_centro() -> None:
    seed = next(e for e in read_seed_events() if e.id == "match_2027")
    feature = load("run_layers/event_area_it0.json")["features"][0]
    ring = feature["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) > 8
    lons, lats = [p[0] for p in ring], [p[1] for p in ring]
    assert (min(lons) + max(lons)) / 2 == pytest.approx(seed.area_center.lon, abs=1e-4)
    assert (min(lats) + max(lats)) / 2 == pytest.approx(seed.area_center.lat, abs=1e-4)
    assert feature["properties"]["radius_m"] == seed.area_radius_m


# --- esportazione ------------------------------------------------------------------------------


def test_i_csv_hanno_le_colonne_della_spec_e_i_dati_del_run() -> None:
    metrics = list(
        csv.reader(io.StringIO((OUTPUT_DIR / "run_export_metrics.csv").read_text("utf-8")))
    )
    assert metrics[0] == [
        "iteration",
        "metric_id",
        "value",
        "unit",
        "kind",
        "source",
        "method",
        "as_of",
    ]
    assert (
        len(metrics) - 1 == 3 * 38 + 1 + 2 + 2
    )  # affluenza (it 0), effetti delle misure (it 1, 2)
    known = {
        m["id"]: m for it in (0, 1, 2) for m in load(f"run_metrics/iteration_{it}.json")["metrics"]
    }
    for row in metrics[1:]:
        assert row[1] in known and float(row[2]) == known[row[1]]["value"]
        # l'affluenza è dell'Evento, non un valore di esempio (come nel backend vero)
        assert row[5].startswith(
            "Evento " if row[1].endswith(".event.attendance") else "mock.fixture"
        )
    edges = list(
        csv.reader(io.StringIO((OUTPUT_DIR / "run_export_critical_edges.csv").read_text("utf-8")))
    )
    assert edges[0] == ["iteration", "edge_key", "name", "vc", "length_m"]
    expected = sum(metric_value(it, "departure.critical_edges.count") for it in (0, 1, 2))
    assert len(edges) - 1 == expected


def test_l_esportazione_json_contiene_tutto_il_run_con_la_provenienza() -> None:
    package = load("run_export.json")
    assert set(package) == {"event", "run", "plan", "requests", "decisions", "metrics"}
    assert [m["iteration"] for m in package["metrics"]] == [0, 1, 2]
    assert package["event"]["revision"] == package["run"]["event_revision"]
    assert package["run"] == final_view()["run"] and len(package["decisions"]) == 28
    for iteration in package["metrics"]:
        assert all(m["source"] and m["method"] and m["inputs"] for m in iteration["metrics"])


# --- dipartimenti, eventi, LIVE ----------------------------------------------------------------


def test_le_risorse_tornano_con_l_evento() -> None:
    seed = next(e for e in read_seed_events() if e.id == "match_2027")
    rows = load("vdept_registry.json")["resources"]
    assert len(rows) == 8
    for row in rows:
        assert row["remaining"] == row["total"] - row["used"] >= 0
    departure = next(r for r in seed.resources if r.window == "departure")
    police = next(r for r in rows if r["window"] == "departure" and r["resource"] == "patrols")
    assert police["total"] == departure.municipal_police_patrols_total
    # 04 7: 6 totali − 5 impegnate = 1 libera, usata dal primo presidio → ne restano 0
    assert (police["used"], police["remaining"]) == (
        departure.municipal_police_patrols_committed + 1,
        0,
    )


def test_gli_eventi_sono_i_preset_veri() -> None:
    seeds = read_seed_events()
    assert [e["id"] for e in load("events_list.json")] == [e.id for e in seeds]
    for seed in seeds:
        assert Event.model_validate(load(f"event_{seed.id}.json")) == seed
    assert load("event_created.json")["revision"] == 1
    assert load("event_updated.json")["revision"] == 2
    assert load("event_updated.json")["created_at"] == load("event_created.json")["created_at"]


def test_live_ha_i_quindici_tratti_e_le_quattro_modalita() -> None:
    ids = [s.id for s in LiveSegmentsConfig.from_yaml().segments]
    assert len(ids) == 14
    fresh = load("live_flow_fresh.json")
    assert [s["id"] for s in fresh["segments"]] == ids and fresh["mode"] == "fresh"
    for segment in fresh["segments"]:
        current, free = segment["current_speed"], segment["free_flow_speed"]
        assert (current["kind"], free["kind"], segment["ratio"]["kind"]) == (
            "real",
            "real",
            "estimate",
        )
        assert segment["ratio"]["value"] == pytest.approx(
            current["value"] / free["value"], abs=0.01
        )
    assert load("live_flow_cached.json")["mode"] == "cached"
    snapshot = load("live_flow_snapshot.json")
    assert snapshot["mode"] == "snapshot" and snapshot["degraded_reason"] == "tomtom_unreachable"
    assert snapshot["segments"][0]["fetched_at"] < fresh["segments"][0]["fetched_at"]
    assert load("live_flow_unavailable.json") == {
        "segments": [], "mode": "unavailable", "degraded_reason": "tomtom_key_missing",
        "summary": [],
    }  # fmt: skip
    # la classe di ogni tratto e il riepilogo vengono dalle funzioni vere del backend
    classes = LiveConfig.from_yaml().flow.ratio_classes
    for segment in fresh["segments"]:
        assert segment["congestion_class"] == sum(
            1 for limit in classes if segment["ratio"]["value"] < limit
        )
    assert {s["congestion_class"] for s in fresh["segments"]} == {
        0,
        1,
        2,
    }  # scorrevoli e due classi
    summary = {m["id"].rsplit(".", 1)[1]: m for m in fresh["summary"]}
    assert set(summary) == {
        "mean_speed", "mean_ratio", "slowed_count", "slowest_speed", "covered_count",
    }  # fmt: skip
    assert summary["covered_count"]["value"] == 14
    assert summary["slowed_count"]["value"] == sum(
        1 for s in fresh["segments"] if s["congestion_class"] >= 1
    )
    assert summary["slowest_speed"]["value"] == min(
        s["current_speed"]["value"] for s in fresh["segments"]
    )


# --- lo script ---------------------------------------------------------------------------------


def test_lo_script_scrive_verifica_e_toglie_solo_i_propri_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "fixtures"
    assert export.main(["--check", "--output", str(target)]) == 1  # non c'è niente
    assert not target.exists()  # --check non scrive
    assert export.main(["--output", str(target)]) == 0
    assert "tutti validi" in capsys.readouterr().out
    assert export.main(["--check", "--output", str(target)]) == 0
    assert export.main(["--output", str(target)]) == 0  # seconda volta: 0 file scritti
    assert "(0 scritti)" in capsys.readouterr().out
    # un file dell'utente non fa mai «non aggiornato»; uno generato in passato e rimasto sì
    (target / "mio.txt").write_text("miei appunti", encoding="utf-8")
    assert export.main(["--check", "--output", str(target)]) == 0
    old = {**json.loads((target / MANIFEST).read_text("utf-8"))}
    old["files"]["vecchio.json"] = "AuthState"
    (target / MANIFEST).write_text(json.dumps(old), encoding="utf-8")
    (target / "vecchio.json").write_text("{}", encoding="utf-8")
    capsys.readouterr()
    assert export.main(["--check", "--output", str(target)]) == 1
    assert "vecchio.json" in capsys.readouterr().err  # …e --check non lo toglie
    assert (target / "vecchio.json").exists()
    assert export.main(["--output", str(target)]) == 0  # la scrittura sì, e solo quello
    assert not (target / "vecchio.json").exists() and (target / "mio.txt").exists()
    (target / "health.json").write_text("{}", encoding="utf-8")
    assert export.main(["--check", "--output", str(target)]) == 1
    assert "health.json" in capsys.readouterr().err


def test_un_manifest_illeggibile_non_ferma_lo_script(tmp_path: Path) -> None:
    target = tmp_path / "fixtures"
    target.mkdir()
    (target / MANIFEST).write_text("non è json", encoding="utf-8")
    (target / "mio.bin").write_bytes(b"\xff\xfe")  # nemmeno testo: non si legge
    assert export.main(["--output", str(target)]) == 0
    assert (target / "mio.bin").read_bytes() == b"\xff\xfe"


# --- la scelta dell'evento è dai dati, non dal nome (principio 4) ------------------------------


def test_la_scena_usa_l_evento_con_una_sola_pattuglia_libera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import fixture_world

    seeds = read_seed_events()
    chosen = fixture_world.scene_event()
    free = {e.id: fixture_world.free_patrols(e, "departure") for e in seeds}
    assert free[chosen.id] == 1 and sum(1 for v in free.values() if v == 1) == 1
    assert fixture_world.World().run_id == f"run_mock_{chosen.id}"
    # due candidati, o nessuno: la scena non è più univoca e la generazione si ferma
    monkeypatch.setattr(fixture_world, "read_seed_events", lambda: [chosen, chosen])
    with pytest.raises(AssertionError):
        fixture_world.scene_event()
    other = next(e for e in seeds if e.id != chosen.id)
    monkeypatch.setattr(fixture_world, "read_seed_events", lambda: [other])
    with pytest.raises(AssertionError):
        fixture_world.scene_event()


def test_un_arco_chiuso_senza_geometria_ferma_la_generazione(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import fixture_world

    scene = fixture_world.scene_event()
    extra = scene.closures[0].model_copy(update={"edge_keys": ["1-2-0"]})
    broken = scene.model_copy(update={"closures": [*scene.closures, extra]})
    monkeypatch.setattr(fixture_world, "read_seed_events", lambda: [broken])
    with pytest.raises(AssertionError, match=r"manca la geometria schematica.*1-2-0"):
        fixture_world.World()
