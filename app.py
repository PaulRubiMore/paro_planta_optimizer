# =============================================================================
# OPTIMIZADOR DE ACTIVIDADES - PARADA DE BOMBEO
# Streamlit + OR-Tools
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from ortools.sat.python import cp_model


# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE LA APP
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="Optimizador Parada Bombeo",
    page_icon="🏭",
    layout="wide"
)

st.title("🏭 Optimización de Parada de Bombeo")


# -----------------------------------------------------------------------------
# SIDEBAR - CARGA DE ARCHIVOS
# -----------------------------------------------------------------------------

st.sidebar.header("Cargar archivos")

archivo1 = st.sidebar.file_uploader(
    "Archivo 1 - Paro de bombeo",
    type=["xlsx"]
)

archivo2 = st.sidebar.file_uploader(
    "Archivo 2 - Lista de actividades",
    type=["xlsx"]
)


# -----------------------------------------------------------------------------
# FUNCIÓN PARA CARGAR Y LIMPIAR DATOS
# -----------------------------------------------------------------------------

def cargar_datos(archivo1, archivo2):

    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)

    # limpiar nombres
    df1.columns = df1.columns.str.strip()
    df2.columns = df2.columns.str.strip()

    # -------------------------------------------------------------
    # FILTRAR MASSY ENERGY
    # -------------------------------------------------------------

    df1 = df1[
        df1["EJECUTOR"].str.contains(
            "massy energy",
            case=False,
            na=False
        )
    ]

    # -------------------------------------------------------------
    # COLUMNAS NECESARIAS
    # -------------------------------------------------------------

    df1 = df1[
        [
            "Centro planificación",
            "Actividades",
            "Orden",
            "TIEMPO (Hrs)",
            "ESTADO",
            "ESPECIALIDAD",
            "EJECUTOR",
            "CRITICIDAD"
        ]
    ]

    df2 = df2[
        [
            "Actividades",
            "Zona",
            "Sector"
        ]
    ]

    # -------------------------------------------------------------
    # MERGE DE LOS DOS ARCHIVOS
    # -------------------------------------------------------------

    df = df1.merge(
        df2,
        on="Actividades",
        how="left"
    )

    # renombrar columnas
    df = df.rename(
        columns={
            "TIEMPO (Hrs)": "duracion_h",
            "Actividades": "actividad",
            "Orden": "orden",
            "ESPECIALIDAD": "especialidad",
            "CRITICIDAD": "criticidad"
        }
    )

    # convertir duración
    df["duracion_h"] = df["duracion_h"].fillna(1).astype(int)

    return df


# -----------------------------------------------------------------------------
# FUNCIÓN DE OPTIMIZACIÓN
# -----------------------------------------------------------------------------

def optimizar_cronograma(df, horizonte=36):

    model = cp_model.CpModel()

    tareas = df.index.tolist()
    duraciones = df["duracion_h"].tolist()

    inicio = {}
    fin = {}
    intervalos = {}

    for i in tareas:

        inicio[i] = model.NewIntVar(0, horizonte, f"inicio_{i}")

        fin[i] = model.NewIntVar(0, horizonte, f"fin_{i}")

        intervalos[i] = model.NewIntervalVar(
            inicio[i],
            duraciones[i],
            fin[i],
            f"intervalo_{i}"
        )

    # -------------------------------------------------------------
    # CAPACIDAD DE TÉCNICOS
    # -------------------------------------------------------------

    CAPACIDAD = {
        "MECANICA": 8,
        "ELECTRICA": 6,
        "INSTRUMENTACION": 5
    }

    especialidades = df["especialidad"].unique()

    for esp in especialidades:

        tareas_esp = [
            i for i in tareas
            if df.loc[i, "especialidad"] == esp
        ]

        intervalos_esp = [
            intervalos[i] for i in tareas_esp
        ]

        demandas = [1] * len(intervalos_esp)

        cap = CAPACIDAD.get(esp, 4)

        model.AddCumulative(
            intervalos_esp,
            demandas,
            cap
        )

    # -------------------------------------------------------------
    # FUNCIÓN OBJETIVO
    # -------------------------------------------------------------

    makespan = model.NewIntVar(0, horizonte, "makespan")

    model.AddMaxEquality(
        makespan,
        [fin[i] for i in tareas]
    )

    model.Minimize(makespan)

    # -------------------------------------------------------------
    # SOLVER
    # -------------------------------------------------------------

    solver = cp_model.CpSolver()

    solver.parameters.max_time_in_seconds = 10

    status = solver.Solve(model)

    resultados = []

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):

        for i in tareas:

            s = solver.Value(inicio[i])
            f = solver.Value(fin[i])

            fila = df.loc[i].to_dict()

            fila["start"] = s
            fila["end"] = f

            resultados.append(fila)

    return pd.DataFrame(resultados)


# -----------------------------------------------------------------------------
# EJECUCIÓN PRINCIPAL
# -----------------------------------------------------------------------------

if archivo1 and archivo2:

    df = cargar_datos(archivo1, archivo2)

    st.subheader("📊 Datos filtrados Massy Energy")

    st.dataframe(df)

    if st.button("🚀 Optimizar cronograma"):

        resultado = optimizar_cronograma(df)

        st.subheader("📅 Cronograma optimizado")

        st.dataframe(resultado)

        # ---------------------------------------------------------
        # FECHAS REALES
        # ---------------------------------------------------------

        inicio_parada = datetime(2026, 3, 18, 6, 0)

        resultado["inicio_real"] = resultado["start"].apply(
            lambda x: inicio_parada + timedelta(hours=x)
        )

        resultado["fin_real"] = resultado["end"].apply(
            lambda x: inicio_parada + timedelta(hours=x)
        )

        # ---------------------------------------------------------
        # DIAGRAMA DE GANTT
        # ---------------------------------------------------------

        fig = px.timeline(
            resultado,
            x_start="inicio_real",
            x_end="fin_real",
            y="actividad",
            color="especialidad",
            title="Cronograma de Actividades"
        )

        fig.update_yaxes(autorange="reversed")

        st.plotly_chart(
            fig,
            use_container_width=True
        )

else:

    st.info("👈 Carga los dos archivos Excel para iniciar.")
