# Ogni grandezza del motore la dichiara tra le assunzioni (principio 6): un solo testo.
STATIC_MODEL_ASSUMPTION = "modello macroscopico statico non calibrato, non una previsione"


def unique(*items: str) -> tuple[str, ...]:
    """Le voci senza doppioni, nell'ordine di prima comparsa (assunzioni e input dei `Measured`)."""
    return tuple(dict.fromkeys(items))
