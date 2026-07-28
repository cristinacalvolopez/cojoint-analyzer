import pandas as pd

from app.mapping import infer_choice_value_map, suggest_mapping


def test_choice_column_prefers_eleccion_over_elige_when_both_present():
    """Regresión: un cuestionario real tenía a la vez `cj1_elige` (metadato de
    diseño, valores "Referencia (no LGTBI+)"/"Perfil variable") y
    `cj1_eleccion` (la letra de perfil elegida de verdad, "Perfil A"/"Perfil
    B"). Ambas casan con el patrón de columna de elección; debe ganar
    `cj1_eleccion`, no la primera que aparezca en el fichero.
    """
    columns = [
        "id",
        "cj1_A_rol", "cj1_B_rol",
        "cj1_elige",     # aparece antes en el fichero, pero no debe ganar
        "cj1_eleccion",
        "cj2_A_rol", "cj2_B_rol",
        "cj2_eleccion",
        "cj2_elige",     # aquí aparece después, tampoco debe ganar
    ]
    suggestion = suggest_mapping(columns)
    assert suggestion["choice_columns"]["cj1"] == "cj1_eleccion"
    assert suggestion["choice_columns"]["cj2"] == "cj2_eleccion"
    # las columnas de menor prioridad no deben colarse como "sin clasificar"
    assert "cj1_elige" not in suggestion["unmatched_columns"]
    assert "cj2_elige" not in suggestion["unmatched_columns"]


def test_choice_column_falls_back_to_elige_when_eleccion_absent():
    columns = ["id", "cj1_A_rol", "cj1_B_rol", "cj1_elige"]
    suggestion = suggest_mapping(columns)
    assert suggestion["choice_columns"]["cj1"] == "cj1_elige"


def test_suggest_mapping_without_df_keeps_identity_choice_map():
    """Sin `df` (solo nombres de columna) se mantiene el comportamiento
    anterior: no hay datos que inspeccionar, así que no se puede inferir
    nada mejor que la identidad perfil -> perfil.
    """
    columns = ["id", "cj1_A_rol", "cj1_B_rol", "cj1_eleccion"]
    suggestion = suggest_mapping(columns)
    assert suggestion["choice_columns"]["cj1"] == "cj1_eleccion"
    assert suggestion["choice_value_map"] == {"A": "A", "B": "B"}


def test_infer_choice_value_map_matches_stata_style_labels():
    """Regresión del bug real: Stata convierte la columna de elección a la
    etiqueta de valor completa ("Perfil A"/"Perfil B"), no al id de perfil
    pelado ("A"/"B"). Con el mapeo identidad anterior, el 100% de las
    elecciones quedaban sin traducir y el AMCE fallaba. "NS/NC" debe quedar
    fuera del mapeo (es no-respuesta, no un perfil).
    """
    df = pd.DataFrame({
        "cj1_eleccion": ["Perfil A", "Perfil B", "NS/NC", "Perfil A"],
    })
    value_map, unmapped = infer_choice_value_map(df, {"cj1": "cj1_eleccion"}, ["A", "B"])
    assert value_map == {"Perfil A": "A", "Perfil B": "B"}
    assert unmapped == []


def test_infer_choice_value_map_falls_back_to_position_when_no_letter_match():
    """Algunos cuestionarios (p. ej. exportados de herramientas de encuestas
    online) codifican la elección como "Candidato/a 1"/"Candidato/a 2" en vez
    de por letra de perfil; en ese caso no hay ninguna "A"/"B" literal que
    encontrar, así que se recurre a la posición marcada por el número final.
    """
    df = pd.DataFrame({
        "exp_1": ["Candidato/a 1", "Candidato/a 2", "Candidato/a 1"],
    })
    value_map, unmapped = infer_choice_value_map(df, {"exp": "exp_1"}, ["A", "B"])
    assert value_map == {"Candidato/a 1": "A", "Candidato/a 2": "B"}
    assert unmapped == []


def test_infer_choice_value_map_leaves_ambiguous_values_unmapped():
    """Si de verdad no hay ninguna pista fiable (ni coincidencia literal, ni
    token suelto, ni un número al final que ordenar), el detector no debe
    adivinar a ciegas: mejor dejarlo sin mapear que asignar mal un perfil.
    """
    df = pd.DataFrame({"cj1_eleccion": ["si", "no"]})
    value_map, unmapped = infer_choice_value_map(df, {"cj1": "cj1_eleccion"}, ["A", "B"])
    assert value_map == {}
    assert unmapped == ["no", "si"]


def test_suggest_mapping_with_df_infers_real_choice_values():
    columns = ["id", "cj1_A_rol", "cj1_B_rol", "cj1_eleccion"]
    df = pd.DataFrame({
        "id": ["r1", "r2", "r3"],
        "cj1_A_rol": ["policia", "medico", "policia"],
        "cj1_B_rol": ["medico", "policia", "medico"],
        "cj1_eleccion": ["Perfil A", "Perfil B", "Perfil A"],
    })
    suggestion = suggest_mapping(columns, df)
    assert suggestion["choice_value_map"] == {"Perfil A": "A", "Perfil B": "B"}
    assert suggestion["unmatched_choice_values"] == []
