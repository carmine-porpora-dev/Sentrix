import hashlib
import json
import re
from datetime import time
from typing import Annotated, Any, Literal, get_args

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
)

from app.clock import ROME


class FrozenModel(BaseModel):
    """Valore immutabile. Le chiavi sconosciute sono un errore: un refuso non si perde."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def content_hash(self) -> str:
        """sha256 del CONTENUTO (non dei byte di un file): entra in Run.params_hash e nelle chiavi
        delle cache.

        Commenti, ordine delle chiavi e spazi di un file YAML non lo cambiano, quindi una modifica
        solo estetica non invalida la cache LLM (che costa); qualunque valore diverso sì.
        """
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Identificatore leggibile: minuscole, cifre e '_', iniziale lettera (zone, coppie O/D, eventi).
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]

_CLOCK = re.compile(r"\d{2}:\d{2}(:\d{2})?")


def _clock_string(value: Any) -> Any:
    # YAML legge 23:59 senza virgolette come il numero 1439 (base 60) e pydantic lo convertirebbe
    # in silenzio in 00:23:59 UTC; un client JSON può mandare un intero. Solo stringhe "HH:MM[:SS]".
    if not isinstance(value, str) or not _CLOCK.fullmatch(value):
        raise ValueError('serve una stringa "HH:MM" tra virgolette (es. "23:59")')
    return value


# Orario del giorno, senza fuso: "13:30" (o "13:30:00", come lo scrive il JSON).
ClockTime = Annotated[time, BeforeValidator(_clock_string)]

# Istante con fuso obbligatorio, normalizzato a Europe/Rome (dev-rules 4).
RomeDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(ROME))]


# Finestra temporale dell'evento a cui si riferisce un'analisi, una misura o una richiesta.
Window = Literal["arrival", "departure"]
# Le finestre nell'ordine canonico (arrivo, poi deflusso): l'unico elenco, per non riscriverlo.
WINDOWS: tuple[Window, ...] = get_args(Window)

# Dove gira l'applicazione (spech.md 6.7: variabile ENV).
Environment = Literal["local", "production"]

# Come l'applicazione usa l'LLM (spech.md 6.7: variabile LLM_MODE, 05 1): `Run.llm_mode` e
# impostazioni.
LlmMode = Literal["live", "cache_only", "template"]

# La notifica WhatsApp (spech.md 12.4): `WHATSAPP_MODE` (`off` = nessun invio) e il servizio
# `WHATSAPP_PROVIDER` che la recapita.
WhatsAppMode = Literal["off", "live"]
WhatsAppProvider = Literal["callmebot", "meta"]

# Chiave di un arco stradale: "u-v-k" = nodo di partenza, nodo di arrivo, chiave dell'arco parallelo
# (stessa forma di `app.data.resolvers.edge_key`, che la costruisce, e di `parse_edge_key`).
EDGE_KEY_PATTERN = r"\d+-\d+-\d+"

# Parte di un identificatore tecnico: finisce dentro altri id (l'id del run negli id dei
# Measured) e negli URL, quindi niente punti né spazi.
ID_PART = r"[A-Za-z0-9_-]+"
RefId = Annotated[str, StringConstraints(pattern=rf"^{ID_PART}$")]

# sha256 in esadecimale minuscolo (params_hash, input_hash).
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
