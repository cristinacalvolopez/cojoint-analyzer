"""Modelos de la configuración de mapeo wide -> long del experimento conjoint.

Una tarea de elección (p. ej. "cj3") enfrenta a dos o más perfiles (p. ej.
"A"/"B"). Cada perfil se describe con los mismos atributos (rol, género,
edad, orientación, rasgos aleatorios...), cada uno almacenado en una columna
distinta del fichero ancho. `AttributeMapping.columns` asocia, para ese
atributo, cada combinación (tarea, perfil) con el nombre de columna de origen.
"""
from pydantic import BaseModel, Field, field_validator


class AttributeMapping(BaseModel):
    name: str = Field(min_length=1)
    label: str = ""
    # columns[task][profile] = nombre de columna en el fichero ancho
    columns: dict[str, dict[str, str]] = Field(default_factory=dict)

    @field_validator("label")
    @classmethod
    def default_label(cls, v: str, info):
        return v or info.data.get("name", "")


class ConjointMappingConfig(BaseModel):
    respondent_id: str | None = None  # columna identificadora; None = índice de fila
    tasks: list[str] = Field(min_length=1)
    profiles: list[str] = Field(min_length=2)
    attributes: list[AttributeMapping] = Field(min_length=1)
    choice_columns: dict[str, str] = Field(default_factory=dict)  # {task: columna de elección}
    # Traduce el valor crudo de la columna de elección al id de perfil elegido,
    # p. ej. {"1": "A", "2": "B"} o {"A": "A", "B": "B"}.
    choice_value_map: dict[str, str] = Field(default_factory=dict)

    def attribute_names(self) -> list[str]:
        return [a.name for a in self.attributes]


class AmceRequest(BaseModel):
    method: str = Field(default="ols", pattern="^(ols|clogit)$")
    attributes: list[str] | None = None  # None = todos los mapeados
    baselines: dict[str, str] = Field(default_factory=dict)  # categoría de referencia por atributo
