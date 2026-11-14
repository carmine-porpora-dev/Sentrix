import os
from pathlib import Path

import pytest

from app.data.paths import DATABASE_FILENAME, REPO_ROOT, DataPaths, default_data_dir
from app.settings import Settings, SettingsError, load_env_file


def test_senza_variabili_valgono_i_default() -> None:
    settings = Settings.from_env({})
    assert settings.env == "local"
    assert settings.data_dir == REPO_ROOT / "data"
    assert settings.app_password is None and settings.session_secret is None
    assert not settings.auth_configured
    assert not settings.secure_cookies
    assert (settings.tomtom_key_present, settings.gemini_key_present) == (False, False)


def test_variabili_impostate() -> None:
    settings = Settings.from_env(
        {
            "ENV": "production",
            "DATA_DIR": "/data",
            "APP_PASSWORD": "fake-pw",
            "SESSION_SECRET": "fake-secret",
            "TOMTOM_API_KEY": "fake-tomtom",
            "GEMINI_API_KEY": "fake-gemini",
        }
    )
    assert settings.env == "production" and settings.secure_cookies
    assert settings.data_dir == Path("/data")
    assert (settings.app_password, settings.session_secret) == ("fake-pw", "fake-secret")
    assert settings.auth_configured
    assert (settings.tomtom_key_present, settings.gemini_key_present) == (True, True)


@pytest.mark.parametrize("blank", ["", " ", "   \t"])
def test_valore_vuoto_o_solo_spazi_equivale_a_non_impostato(blank: str) -> None:
    settings = Settings.from_env(
        {
            "ENV": blank,
            "DATA_DIR": blank,
            "APP_PASSWORD": blank,
            "SESSION_SECRET": blank,
            "TOMTOM_API_KEY": blank,
            "GEMINI_API_KEY": blank,
        }
    )
    assert settings == Settings.from_env({})


@pytest.mark.parametrize("env", [{"APP_PASSWORD": "fake-pw"}, {"SESSION_SECRET": "fake-secret"}])
def test_senza_password_o_senza_segreto_l_accesso_e_chiuso(env: dict[str, str]) -> None:
    assert not Settings.from_env(env).auth_configured


@pytest.mark.parametrize("value", ["prod", "Production", "dev", "1", "localx"])
def test_env_non_ammesso_e_un_errore(value: str) -> None:
    with pytest.raises(SettingsError, match=value):
        Settings.from_env({"ENV": value})


def test_i_segreti_non_compaiono_nel_repr() -> None:
    settings = Settings.from_env(
        {
            "APP_PASSWORD": "fake-pw-visibile?",
            "SESSION_SECRET": "fake-secret-visibile?",
            "TOMTOM_API_KEY": "fake-tomtom-visibile?",
        }
    )
    text = f"{settings!r} {settings}"
    for secret in ("fake-pw-visibile", "fake-secret-visibile", "fake-tomtom-visibile"):
        assert secret not in text


def test_le_chiavi_di_tomtom_e_gemini_non_sono_conservate() -> None:
    settings = Settings.from_env({"TOMTOM_API_KEY": "fake-tomtom", "GEMINI_API_KEY": "fake-g"})
    assert "fake-tomtom" not in repr(vars(settings)) and "fake-g" not in repr(vars(settings))


def test_load_env_file_non_sovrascrive_l_ambiente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FAKE_ALREADY=dal-file\nFAKE_NEW=dal-file\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_ALREADY", "dall-ambiente")
    monkeypatch.delenv("FAKE_NEW", raising=False)
    load_env_file(env_file)
    assert os.environ["FAKE_ALREADY"] == "dall-ambiente"
    assert os.environ["FAKE_NEW"] == "dal-file"
    monkeypatch.delenv("FAKE_NEW")
    load_env_file(tmp_path / "manca.env")  # file assente: nessun errore


# --- percorsi dei dati -----------------------------------------------------------------------


def test_default_data_dir() -> None:
    assert default_data_dir({}) == REPO_ROOT / "data"
    assert default_data_dir({"DATA_DIR": ""}) == REPO_ROOT / "data"
    assert default_data_dir({"DATA_DIR": "  "}) == REPO_ROOT / "data"
    assert default_data_dir({"DATA_DIR": "/data"}) == Path("/data")
    assert (REPO_ROOT / "config" / "engine.yaml").is_file()  # REPO_ROOT è davvero la radice


def test_layout_dei_dati() -> None:
    paths = DataPaths(Path("/d"))
    assert paths.osm_graph == Path("/d/osm/graph_drive.graphml")
    assert paths.gtfs_dir == Path("/d/gtfs")
    assert paths.gtfs_feed == Path("/d/gtfs/anm")
    assert paths.pmtiles == Path("/d/tiles/napoli.pmtiles")
    assert paths.database == Path("/d/napoli.db") and DATABASE_FILENAME == "napoli.db"
    assert paths.out_dir == Path("/d/out")


# --- accesso libero (`PUBLIC_ACCESS`, hackathon 14/11/2026) ---------------------------------------


def test_l_accesso_libero_e_spento_di_default() -> None:
    """In locale e nei test l'accesso resta protetto: si accende, non si eredita per distrazione."""
    assert Settings.from_env({}).public_access is False
    assert Settings.from_env({"PUBLIC_ACCESS": ""}).public_access is False
    assert Settings(env="local", data_dir=Path("/x")).public_access is False


@pytest.mark.parametrize(("value", "expected"), [("true", True), ("TRUE", True), ("false", False)])
def test_public_access_si_legge_dall_ambiente(value: str, expected: bool) -> None:
    assert Settings.from_env({"PUBLIC_ACCESS": value}).public_access is expected


@pytest.mark.parametrize("value", ["1", "yes", "si", "on"])
def test_public_access_non_ammesso_e_un_errore(value: str) -> None:
    """Un refuso non apre l'accesso in silenzio né lo chiude: si ferma e lo dice."""
    with pytest.raises(SettingsError, match="PUBLIC_ACCESS"):
        Settings.from_env({"PUBLIC_ACCESS": value})


def test_l_accesso_libero_non_dipende_dalla_password() -> None:
    settings = Settings.from_env({"PUBLIC_ACCESS": "true"})
    assert settings.public_access and not settings.auth_configured


# --- WhatsApp (spech.md 12.4) --------------------------------------------------------------------

WHATSAPP_ENV = {
    "WHATSAPP_MODE": "live",
    "WHATSAPP_PROVIDER": "callmebot",
    "WHATSAPP_TO": "+393331234512",
    "CALLMEBOT_APIKEY": "ck-fake-7391846",
}


def test_whatsapp_di_default_e_spento_con_callmebot_e_venti_messaggi_al_giorno() -> None:
    whatsapp = Settings.from_env({}).whatsapp
    assert (whatsapp.mode, whatsapp.provider, whatsapp.daily_limit) == ("off", "callmebot", 20)
    assert not whatsapp.configured and whatsapp.missing() == ["WHATSAPP_TO", "CALLMEBOT_APIKEY"]


def test_whatsapp_con_tutto_impostato_e_configurato() -> None:
    whatsapp = Settings.from_env({**WHATSAPP_ENV, "WHATSAPP_DAILY_LIMIT": "5"}).whatsapp
    assert whatsapp.configured and whatsapp.missing() == [] and whatsapp.daily_limit == 5
    assert (whatsapp.to, whatsapp.callmebot_apikey) == ("+393331234512", "ck-fake-7391846")


def test_whatsapp_configurato_vuole_l_invio_acceso_e_le_chiavi_del_servizio_scelto() -> None:
    assert not Settings.from_env({**WHATSAPP_ENV, "WHATSAPP_MODE": "off"}).whatsapp.configured
    assert not Settings.from_env({**WHATSAPP_ENV, "CALLMEBOT_APIKEY": ""}).whatsapp.configured
    # le chiavi di CallMeBot non servono a Meta
    meta = Settings.from_env({**WHATSAPP_ENV, "WHATSAPP_PROVIDER": "meta"}).whatsapp
    assert not meta.configured and meta.missing() == [
        "WHATSAPP_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_API_VERSION",
    ]
    full = {
        **WHATSAPP_ENV,
        "WHATSAPP_PROVIDER": "meta",
        "WHATSAPP_TOKEN": "t",
        "WHATSAPP_PHONE_NUMBER_ID": "1",
        "WHATSAPP_API_VERSION": "v21.0",
    }
    assert Settings.from_env(full).whatsapp.configured  # il modello è facoltativo


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WHATSAPP_MODE", "on"),
        ("WHATSAPP_MODE", "Live"),
        ("WHATSAPP_PROVIDER", "twilio"),
        ("WHATSAPP_DAILY_LIMIT", "venti"),
        ("WHATSAPP_DAILY_LIMIT", "-1"),
    ],
)
def test_whatsapp_valori_non_ammessi(name: str, value: str) -> None:
    with pytest.raises(SettingsError, match=name):
        Settings.from_env({name: value})


@pytest.mark.parametrize("name", [*WHATSAPP_ENV, "WHATSAPP_DAILY_LIMIT", "WHATSAPP_TOKEN"])
def test_whatsapp_valore_vuoto_equivale_a_non_impostato(name: str) -> None:
    assert Settings.from_env({name: "  "}) == Settings.from_env({})


def test_il_repr_delle_impostazioni_non_mostra_numero_ne_chiavi() -> None:
    secrets = {
        **WHATSAPP_ENV,
        "WHATSAPP_TOKEN": "tok-fake-0987654",
        "WHATSAPP_PHONE_NUMBER_ID": "104567890",
        "WHATSAPP_API_VERSION": "v21.0",
        "WHATSAPP_TEMPLATE": "modello_fake",
    }
    settings = Settings.from_env(secrets)
    for text in (repr(settings), str(settings), repr(settings.whatsapp), f"{settings.whatsapp}"):
        for secret in ("393331234512", "ck-fake-7391846", "tok-fake-0987654", "104567890"):
            assert secret not in text
        assert "modello_fake" not in text
