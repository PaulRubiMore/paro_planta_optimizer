# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA
# Streamlit + OR-Tools
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from ortools.sat.python import cp_model


# -----------------------------------------------------------------------------
# CONFIGURACIÓN APP
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="Optimizador Parada Planta",
    page_icon="🏭",
    layout="wide"
)

st.title("🏭 Optimización de Parada de Planta")


# -----------------------------------------------------------------------------
# SIDEBAR
# -----------------------------------------------------------------------------

st.sidebar.header("Configuración del Paro")

horas_paro = st.sidebar.number_input(
    "Duración del paro (horas)",
    min_value=1,
    max_value=500,
    value=36
)

fecha_inicio = st.sidebar.date_input(
    "Fecha inicio del paro"
)

hora_inicio = st.sidebar.time_input(
    "Hora inicio del paro"
)

inicio_parada = datetime.combine(fecha_inicio, hora_inicio)


st.sidebar.header("Cargar archivos Excel")

archivo1 = st.sidebar.file_uploader(
    "Archivo 1 - Paro de bombeo",
    type=["xlsx"]
)

archivo2 = st.sidebar.file_uploader(
    "Archivo 2 - Lista de actividades",
    type=["xlsx"]
)


# -----------------------------------------------------------------------------
# LIMPIAR COLUMNAS
# -----------------------------------------------------------------------------

def limpiar_columnas(df):

    df.columns = (
        df.columns
        .str.strip()
        .str.replace("\n", " ", regex=True)
        .str.replace("  ", " ")
    )

    return df


# -----------------------------------------------------------------------------
# CARGAR DATOS
# -----------------------------------------------------------------------------

def cargar_datos(archivo1, archivo2):

    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)

    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)

    # detectar columna tiempo
    for col in df1.columns:
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col: "TIEMPO (Hrs)"})

    # filtrar massy
    df1 = df1[
        df1["EJECUTOR"].str.contains(
            "massy",
            case=False,
            na=False
        )
    ]

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

    # eliminar duplicados
    df1 = df1.drop_duplicates(subset=["Orden"])
    df2 = df2.drop_duplicates(subset=["Actividades"])

    # merge
    df = df1.merge(
        df2,
        on="Actividades",
        how="left"
    )

    # renombrar
    df = df.rename(
        columns={
            "Orden": "orden",
            "Actividades": "actividad",
            "TIEMPO (Hrs)": "duracion_h",
            "ESPECIALIDAD": "especialidad",
            "CRITICIDAD": "criticidad"
        }
    )

    df["duracion_h"] = df["duracion_h"].fillna(1).astype(int)

    return df


# -----------------------------------------------------------------------------
# OPTIMIZADOR
# -----------------------------------------------------------------------------

def optimizar_cronograma(df, horizonte):

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

    # capacidad técnicos
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

        intervalos_esp = [intervalos[i] for i in tareas_esp]

        demandas = [1] * len(intervalos_esp)

        cap = CAPACIDAD.get(esp, 4)

        model.AddCumulative(
            intervalos_esp,
            demandas,
            cap
        )

    # objetivo minimizar duración total
    makespan = model.NewIntVar(0, horizonte, "makespan")

    model.AddMaxEquality(
        makespan,
        [fin[i] for i in tareas]
    )

    model.Minimize(makespan)

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
# EJECUCIÓN
# -----------------------------------------------------------------------------

if archivo1 and archivo2:

    df = cargar_datos(archivo1, archivo2)

    st.subheader("Datos filtrados Massy Energy")

    st.dataframe(df)

    st.write("Ordenes únicas:", df["orden"].nunique())

    if st.button("Optimizar cronograma"):

        resultado = optimizar_cronograma(df, horas_paro)

        st.subheader("Cronograma optimizado")

        resultado["inicio_real"] = resultado["start"].apply(
            lambda x: inicio_parada + timedelta(hours=x)
        )

        resultado["fin_real"] = resultado["end"].apply(
            lambda x: inicio_parada + timedelta(hours=x)
        )

        st.dataframe(resultado)

        # GANTT
        fig = px.timeline(
            resultado,
            x_start="inicio_real",
            x_end="fin_real",
            y="actividad",
            color="especialidad",
            title="Cronograma de Parada"
        )

        fig.update_yaxes(autorange="reversed")

        st.plotly_chart(fig, use_container_width=True)

else:

    st.info("Cargar los dos archivos Excel para iniciar.")
