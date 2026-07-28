import pandas as pd

from app.readers import _fix_mojibake, _fix_mojibake_column, _fix_mojibake_dataframe


def test_fix_mojibake_repairs_double_encoded_utf8():
    """Regresión: los .dta con formato < 118 no declaran codificación y pandas
    asume latin-1 (`StataReader._set_encoding`), pero el fichero real de
    prueba contiene texto en UTF-8. "uÃ±as" es "uñas" cuyos bytes UTF-8
    (0xC3 0xB1) se decodificaron como si fueran dos caracteres latin-1.
    """
    assert _fix_mojibake("uÃ±as") == "uñas"
    assert _fix_mojibake("Es voluntario/a en actos contra el cÃ¡ncer") == (
        "Es voluntario/a en actos contra el cáncer"
    )
    assert _fix_mojibake("Escucha mÃºsica electrÃ³nica") == "Escucha música electrónica"


def test_fix_mojibake_leaves_correctly_decoded_text_untouched():
    """Si el texto ya está bien (o no es "arreglable" reinterpretándolo como
    UTF-8), no debe tocarse: solo se corrige cuando el reintento de
    decodificación produce UTF-8 válido, la señal de que hubo doble
    decodificación.
    """
    assert _fix_mojibake("uñas") == "uñas"
    assert _fix_mojibake("Hombre") == "Hombre"
    assert _fix_mojibake("") == ""


def test_fix_mojibake_column_categorical():
    series = pd.Series(pd.Categorical(["uÃ±as", "Le gusta leer", "uÃ±as"]))
    fixed = _fix_mojibake_column(series)
    assert list(fixed) == ["uñas", "Le gusta leer", "uñas"]
    assert isinstance(fixed.dtype, pd.CategoricalDtype)


def test_fix_mojibake_column_object_dtype():
    series = pd.Series(["cÃ¡ncer", None, "mÃºsica"], dtype=object)
    fixed = _fix_mojibake_column(series)
    assert fixed.tolist() == ["cáncer", None, "música"]


def test_fix_mojibake_dataframe_only_touches_string_columns():
    df = pd.DataFrame({
        "texto": pd.Categorical(["uÃ±as", "Le gusta leer"]),
        "edad": [40, 41],
    })
    fixed = _fix_mojibake_dataframe(df)
    assert list(fixed["texto"]) == ["uñas", "Le gusta leer"]
    assert fixed["edad"].tolist() == [40, 41]
