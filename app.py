# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA - STREAMLIT + OR-TOOLS
# Genera automáticamente la cantidad de técnicos necesaria
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px

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

fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")
inicio_parada = datetime.combine(fecha_inicio, hora_inicio)

st.sidebar.header("Cargar archivos Excel")
archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])

# -----------------------------------------------------------------------------
# FUNCIONES AUXILIARES
# -----------------------------------------------------------------------------

def limpiar_columnas(df):
    df.columns = (
        df.columns
        .str.strip()
        .str.replace("\n", " ", regex=True)
        .str.replace("  ", " ")
    )
    return df

def cargar_datos(archivo1, archivo2):
    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)

    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)

    for col in df1.columns:
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col: "TIEMPO (Hrs)"})

    # Filtrar Massy
    df1 = df1[df1["EJECUTOR"].str.contains("massy", case=False, na=False)]

    df1 = df1[[
        "Centro planificación",
        "Actividades",
        "Orden",
        "TIEMPO (Hrs)",
        "ESTADO",
        "ESPECIALIDAD",
        "EJECUTOR",
        "CRITICIDAD"
    ]]

    df2 = df2[["Actividades", "Zona", "Sector"]]

    df1 = df1.drop_duplicates(subset=["Orden"])
    df2 = df2.drop_duplicates(subset=["Actividades"])

    df = df1.merge(df2, on="Actividades", how="left")

    df = df.rename(columns={
        "Orden": "orden",
        "Actividades": "actividad",
        "TIEMPO (Hrs)": "duracion_h",
        "ESPECIALIDAD": "especialidad",
        "CRITICIDAD": "criticidad"
    })

    df["duracion_h"] = df["duracion_h"].fillna(1).astype(float)
    return df

# -----------------------------------------------------------------------------
# Paso 1-4: Descomposición de órdenes y distribución de horas
# -----------------------------------------------------------------------------

def descomponer_ordenes(df):
    actividades = []
    for _, row in df.iterrows():
        especs = [e.strip().upper() for e in row["especialidad"].split(",")]
        total = row["duracion_h"]

        # Distribución de horas
        if len(especs) == 3:
            porcentajes = [0.5, 0.3, 0.2]
        elif len(especs) == 2:
            if "MECANICA" in especs and "ELECTRICA" in especs:
                porcentajes = [0.65, 0.35]
            elif "ELECTRICA" in especs and "INSTRUMENTACION" in especs:
                porcentajes = [0.6, 0.4]
            else:
                porcentajes = [0.5, 0.5]
        else:
            porcentajes = [1]

        for esp, pct in zip(especs, porcentajes):
            dur = total * pct
            dur = int(dur) if dur - int(dur) < 1.5 else int(dur)+1
            actividades.append({
                "orden": row["orden"],
                "actividad": row["actividad"],
                "centro": row["Centro planificación"],
                "especialidad": esp,
                "criticidad": row["criticidad"].upper(),
                "duracion_h": dur
            })
    return pd.DataFrame(actividades)

# -----------------------------------------------------------------------------
# Paso 5-6: Generación automática de técnicos según demanda
# -----------------------------------------------------------------------------

def generar_tecnicos(df_actividades, horas_paro):
    dias_paro = ceil(horas_paro / 24)
    capacidad_por_tecnico = dias_paro * 8  # 8 h/día

    centros = df_actividades["centro"].unique()
    especialidades = df_actividades["especialidad"].unique()
    tecnicos = []

    for c in centros:
        for e in especialidades:
            total_horas = df_actividades[(df_actividades["centro"]==c) &
                                         (df_actividades["especialidad"]==e)]["duracion_h"].sum()
            n_tecnicos = max(1, ceil(total_horas / capacidad_por_tecnico))
            for t in range(1, n_tecnicos+1):
                tecnicos.append({
                    "id": f"{c}_{e}_T{t}",
                    "centro": c,
                    "especialidad": e,
                    "capacidad": capacidad_por_tecnico
                })
    return pd.DataFrame(tecnicos)

# -----------------------------------------------------------------------------
# Paso 7: Optimización CP-SAT
# -----------------------------------------------------------------------------

def optimizar_actividades(df_actividades, df_tecnicos, horas_paro):
    model = cp_model.CpModel()
    horizon = horas_paro
    actividades = df_actividades.index.tolist()
    tecnicos = df_tecnicos["id"].tolist()

    start = {}
    end = {}
    intervalos = {}
    asigna = {}

    for i in actividades:
        row = df_actividades.loc[i]
        asigna[i] = []
        techs_disp = df_tecnicos[(df_tecnicos["centro"]==row["centro"]) &
                                 (df_tecnicos["especialidad"]==row["especialidad"])]["id"].tolist()
        for t in techs_disp:
            s = model.NewIntVar(0, horizon, f"start_{i}_{t}")
            e = model.NewIntVar(0, horizon, f"end_{i}_{t}")
            dur = row["duracion_h"]
            interv = model.NewIntervalVar(s, dur, e, f"int_{i}_{t}")
            start[i,t] = s
            end[i,t] = e
            intervalos[i,t] = interv
            asigna[i].append(t)

    # Restricción: un técnico solo hace una actividad a la vez
    for t in tecnicos:
        interv_tecnico = [intervalos[i,t] for i in actividades if (i,t) in intervalos]
        if interv_tecnico:
            model.AddNoOverlap(interv_tecnico)

    # Objetivo: minimizar makespan
    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, [end[i,t] for i in actividades for t in asigna[i]])
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    resultados = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for i in actividades:
            row = df_actividades.loc[i].to_dict()
            for t in asigna[i]:
                if solver.Value(start[i,t]) < horizon:
                    row_copy = row.copy()
                    row_copy["tecnico"] = t
                    row_copy["start"] = solver.Value(start[i,t])
                    row_copy["end"] = solver.Value(end[i,t])
                    resultados.append(row_copy)

    return pd.DataFrame(resultados)

# -----------------------------------------------------------------------------
# Paso 8: Generar cronograma por hora
# -----------------------------------------------------------------------------

def generar_cronograma_horas(df_result, horas_paro):
    tecnicos = df_result["tecnico"].unique()
    cronograma = pd.DataFrame(index=tecnicos, columns=range(horas_paro))

    for _, row in df_result.iterrows():
        t = row["tecnico"]
        for h in range(row["start"], row["end"]):
            if h < horas_paro:
                cronograma.loc[t, h] = row["actividad"]

    return cronograma.fillna("")

# -----------------------------------------------------------------------------
# EJECUCIÓN APP
# -----------------------------------------------------------------------------

if archivo1 and archivo2:
    df = cargar_datos(archivo1, archivo2)
    st.subheader("Datos filtrados Massy Energy")
    st.dataframe(df)

    if st.button("Generar Cronograma"):
        df_actividades = descomponer_ordenes(df)
        df_tecnicos = generar_tecnicos(df_actividades, horas_paro)
        st.subheader("Técnicos necesarios calculados automáticamente")
        st.dataframe(df_tecnicos)

        st.subheader("Optimizando actividades...")
        resultado = optimizar_actividades(df_actividades, df_tecnicos, horas_paro)

        # Convertir horas a datetime real
        resultado["inicio_real"] = resultado["start"].apply(lambda x: inicio_parada + timedelta(hours=x))
        resultado["fin_real"] = resultado["end"].apply(lambda x: inicio_parada + timedelta(hours=x))

        st.subheader("Cronograma optimizado")
        st.dataframe(resultado)

        # Cronograma por hora
        cronograma_horas = generar_cronograma_horas(resultado, horas_paro)
        st.subheader("Cronograma por técnico y hora")
        st.dataframe(cronograma_horas)

        # GANTT
        fig = px.timeline(
            resultado,
            x_start="inicio_real",
            x_end="fin_real",
            y="tecnico",
            color="especialidad",
            title="Cronograma de Parada"
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Cargar los dos archivos Excel para iniciar.")
