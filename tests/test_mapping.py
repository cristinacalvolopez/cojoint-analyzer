from app.mapping import suggest_mapping


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
