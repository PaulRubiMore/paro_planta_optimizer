# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA - CP-SAT
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px

# -------------------------------------------------------------------
# CONFIGURACIÓN APP
# -------------------------------------------------------------------
st.set_page_config(page_title="Optimización Parada Planta", page_icon="🏭", layout="wide")
st.title("🏭 Optimización de Parada de Planta")

horas_paro = st.sidebar.number_input("Duración del paro (horas)", min_value=1, max_value=500, value=36)
fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")
inicio_parada = datetime.combine(fecha_inicio, hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])

# -------------------------------------------------------------------
# FUNCIONES AUXILIARES
# -------------------------------------------------------------------
def limpiar_columnas(df):
    df.columns = df.columns.str.strip().str.replace("\n"," ",regex=True).str.replace("  "," ")
    return df

def cargar_datos(archivo1, archivo2):
    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)
    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)
    for col in df1.columns:
        if "TIEMPO" in col.upper(): df1 = df1.rename(columns={col:"TIEMPO (Hrs)"})
    df1 = df1[df1["EJECUTOR"].str.contains("massy", case=False, na=False)]
    df1 = df1[["Centro planificación","Actividades","Orden","TIEMPO (Hrs)","ESTADO","ESPECIALIDAD","EJECUTOR","CRITICIDAD"]]
    df2 = df2[["Actividades","Zona","Sector"]]
    df1 = df1.drop_duplicates(subset=["Orden"])
    df2 = df2.drop_duplicates(subset=["Actividades"])
    df = df1.merge(df2, on="Actividades", how="left")
    df = df.rename(columns={"Orden":"orden","Actividades":"actividad","TIEMPO (Hrs)":"duracion_h","ESPECIALIDAD":"especialidad","CRITICIDAD":"criticidad"})
    df["duracion_h"] = df["duracion_h"].fillna(1).astype(float)
    return df

# -------------------------------------------------------------------
# Descomposición de órdenes por especialidad y distribución de horas
# -------------------------------------------------------------------
def descomponer_ordenes(df):
    actividades=[]
    for _,row in df.iterrows():
        especs=[e.strip().upper() for e in str(row["especialidad"]).replace("/,",",").replace("/",",").split(",")]
        total=row["duracion_h"]
        if len(especs)==3: porcentajes=[0.5,0.3,0.2]
        elif len(especs)==2:
            if "MECANICA" in especs and "ELECTRICA" in especs: porcentajes=[0.65,0.35]
            elif "ELECTRICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            elif "MECANICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            else: porcentajes=[0.5,0.5]
        else: porcentajes=[1]

        for esp,pct in zip(especs,porcentajes):
            dur=total*pct
            dur=int(dur) if dur-int(dur)<1.5 else int(dur)+1
            actividades.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["Centro planificación"],
                "especialidad":esp,
                "criticidad":str(row["criticidad"]).upper(),
                "duracion_h": dur,
                "duracion_total_orden": total
            })
    return pd.DataFrame(actividades)

# -------------------------------------------------------------------
# OPTIMIZACIÓN
# -------------------------------------------------------------------
def optimizar_actividades(df_actividades, horas_paro):
    dias_paro = ceil(horas_paro/24)
    capacidad_por_tecnico = 8 * dias_paro
    model = cp_model.CpModel()
    intervalos = {}
    resultados = []

    # Crear fragmentos por capacidad de técnico
    for idx,row in df_actividades.iterrows():
        dur = row["duracion_h"]
        n_frag = ceil(dur / 8)  # fragmentos de máximo 8h
        fragmentos=[]
        remaining = dur
        for f in range(n_frag):
            frag_dur = min(8, remaining)
            s = model.NewIntVar(0, horas_paro, f"s_{idx}_{f}")
            e = model.NewIntVar(0, horas_paro, f"e_{idx}_{f}")
            iv = model.NewIntervalVar(s, frag_dur, e, f"int_{idx}_{f}")
            fragmentos.append((s,e,iv,f+1))
            remaining -= frag_dur
        intervalos[idx] = fragmentos

    # Restricción: No overlap por centro/especialidad
    for (c,e), idxs in df_actividades.groupby(["centro","especialidad"]).groups.items():
        intervs=[]
        for idx in idxs:
            intervs.extend([iv for s,e_,iv,f in intervalos[idx]])
        model.AddNoOverlap(intervs)

    # Objetivo: minimizar makespan
    makespan = model.NewIntVar(0, horas_paro, "makespan")
    all_ends = [e_ for idxs in intervalos.values() for s,e_,iv,f in idxs]
    model.AddMaxEquality(makespan, all_ends)
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return pd.DataFrame()  # no factible

    for idx,row in df_actividades.iterrows():
        for s,e_,iv,f in intervalos[idx]:
            resultados.append({
                **row,
                "fragmento": f,
                "start": solver.Value(s),
                "end": solver.Value(e_)
            })

    df_result = pd.DataFrame(resultados)
    if df_result.empty:
        df_result = pd.DataFrame(columns=list(df_actividades.columns)+["fragmento","start","end","tecnico_id"])
    else:
        # Crear ID de técnico dinámico
        df_result["tecnico_id"] = df_result.groupby(["centro","especialidad","fragmento"]).ngroup()+1
    return df_result

# -------------------------------------------------------------------
# GENERAR CRONOGRAMA POR HORAS
# -------------------------------------------------------------------
def generar_cronograma_horas(df_result,horas_paro):
    if df_result.empty: return pd.DataFrame()
    tecnicos = df_result["tecnico_id"].unique()
    cronograma = pd.DataFrame(index=tecnicos, columns=range(horas_paro))
    for _,row in df_result.iterrows():
        t = row["tecnico_id"]
        for h in range(row["start"], row["end"]):
            if h < horas_paro: cronograma.loc[t,h] = row["actividad"]
    return cronograma.fillna("")

# -------------------------------------------------------------------
# EJECUCIÓN APP
# -------------------------------------------------------------------
if archivo1 and archivo2:
    df = cargar_datos(archivo1, archivo2)
    st.subheader("Datos filtrados Massy Energy")
    st.dataframe(df)

    if st.button("Generar Cronograma"):
        df_actividades = descomponer_ordenes(df)
        st.subheader("Actividades descompuestas por especialidad")
        st.dataframe(df_actividades)

        st.subheader("Optimizando actividades...")
        resultado = optimizar_actividades(df_actividades, horas_paro)

        if not resultado.empty:
            resultado["inicio_real"] = resultado["start"].apply(lambda x: inicio_parada + timedelta(hours=x))
            resultado["fin_real"] = resultado["end"].apply(lambda x: inicio_parada + timedelta(hours=x))
            st.subheader("Cronograma optimizado")
            st.dataframe(resultado)

            cronograma_horas = generar_cronograma_horas(resultado, horas_paro)
            st.subheader("Cronograma por técnico y hora")
            st.dataframe(cronograma_horas)

            fig = px.timeline(
                resultado,
                x_start="inicio_real",
                x_end="fin_real",
                y="tecnico_id",
                color="especialidad",
                title="Cronograma de Parada"
            )
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig,use_container_width=True)
        else:
            st.warning("No se pudo generar un cronograma. Revisa los datos o la duración del paro.")
else:
    st.info("Cargar los dos archivos Excel para iniciar.")
