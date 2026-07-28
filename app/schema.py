"""Modelos de configuración de los "conjuntos" (experimentos) de un proyecto.

Un fichero de encuesta puede contener más de un experimento (p. ej. un
conjoint de elección y una o varias viñetas administradas a submuestras
distintas), así que la unidad de análisis no es "la sesión" sino el
"conjunto": cada uno tiene su propio tipo, su propio filtro de submuestra
opcional y su propio mapeo, y varios conjuntos conviven en la misma sesión.

- `ConjointMappingConfig`: experimento de elección. Una tarea (p. ej. "cj3")
  enfrenta a dos o más perfiles (p. ej. "A"/"B"); cada perfil se describe con
  los mismos atributos, cada uno en una columna distinta del fichero ancho.
  `AttributeMapping.columns` asocia, para ese atributo, cada combinación
  (tarea, perfil) con el nombre de columna de origen.
- `VignetteMappingConfig`: experimento de viñeta. A diferencia del conjoint,
  no hay perfiles enfrentados: cada entrevistado ve un único perfil/estímulo
  (a menudo aleatorizado entre versiones) y lo valora en una variable de
  resultado continua o de escala. Como cada fila del fichero ancho ya es una
  observación completa, no hace falta reestructurar a formato largo.
"""
from typing import Literal

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


class VignetteAttributeMapping(BaseModel):
    name: str = Field(min_length=1)
    label: str = ""
    column: str = Field(min_length=1)  # una sola columna: no hay perfil A/B que enfrentar

    @field_validator("label")
    @classmethod
    def default_label(cls, v: str, info):
        return v or info.data.get("name", "")


class VignetteMappingConfig(BaseModel):
    respondent_id: str | None = None
    outcome_column: str = Field(min_length=1)
    outcome_label: str = ""
    attributes: list[VignetteAttributeMapping] = Field(min_length=1)

    def attribute_names(self) -> list[str]:
        return [a.name for a in self.attributes]


class AmceRequest(BaseModel):
    method: str = Field(default="ols", pattern="^(ols|clogit)$")
    attributes: list[str] | None = None  # None = todos los mapeados
    baselines: dict[str, str] = Field(default_factory=dict)  # categoría de referencia por atributo


class VignetteEstimateRequest(BaseModel):
    attributes: list[str] | None = None  # None = todos los mapeados
    baselines: dict[str, str] = Field(default_factory=dict)


class SampleFilter(BaseModel):
    """Restringe un conjunto a las filas donde `column` vale uno de `values`
    (p. ej. `EXPERIMENTO` = 1, para aislar un experimento de los otros dos que
    comparten el mismo fichero)."""
    column: str = Field(min_length=1)
    values: list[str] = Field(min_length=1)


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1)
    kind: Literal["conjoint", "vignette"] = "conjoint"
    sample_filter: SampleFilter | None = None


class ExperimentUpdate(BaseModel):
    name: str | None = None
    sample_filter: SampleFilter | None = None
    clear_sample_filter: bool = False


class ExperimentDuplicate(BaseModel):
    name: str = Field(min_length=1)
