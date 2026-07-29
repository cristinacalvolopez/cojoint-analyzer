import pandas as pd

from app.mapping import classify_unmapped_choice_values, infer_choice_value_map, suggest_mapping, validate_config
from app.schema import AttributeMapping, ConjointMappingConfig


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


def _config_with_choice(choice_value_map):
    return ConjointMappingConfig(
        tasks=["cj1"],
        profiles=["A", "B"],
        attributes=[AttributeMapping(name="rol", columns={"cj1": {"A": "cj1_A_rol", "B": "cj1_B_rol"}})],
        choice_columns={"cj1": "cj1_eleccion"},
        choice_value_map=choice_value_map,
    )


def test_classify_unmapped_choice_values_separates_non_response_from_real_problem():
    """Regresión: el resumen de la reestructuración mostraba "313 conjuntos
    sin perfil elegido" sin decir por qué, dando a entender un fallo de mapeo
    incluso cuando la única causa era "NS/NC" (no respuesta genuina). Esta
    clasificación es lo que permite a la interfaz distinguir ambos casos.
    """
    df = pd.DataFrame({
        "cj1_eleccion": ["Perfil A", "Perfil B", "NS/NC", "algo_raro"],
        "cj1_A_rol": ["policia"] * 4,
        "cj1_B_rol": ["medico"] * 4,
    })
    config = _config_with_choice({"Perfil A": "A", "Perfil B": "B"})
    result = classify_unmapped_choice_values(df, config)
    assert result["missing_like"] == ["NS/NC"]
    assert result["unrecognized"] == ["algo_raro"]


def test_classify_unmapped_choice_values_empty_when_everything_mapped():
    df = pd.DataFrame({
        "cj1_eleccion": ["Perfil A", "Perfil B"],
        "cj1_A_rol": ["policia", "medico"],
        "cj1_B_rol": ["medico", "policia"],
    })
    config = _config_with_choice({"Perfil A": "A", "Perfil B": "B"})
    result = classify_unmapped_choice_values(df, config)
    assert result == {"missing_like": [], "unrecognized": []}


def test_validate_config_marks_non_response_as_info_not_warning():
    """Regresión: un valor de no respuesta (NS/NC) en la columna de elección
    no es un problema de mapeo — antes se mostraba con el mismo estilo de
    aviso alarmante que un error real. Debe llegar marcado como "info".
    """
    df = pd.DataFrame({
        "cj1_eleccion": ["Perfil A", "Perfil B", "NS/NC"],
        "cj1_A_rol": ["policia"] * 3,
        "cj1_B_rol": ["medico"] * 3,
    })
    config = _config_with_choice({"Perfil A": "A", "Perfil B": "B"})
    issues = validate_config(df, config)
    non_response_issues = [i for i in issues if "no respuesta" in i["text"]]
    assert len(non_response_issues) == 1
    assert non_response_issues[0]["severity"] == "info"


def test_validate_config_marks_untranslated_value_as_warning():
    """Un valor que no es de no respuesta y tampoco está traducido a ningún
    perfil sí es un problema real de mapeo: debe seguir marcado "warning".
    """
    df = pd.DataFrame({
        "cj1_eleccion": ["Perfil A", "Perfil B", "algo_raro"],
        "cj1_A_rol": ["policia"] * 3,
        "cj1_B_rol": ["medico"] * 3,
    })
    config = _config_with_choice({"Perfil A": "A", "Perfil B": "B"})
    issues = validate_config(df, config)
    untranslated_issues = [i for i in issues if "sin traducir" in i["text"]]
    assert len(untranslated_issues) == 1
    assert untranslated_issues[0]["severity"] == "warning"
