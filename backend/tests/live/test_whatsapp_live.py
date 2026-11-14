from dataclasses import replace
from datetime import date

import pytest

from app.clock import now_rome
from app.notifications.templates import advisory_text, mask_phone
from app.notifications.whatsapp_client import WhatsAppError, build_client
from app.settings import Settings, load_env_file

pytestmark = pytest.mark.live


async def test_un_messaggio_vero_arriva_al_numero_configurato() -> None:
    load_env_file()
    whatsapp = Settings.from_env().whatsapp
    if whatsapp.missing():
        pytest.skip(f"servono nel .env: {', '.join(whatsapp.missing())}")
    stamp = now_rome().strftime("%H:%M:%S")
    text = advisory_text(
        event_name=f"PROVA di invio ({stamp}), nessuna chiusura reale",
        event_date=date.today(),
        closed_roads=["Via di prova uno", "Via di prova due"],
        transit_disruptions=["Linea di prova interrotta"],
        notice="Questo è un messaggio di prova del test live: non c'è nessun evento.",
    )
    print(f"\nInvio a {mask_phone(whatsapp.to or '')} con {whatsapp.provider}")
    try:
        result = await build_client(replace(whatsapp, mode="live")).send(text)
    except WhatsAppError as error:  # il motivo è già ripulito: numero e chiave non ci sono
        pytest.fail(f"messaggio non inviato ({error.code}): {error.detail}")
    print(f"Inviato; id del servizio: {result.message_id or '(il servizio non ne dà)'}")
