from app.engine import unique
from app.engine.result import EngineResult
from app.engine.run import RoadResult
from app.engine.transit_run import TransitResult


def test_unique_toglie_i_doppioni_e_tiene_l_ordine_di_prima_comparsa() -> None:
    assert unique("b", "a", "b", "c", "a") == ("b", "a", "c")
    assert unique() == ()
    assert isinstance(unique("x"), tuple)


def test_strada_e_trasporto_condividono_i_campi_comuni_nello_stesso_ordine() -> None:
    common = ["event_id", "level", "window", "applied"]
    assert list(EngineResult.model_fields) == common
    for result in (RoadResult, TransitResult):
        assert issubclass(result, EngineResult)
        assert list(result.model_fields) == [*common, "metrics"]
