"""Exportación del fichero reestructurado (o de los datos mapeados de una
viñeta) a los formatos habituales de análisis estadístico, no solo a la
vista previa en pantalla: quien analiza el conjunto suele necesitar el
fichero completo en Excel, SPSS o Stata para seguir trabajando con él fuera
de esta herramienta.
"""
import io
import os
import tempfile

import pandas as pd
import pyreadstat

SUPPORTED_EXPORT_FORMATS = ("csv", "xlsx", "sav", "dta")

_CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "sav": "application/octet-stream",
    "dta": "application/octet-stream",
}


def export_dataframe(df: pd.DataFrame, fmt: str) -> tuple[bytes, str]:
    """Devuelve (contenido en bytes, content-type) para el formato pedido.

    Los escritores de SPSS/Stata (`pyreadstat`) solo aceptan una ruta de
    fichero real, no un buffer en memoria, así que se escribe a un temporal
    y se lee de vuelta — el mismo patrón que ya usa `readers._read_spss`
    para la lectura.
    """
    if fmt not in SUPPORTED_EXPORT_FORMATS:
        raise ValueError(
            f'Formato de exportación no soportado: "{fmt}". Usa uno de: {", ".join(SUPPORTED_EXPORT_FORMATS)}.'
        )

    if fmt == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return buf.getvalue().encode("utf-8-sig"), _CONTENT_TYPES[fmt]

    if fmt == "xlsx":
        buf = io.BytesIO()
        # Excel no admite más de 31 caracteres en el nombre de la hoja ni
        # ciertas columnas con más de ~16k caracteres; para este uso (datos
        # tabulares normales) el valor por defecto de pandas es suficiente.
        df.to_excel(buf, index=False, sheet_name="datos")
        return buf.getvalue(), _CONTENT_TYPES[fmt]

    fd, tmp_path = tempfile.mkstemp(suffix=f".{fmt}")
    try:
        os.close(fd)
        if fmt == "sav":
            pyreadstat.write_sav(df, tmp_path)
        else:
            pyreadstat.write_dta(df, tmp_path)
        with open(tmp_path, "rb") as f:
            content = f.read()
    finally:
        os.unlink(tmp_path)
    return content, _CONTENT_TYPES[fmt]
