from pathlib import Path
from typing import Any, ClassVar, Self

import yaml

from app.models.base import FrozenModel

# <radice del repository>/config (backend/app/models/yamlconfig.py -> parents[3]).
CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader che rifiuta le chiavi duplicate (PyYAML terrebbe in silenzio l'ultima)."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"chiave duplicata '{key}'", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


class YamlConfig(FrozenModel):
    """Un modello che si carica da un file YAML. Chi eredita imposta `DEFAULT_PATH`."""

    DEFAULT_PATH: ClassVar[Path]

    @classmethod
    def from_yaml_text(cls, text: str) -> Self:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 (è un SafeLoader)
        if not isinstance(data, dict):
            raise ValueError(
                f"{cls.DEFAULT_PATH.name}: il documento deve essere una mappa di sezioni"
            )
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> Self:
        """Carica e valida il file (default: quello del repository in `config/`)."""
        return cls.from_yaml_text((path or cls.DEFAULT_PATH).read_text(encoding="utf-8"))
