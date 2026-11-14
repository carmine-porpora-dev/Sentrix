from typing import ClassVar, Literal

from pydantic import Field

from app.models.yamlconfig import CONFIG_DIR, YamlConfig

MAX_TEMPERATURE = 0.2  # 05 1: «temperature=0 (max 0,2)»


class LlmConfig(YamlConfig):
    DEFAULT_PATH: ClassVar = CONFIG_DIR / "llm.yaml"

    timeout_s: float = Field(gt=0)  # attesa massima di una chiamata
    temperature: float = Field(ge=0, le=MAX_TEMPERATURE)
    retries: int = Field(ge=0, le=3)  # nuovi tentativi per una risposta non conforme
    # Quanto ragiona il modello prima di rispondere (Gemini 3): i token di ragionamento si pagano
    # come output e allungano la chiamata. `None` = lascia il valore del modello.
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = None
    # Tetto ai token della risposta: una risposta troncata è «non valida», non una spesa senza fine.
    max_output_tokens: int | None = Field(default=None, ge=256)
