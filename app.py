# =============================================================================
# APP STREAMLIT - OPTIMIZADOR PARADA DE PLANTA
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime
from ortools.sat.python import cp_model

# -----------------------------------------------------------------------------
# CONFIGURACIÓN APP
# -----------------------------------------------------------------------------

st.set_page_config(page_title="Optimización Paro Planta", layout="wide")

st.title("Optimización de Parada de Planta")

# -----------------------------------------------------------------------------
# PARÁMETROS DEL PARO
# -----------------------------------------------------------------------------

st.sidebar.header("Parámetros del Paro")

horas_paro = st.sidebar.number_input(
    "Duración del paro (horas)",
    min_value=1,
    max_value=500,
    value=36
)

fecha_inicio = st.sidebar.date_input("Fecha inicio paro")
hora_inicio = st.sidebar.time_input("Hora inicio paro")

inicio_paro = datetime.combine(fecha_inicio, hora_inicio)

# -----------------------------------------------------------------------------
# CARGA ARCHIVOS
# -----------------------------------------------------------------------------

archivo1 = st.sidebar.file_uploader("Archivo SAP órdenes", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo zonas", type=["xlsx"])


# -----------------------------------------------------------------------------
# LIMPIEZA COLUMNAS
# -----------------------------------------------------------------------------

def limpiar_columnas(df):

    df.columns = df.columns.str.strip()
    df.columns = df.columns.str.replace("\n", " ", regex=True)

    return df


# -----------------------------------------------------------------------------
# CARGA DATOS
# -----------------------------------------------------------------------------

def cargar_datos(archivo1, archivo2):

    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)

    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)

    # buscar columna tiempo

    for col in df1.columns:
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col: "TIEMPO (Hrs)"})

    df1 = df1[df1["EJECUTOR"].str.contains("massy", case=False, na=False)]

    df1 = df1[[
        "Centro planificación",
        "Actividades",
        "Orden",
        "TIEMPO (Hrs)",
        "ESPECIALIDAD",
        "CRITICIDAD",
        "EJECUTOR"
    ]]

    df2 = df2[["Actividades", "Zona", "Sector"]]

    df = df1.merge(df2, on="Actividades", how="left")

    df = df.rename(columns={
        "Orden": "orden",
        "Actividades": "actividad",
        "TIEMPO (Hrs)": "duracion_h",
        "ESPECIALIDAD": "especialidad",
        "CRITICIDAD": "criticidad",
        "Centro planificación": "centro"
    })

    df["duracion_h"] = df["duracion_h"].fillna(1)

    return df


# -----------------------------------------------------------------------------
# DESCOMPOSICIÓN POR ESPECIALIDAD
# -----------------------------------------------------------------------------

def descomponer_ordenes(df):

    actividades = []

    for _, row in df.iterrows():

        especs = str(row["especialidad"]).replace("/", ",").split(",")

        especs = [e.strip().upper() for e in especs]

        total = row["duracion_h"]

        if len(especs) == 3:

            porcentajes = [0.5, 0.3, 0.2]

        elif len(especs) == 2:

            porcentajes = [0.6, 0.4]

        else:

            porcentajes = [1]

        for esp, pct in zip(especs, porcentajes):

            dur = round(total * pct)

            actividades.append({

                "orden": row["orden"],
                "actividad": row["actividad"],
                "centro": row["centro"],
                "especialidad": esp,
                "duracion_h": dur

            })

    return pd.DataFrame(actividades)


# -----------------------------------------------------------------------------
# FRAGMENTAR EN BLOQUES DE 8 HORAS
# -----------------------------------------------------------------------------

def fragmentar_actividades(df):

    bloques = []

    for _, row in df.iterrows():

        horas = row["duracion_h"]

        bloque = 1

        while horas > 0:

            dur = min(8, horas)

            bloques.append({

                "orden": row["orden"],
                "actividad": row["actividad"],
                "centro": row["centro"],
                "especialidad": row["especialidad"],
                "duracion": dur,
                "bloque": bloque

            })

            horas -= dur
            bloque += 1

    return pd.DataFrame(bloques)


# -----------------------------------------------------------------------------
# OPTIMIZADOR CP-SAT
# -----------------------------------------------------------------------------

def optimizar_paro(df, horas_paro):

    model = cp_model.CpModel()

    n = len(df)

    max_tecnicos = 20

    start = {}
    end = {}
    tec = {}

    for i in range(n):

        dur = int(df.loc[i, "duracion"])

        start[i] = model.NewIntVar(0, horas_paro, f"start_{i}")

        end[i] = model.NewIntVar(0, horas_paro, f"end_{i}")

        tec[i] = model.NewIntVar(0, max_tecnicos - 1, f"tec_{i}")

        model.Add(end[i] == start[i] + dur)

    # no solapamiento por técnico

    for t in range(max_tecnicos):

        intervals = []

        for i in range(n):

            dur = int(df.loc[i, "duracion"])

            pres = model.NewBoolVar(f"p_{i}_{t}")

            model.Add(tec[i] == t).OnlyEnforceIf(pres)

            model.Add(tec[i] != t).OnlyEnforceIf(pres.Not())

            interval = model.NewOptionalIntervalVar(

                start[i],
                dur,
                end[i],
                pres,
                f"int_{i}_{t}"

            )

            intervals.append(interval)

        model.AddNoOverlap(intervals)

    max_tec = model.NewIntVar(0, max_tecnicos, "max_tec")

    model.AddMaxEquality(max_tec, [tec[i] for i in range(n)])

    model.Minimize(max_tec)

    solver = cp_model.CpSolver()

    solver.parameters.max_time_in_seconds = 30

    status = solver.Solve(model)

    resultado = []

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):

        for i in range(n):

            resultado.append({

                "Tecnico": f"T{solver.Value(tec[i])}",

                "Orden": df.loc[i, "orden"],

                "Actividad": df.loc[i, "actividad"],

                "Centro": df.loc[i, "centro"],

                "Especialidad": df.loc[i, "especialidad"],

                "Bloque": df.loc[i, "bloque"],

                "Inicio_h": solver.Value(start[i]),

                "Fin_h": solver.Value(end[i]),

                "Duracion": df.loc[i, "duracion"]

            })

    return pd.DataFrame(resultado)


# -----------------------------------------------------------------------------
# EJECUCIÓN
# -----------------------------------------------------------------------------

if archivo1 and archivo2:

    df = cargar_datos(archivo1, archivo2)

    st.subheader("Datos cargados")

    st.dataframe(df)

    df_act = descomponer_ordenes(df)

    st.subheader("Actividades por especialidad")

    st.dataframe(df_act)

    df_frag = fragmentar_actividades(df_act)

    st.subheader("Fragmentación en bloques de 8h")

    st.dataframe(df_frag)

    st.subheader("Optimización")

    resultado = optimizar_paro(df_frag, horas_paro)

    st.dataframe(resultado)

    st.subheader("Técnicos requeridos")

    st.write(resultado["Tecnico"].nunique())

    st.subheader("Cronograma final")

    resultado["inicio_real"] = resultado["Inicio_h"].apply(
        lambda x: inicio_paro + pd.Timedelta(hours=x)
    )

    resultado["fin_real"] = resultado["Fin_h"].apply(
        lambda x: inicio_paro + pd.Timedelta(hours=x)
    )

    st.dataframe(resultado)
