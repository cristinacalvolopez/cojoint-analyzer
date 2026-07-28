"""Genera un CSV ancho de ejemplo con la misma forma que el estudio real:
300 entrevistados, 8 tareas (cj1..cj8), 2 perfiles (A/B) por tarea y 6
atributos por perfil (rol, género, edad, orientación, dos rasgos
aleatorios). Sirve para probar la app sin exponer datos reales.

Uso:
    python sample_data/generate_sample.py
"""
import numpy as np
import pandas as pd

ROLES = ["Profesor/a", "Policía", "Sanitario/a", "Empresario/a"]
GENEROS = ["Hombre", "Mujer"]
EDADES = ["25 años", "40 años", "60 años"]
ORIENTACIONES = ["Heterosexual", "Gay", "Lesbiana", "Bisexual"]
RASGO_A = ["Con pareja estable", "Soltero/a"]
RASGO_B = ["Sin hijos", "Con hijos"]

N_RESPONDENTS = 300
N_TASKS = 8


def main(seed: int = 2026):
    rng = np.random.default_rng(seed)
    rows = []
    for rid in range(1, N_RESPONDENTS + 1):
        row = {"id_encuesta": rid}
        for t in range(1, N_TASKS + 1):
            profile_a = {
                "rol": rng.choice(ROLES),
                "gen": rng.choice(GENEROS),
                "edad": rng.choice(EDADES),
                "orient": rng.choice(ORIENTACIONES),
                "ca_1": rng.choice(RASGO_A),
                "ca_2": rng.choice(RASGO_B),
            }
            profile_b = {
                "rol": rng.choice(ROLES),
                "gen": rng.choice(GENEROS),
                "edad": rng.choice(EDADES),
                "orient": rng.choice(ORIENTACIONES),
                "ca_1": rng.choice(RASGO_A),
                "ca_2": rng.choice(RASGO_B),
            }
            for key, value in profile_a.items():
                row[f"cj{t}_A_{key}"] = value
            for key, value in profile_b.items():
                row[f"cj{t}_B_{key}"] = value

            # Utilidad simulada con un efecto negativo hacia orientaciones no
            # heterosexuales, solo para tener una señal detectable en el AMCE
            # de ejemplo; no representa ninguna opinión ni dato real.
            def utility(p):
                u = rng.normal(0, 1)
                if p["orient"] != "Heterosexual":
                    u -= 0.6
                return u

            row[f"cj{t}_eleccion"] = "A" if utility(profile_a) > utility(profile_b) else "B"

        rows.append(row)

    df = pd.DataFrame(rows)
    out_path = "sample_data/conjoint_sample_wide.csv"
    df.to_csv(out_path, index=False)
    print(f"Generado {out_path} con {df.shape[0]} filas y {df.shape[1]} columnas.")


if __name__ == "__main__":
    main()
