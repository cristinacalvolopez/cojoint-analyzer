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
- `ExternalDesignMappingConfig`: conjoint de elección cuyo diseño (qué
  atributos vio cada perfil en cada tarea) no está incrustado en el fichero
  de respuestas, sino en un fichero de diseño/plan de bloques aparte,
  generado por la herramienta que aleatorizó el experimento. Hay que
  cruzarlo con las respuestas por una o varias claves (p. ej. la versión
  aleatoria asignada a cada entrevistado, y a veces también un bloque
  geográfico o demográfico) antes de poder calcular el AMCE.
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


class DesignJoinKey(BaseModel):
    """Une el fichero de respuestas con el de diseño por una variable de
    contexto (p. ej. la comunidad autónoma, cuando el diseño reparte bloques
    distintos por región). `value_map` traduce cada valor observado en la
    columna del entrevistado al valor correspondiente en el fichero de
    diseño (p. ej. "Comunitat Valenciana" -> "País Valencià"); los valores no
    traducidos explícitamente caen en `default_design_value` si se indica
    (p. ej. "Resto CCAA"), o se usan tal cual si `value_map` está vacío.
    """
    design_column: str = Field(min_length=1)
    respondent_column: str = Field(min_length=1)
    value_map: dict[str, str] = Field(default_factory=dict)
    default_design_value: str | None = None


class ExternalDesignAttributeMapping(BaseModel):
    name: str = Field(min_length=1)
    label: str = ""
    design_column: str = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def default_label(cls, v: str, info):
        return v or info.data.get("name", "")


class ExternalDesignMappingConfig(BaseModel):
    respondent_id: str | None = None
    tasks: list[str] = Field(min_length=1)
    profiles: list[str] = Field(min_length=2)
    design_task_column: str = Field(min_length=1)
    design_profile_column: str = Field(min_length=1)
    choice_columns: dict[str, str] = Field(default_factory=dict)  # {task: columna de elección del entrevistado}
    choice_value_map: dict[str, str] = Field(default_factory=dict)  # valor crudo -> id de perfil
    join_keys: list[DesignJoinKey] = Field(default_factory=list)
    attributes: list[ExternalDesignAttributeMapping] = Field(min_length=1)

    def attribute_names(self) -> list[str]:
        return [a.name for a in self.attributes]


class RecodeRequest(BaseModel):
    """Crea una nueva columna dicotómica derivada de una columna numérica
    existente (p. ej. "grave" = 1 si `EXP2_P2` >= 8, si no 0), disponible
    después en cualquier selector de columnas de la sesión."""
    source_column: str = Field(min_length=1)
    new_column: str = Field(min_length=1)
    new_label: str = ""
    operator: Literal[">=", ">", "<=", "<", "=="] = ">="
    threshold: float
    true_label: str = "Sí"
    false_label: str = "No"


class TableExportRequest(BaseModel):
    """Exporta a un fichero descargable cualquier tabla que ya esté en
    pantalla (coeficientes del AMCE, resultados por batería...), sin tener
    que volver a calcular nada en el servidor: el propio cliente manda las
    filas ya construidas."""
    rows: list[dict] = Field(min_length=1)
    filename: str = Field(min_length=1, default="tabla")
    format: Literal["xlsx", "csv"] = "xlsx"


class CrosstabRequest(BaseModel):
    """Tabla cruzada de cada una de `outcome_columns` por cada atributo ya
    mapeado en el conjunto de viñeta (no hace falta re-mapear nada)."""
    outcome_columns: list[str] = Field(min_length=1)


class BatteryEstimateRequest(BaseModel):
    """Repite la regresión de una viñeta (resultado ~ atributos) para cada
    una de varias variables de resultado a la vez: pensado para experimentos
    donde no hay una única variable dependiente, sino una batería de
    preguntas (a menudo escalas Likert) sobre el mismo estímulo ya mapeado.
    Las columnas que no se puedan tratar como escala numérica se omiten
    (ver `skipped` en la respuesta) en vez de abortar toda la batería."""
    outcome_columns: list[str] = Field(min_length=1)
    attributes: list[str] | None = None  # None = todos los mapeados
    baselines: dict[str, str] = Field(default_factory=dict)


class MultiResponseItem(BaseModel):
    column: str = Field(min_length=1)
    label: str = ""
    selected_value: str | None = None


class MultiResponseRequest(BaseModel):
    items: list[MultiResponseItem] = Field(min_length=1)
    group_attribute: str | None = None  # nombre del atributo ya mapeado para desglosar, si se quiere


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
    kind: Literal["conjoint", "vignette", "conjoint_design"] = "conjoint"
    sample_filter: SampleFilter | None = None


class ExperimentUpdate(BaseModel):
    name: str | None = None
    sample_filter: SampleFilter | None = None
    clear_sample_filter: bool = False


class ExperimentDuplicate(BaseModel):
    name: str = Field(min_length=1)
