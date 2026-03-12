# =============================================================================
# OPTIMIZADOR DE PARADAS DE PLANTA
# Streamlit + OR-Tools
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px

from ortools.sat.python import cp_model


# -----------------------------------------------------------------------------
# CONFIGURACIÓN STREAMLIT
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="Optimizador Parada de Planta",
    page_icon="🏭",
    layout="wide"
)

st.title("🏭 Optimización de Paradas de Planta")


# -----------------------------------------------------------------------------
# CARGA DE ARCHIVOS
# -----------------------------------------------------------------------------

st.sidebar.header("Cargar archivos Excel")

archivo1 = st.sidebar.file_uploader(
    "Archivo planificación",
    type=["xlsx"]
)

archivo2 = st.sidebar.file_uploader(
    "Archivo órdenes",
    type=["xlsx"]
)


# -----------------------------------------------------------------------------
# LIMPIAR COLUMNAS
# -----------------------------------------------------------------------------

def limpiar_columnas(df):

    df.columns = (
        df.columns
        .str.strip()
        .str.replace("\n", " ")
        .str.replace("  ", " ")
    )

    return df


# -----------------------------------------------------------------------------
# CARGAR Y PREPARAR DATOS
# -----------------------------------------------------------------------------

def cargar_datos(file1, file2):

    df1 = pd.read_excel(file1)
    df2 = pd.read_excel(file2)

    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)

    # unir archivos
    df = pd.concat([df1, df2], ignore_index=True)

    # filtrar ejecutor
    df = df[
        df["EJECUTOR"].str.upper().isin(
            ["MASSY ENERGY", "MASSY ENERGY GEN"]
        )
    ]

    # renombrar columnas para el modelo
    df = df.rename(columns={
        "Actividades": "actividad",
        "TIEMPO (Hrs)": "duracion_h",
        "ESPECIALIDAD": "especialidad",
        "CRITICIDAD": "criticidad"
    })

    # eliminar filas sin duración
    df = df[df["duracion_h"].notna()]

    df["duracion_h"] = df["duracion_h"].astype(int)

    df = df.reset_index(drop=True)

    return df


# -----------------------------------------------------------------------------
# OPTIMIZADOR ORTOOLS
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


    # ------------------------------------------------------------
    # CAPACIDAD DE TÉCNICOS
    # ------------------------------------------------------------

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


    # ------------------------------------------------------------
    # OBJETIVO: minimizar duración total
    # ------------------------------------------------------------

    makespan = model.NewIntVar(0, horizonte, "makespan")

    model.AddMaxEquality(
        makespan,
        [fin[i] for i in tareas]
    )

    model.Minimize(makespan)


    # ------------------------------------------------------------
    # SOLVER
    # ------------------------------------------------------------

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
# EJECUCIÓN DE LA APP
# -----------------------------------------------------------------------------

if archivo1 and archivo2:

    df = cargar_datos(archivo1, archivo2)

    st.subheader("📊 Datos filtrados (Massy Energy)")

    st.dataframe(df)


    if st.button("🚀 Optimizar cronograma"):

        resultado = optimizar_cronograma(df)

        st.subheader("📅 Cronograma optimizado")

        st.dataframe(resultado)


        # ---------------------------------------------------------
        # CONVERTIR HORAS A FECHA REAL
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
            title="Cronograma de Parada de Planta"
        )

        fig.update_yaxes(autorange="reversed")

        st.plotly_chart(fig, use_container_width=True)

else:

    st.info("⬅️ Carga ambos archivos Excel para iniciar.")
