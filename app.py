# =============================================================================
# OPTIMIZADOR DE PARADAS DE PLANTA
# Streamlit + OR-Tools
#
# Este sistema permite:
# 1. Cargar órdenes de trabajo exportadas desde SAP
# 2. Optimizar el cronograma de ejecución
# 3. Respetar capacidades de técnicos
# 4. Minimizar el tiempo total de parada
# 5. Visualizar el resultado en un diagrama de Gantt
#
# Tecnologías:
# - Streamlit (interfaz web)
# - OR-Tools CP-SAT (optimización)
# - Plotly (visualización)
# =============================================================================

# -----------------------------------------------------------------------------
# IMPORTACIÓN DE LIBRERÍAS
# -----------------------------------------------------------------------------

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# librería para gráficos interactivos
import plotly.express as px

# optimizador de Google
from ortools.sat.python import cp_model


# -----------------------------------------------------------------------------
# CONFIGURACIÓN GENERAL DE LA APLICACIÓN
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="Optimizador Parada de Planta",
    page_icon="🏭",
    layout="wide"
)

st.title("🏭 Optimización de Paradas de Planta")
st.write("Modelo de optimización usando OR-Tools")


# -----------------------------------------------------------------------------
# PANEL LATERAL - CARGA DE DATOS
# -----------------------------------------------------------------------------

st.sidebar.header("Cargar datos")

archivo = st.sidebar.file_uploader(
    "Subir archivo Excel exportado desde SAP",
    type=["xlsx"]
)


# -----------------------------------------------------------------------------
# FUNCIÓN PARA LEER EL EXCEL
# -----------------------------------------------------------------------------

def cargar_datos(file):

    # leer archivo Excel
    df = pd.read_excel(file)

    # limpiar nombres de columnas
    df.columns = df.columns.str.strip()

    return df


# -----------------------------------------------------------------------------
# FUNCIÓN DE OPTIMIZACIÓN (OR-TOOLS)
# -----------------------------------------------------------------------------

def optimizar_cronograma(df, horizonte=36):

    """
    Esta función crea un modelo matemático de programación de actividades.

    Objetivo:
    minimizar el tiempo total de parada.

    Restricciones:
    - capacidad de técnicos
    - duración de actividades
    """

    # crear modelo de optimización
    model = cp_model.CpModel()

    # lista de tareas
    tareas = df.index.tolist()

    # duración de cada tarea
    duraciones = df["duracion_h"].astype(int).tolist()

    # -------------------------------------------------------------------------
    # VARIABLES DE DECISIÓN
    # -------------------------------------------------------------------------
    # el solver decide en qué hora inicia cada actividad

    inicio = {}
    fin = {}
    intervalos = {}

    for i in tareas:

        # hora de inicio
        inicio[i] = model.NewIntVar(
            0,
            horizonte,
            f"inicio_{i}"
        )

        # hora de fin
        fin[i] = model.NewIntVar(
            0,
            horizonte,
            f"fin_{i}"
        )

        # intervalo de ejecución
        intervalos[i] = model.NewIntervalVar(
            inicio[i],
            duraciones[i],
            fin[i],
            f"intervalo_{i}"
        )


    # -------------------------------------------------------------------------
    # CAPACIDAD DE RECURSOS (TÉCNICOS DISPONIBLES)
    # -------------------------------------------------------------------------

    CAPACIDAD = {
        "MECANICA": 8,
        "ELECTRICA": 6,
        "INSTRUMENTACION": 5
    }

    especialidades = df["especialidad"].unique()

    for esp in especialidades:

        # seleccionar tareas de esa especialidad
        tareas_esp = [
            i for i in tareas
            if df.loc[i, "especialidad"] == esp
        ]

        # intervalos correspondientes
        intervalos_esp = [
            intervalos[i] for i in tareas_esp
        ]

        # cada tarea usa 1 técnico
        demandas = [1] * len(intervalos_esp)

        # capacidad máxima
        cap = CAPACIDAD.get(esp, 4)

        # restricción cumulative
        model.AddCumulative(
            intervalos_esp,
            demandas,
            cap
        )


    # -------------------------------------------------------------------------
    # FUNCIÓN OBJETIVO
    # -------------------------------------------------------------------------
    # minimizar duración total de la parada

    makespan = model.NewIntVar(
        0,
        horizonte,
        "makespan"
    )

    model.AddMaxEquality(
        makespan,
        [fin[i] for i in tareas]
    )

    model.Minimize(makespan)


    # -------------------------------------------------------------------------
    # EJECUTAR SOLVER
    # -------------------------------------------------------------------------

    solver = cp_model.CpSolver()

    # tiempo máximo de búsqueda
    solver.parameters.max_time_in_seconds = 10

    status = solver.Solve(model)


    # -------------------------------------------------------------------------
    # EXTRAER RESULTADOS
    # -------------------------------------------------------------------------

    resultados = []

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):

        for i in tareas:

            # valores encontrados por el solver
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

if archivo:

    # leer datos
    df = cargar_datos(archivo)

    st.subheader("Datos cargados")

    st.dataframe(df)

    # botón para ejecutar optimización
    if st.button("Optimizar cronograma"):

        resultado = optimizar_cronograma(df)

        st.subheader("Cronograma optimizado")

        st.dataframe(resultado)


        # ---------------------------------------------------------------------
        # CREAR FECHAS REALES
        # ---------------------------------------------------------------------

        inicio_parada = datetime(2026, 3, 18, 6, 0)

        resultado["inicio_real"] = resultado["start"].apply(
            lambda x: inicio_parada + timedelta(hours=x)
        )

        resultado["fin_real"] = resultado["end"].apply(
            lambda x: inicio_parada + timedelta(hours=x)
        )


        # ---------------------------------------------------------------------
        # GRAFICO DE GANTT
        # ---------------------------------------------------------------------

        fig = px.timeline(
            resultado,
            x_start="inicio_real",
            x_end="fin_real",
            y="actividad",
            color="especialidad",
            title="Cronograma de Parada de Planta"
        )

        fig.update_yaxes(autorange="reversed")

        st.plotly_chart(
            fig,
            use_container_width=True
        )
