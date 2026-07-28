"""Lectura de bases de datos del estudio en xlsx, CSV, Stata (.dta) y SPSS (.sav).

Stata y SPSS traen metadatos propios (etiqueta descriptiva por variable y
etiquetas de valor por categoría) que xlsx/csv no tienen. Los conservamos
siempre que existan: la etiqueta de variable se usa en la interfaz en lugar
del nombre técnico de columna, y las etiquetas de valor se aplican para que
las categóricas lleguen ya legibles (p. ej. 1/2 -> "Hombre"/"Mujer").
"""
import csv as csv_module
import io
import os
import tempfile

import pandas as pd
import pyreadstat

SUPPORTED_EXTENSIONS = (".xlsx", ".xls", ".dta", ".sav", ".csv")


def _fix_mojibake(text: str) -> str:
    """Repara texto UTF-8 que se decodificó como si fuera latin-1.

    Los ficheros .dta con formato < 118 (Stata < 15) no declaran su propia
    codificación y pandas asume latin-1 por defecto (`StataReader._set_encoding`),
    pero en la práctica muchos de estos ficheros —sobre todo si se generaron o
    reexportaron con herramientas no-Stata— contienen texto en UTF-8. El
    resultado son acentos corruptos tipo "uÃ±as" en vez de "uñas".

    Solo se corrige si el reintento de decodificación como UTF-8 tiene éxito:
    como latin-1 nunca falla al decodificar, ese es justo el caso donde el
    texto original ya iba en UTF-8 y pandas lo decodificó mal; si no es UTF-8
    válido, se asume que el texto ya estaba bien y se deja tal cual.
    """
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def _fix_mojibake_column(series: pd.Series) -> pd.Series:
    if isinstance(series.dtype, pd.CategoricalDtype):
        fixed_categories = [_fix_mojibake(str(c)) for c in series.cat.categories]
        if fixed_categories == list(series.cat.categories.astype(str)):
            return series
        if len(set(fixed_categories)) != len(fixed_categories):
            return series  # dos categorías distintas colapsarían en una: no tocar
        return series.cat.rename_categories(fixed_categories)
    if series.dtype == object:
        return series.map(lambda v: _fix_mojibake(v) if isinstance(v, str) else v)
    return series


def _fix_mojibake_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if isinstance(df[col].dtype, pd.CategoricalDtype) or df[col].dtype == object:
            df[col] = _fix_mojibake_column(df[col])
    return df


def _dedupe_value_labels(mapping: dict[float, str]) -> dict[float, str]:
    """Si dos códigos comparten el mismo texto de etiqueta, pandas no puede
    construir un Categorical porque las categorías deben ser únicas.
    Distinguimos las repetidas añadiendo el código entre paréntesis.
    """
    text_counts: dict[str, int] = {}
    for text in mapping.values():
        text_counts[text] = text_counts.get(text, 0) + 1
    return {
        code: (f"{text} ({code:g})" if text_counts[text] > 1 else text)
        for code, text in mapping.items()
    }


def _apply_stata_value_labels(df: pd.DataFrame, value_labels_by_var: dict[str, dict[float, str]]) -> pd.DataFrame:
    """Aplica a mano las etiquetas de valor de Stata cuando pandas no puede
    hacerlo automáticamente (etiquetas repetidas dentro del mismo conjunto).
    Los códigos sin etiqueta conocida conservan su valor numérico original.
    """
    for col, mapping in value_labels_by_var.items():
        if col not in df.columns or not mapping:
            continue
        safe_mapping = _dedupe_value_labels(mapping)
        code_by_text = {text: code for code, text in safe_mapping.items()}
        mapped = df[col].map(lambda v: safe_mapping.get(v, v))
        cat = pd.Categorical(mapped)

        def sort_key(value, code_by_text=code_by_text):
            if value in code_by_text:
                return (0, code_by_text[value])
            try:
                return (0, float(value))
            except (TypeError, ValueError):
                return (1, str(value))

        df[col] = cat.reorder_categories(sorted(cat.categories, key=sort_key))
    return df


def _read_stata(buf: io.BytesIO) -> tuple[pd.DataFrame, dict[str, str]]:
    reader = pd.io.stata.StataReader(buf)
    try:
        df = reader.read(convert_categoricals=True)
    except ValueError as e:
        if "are not unique" not in str(e):
            raise
        buf.seek(0)
        reader = pd.io.stata.StataReader(buf)
        df = reader.read(convert_categoricals=False)
        value_labels_by_set = reader.value_labels()
        col_to_labelset = dict(zip(df.columns, getattr(reader, "_lbllist", [])))
        value_labels_by_var = {
            col: value_labels_by_set[labelset]
            for col, labelset in col_to_labelset.items()
            if labelset in value_labels_by_set
        }
        df = _apply_stata_value_labels(df, value_labels_by_var)
    df = _fix_mojibake_dataframe(df)
    raw_labels = reader.variable_labels()
    labels = {col: _fix_mojibake(raw_labels.get(col) or str(col)) for col in df.columns}
    return df, labels


def _read_spss(content: bytes) -> tuple[pd.DataFrame, dict[str, str]]:
    # pyreadstat necesita una ruta de archivo real, no acepta un buffer en memoria.
    fd, tmp_path = tempfile.mkstemp(suffix=".sav")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(content)
        # formats_as_ordered_category=True conserva el orden original de los
        # códigos de valor; sin este flag pandas reordena alfabéticamente.
        df, meta = pyreadstat.read_sav(
            tmp_path, apply_value_formats=True, formats_as_ordered_category=True
        )
    finally:
        os.unlink(tmp_path)
    raw_labels = dict(zip(meta.column_names, meta.column_labels))
    labels = {col: (raw_labels.get(col) or str(col)) for col in df.columns}
    return df, labels


def _sniff_csv_separator(sample: str) -> str:
    try:
        return csv_module.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv_module.Error:
        return ","


def _read_csv(buf: io.BytesIO) -> tuple[pd.DataFrame, dict[str, str]]:
    raw = buf.read()
    text = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("No se pudo determinar la codificación del archivo CSV.")

    sep = _sniff_csv_separator(text[:4096])
    df = pd.read_csv(io.StringIO(text), sep=sep)
    labels = {col: str(col) for col in df.columns}
    return df, labels


def read_dataset(filename: str, content: bytes) -> tuple[pd.DataFrame, dict[str, str]]:
    """Lee el dataset y devuelve (dataframe, etiquetas descriptivas de variable).

    Stata y SPSS pueden traer una etiqueta descriptiva por variable, distinta
    del nombre técnico de columna (p. ej. columna "cj1_A_gen", etiqueta
    "Perfil A, tarea 1: género"); para xlsx/csv no existe ese concepto, así
    que la etiqueta coincide con el nombre de columna.
    """
    name = filename.lower()
    buf = io.BytesIO(content)

    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(buf)
        labels = {col: str(col) for col in df.columns}
    elif name.endswith(".dta"):
        df, labels = _read_stata(buf)
    elif name.endswith(".sav"):
        df, labels = _read_spss(content)
    elif name.endswith(".csv"):
        df, labels = _read_csv(buf)
    else:
        raise ValueError(
            "Formato no soportado. Sube un archivo .xlsx, .xls, .csv, .dta o .sav."
        )

    df.columns = [str(c) for c in df.columns]
    labels = {str(k): str(v) for k, v in labels.items()}
    return df, labels
