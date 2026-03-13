# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA - VERSIÓN EFICIENTE
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px

# ---------------------------------------------------------------------------
# CONFIGURACIÓN APP
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Optimización Parada Planta", page_icon="🏭", layout="wide")
st.title("🏭 Optimización de Parada de Planta")

horas_paro = st.sidebar.number_input("Duración del paro (horas)", min_value=1, max_value=500, value=36)
fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")
inicio_parada = datetime.combine(fecha_inicio, hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])

# ---------------------------------------------------------------------------
# FUNCIONES AUXILIARES
# ---------------------------------------------------------------------------
def limpiar_columnas(df):
    df.columns = df.columns.str.strip().str.replace("\n"," ",regex=True).str.replace("  "," ")
    return df

def cargar_datos(archivo1, archivo2):
    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)
    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)
    df1 = df1[["Centro planificación","Actividades","Orden","TIEMPO (Hrs)","ESTADO","ESPECIALIDAD","CRITICIDAD"]]
    df2 = df2[["Actividades","Zona","Sector"]]
    df1 = df1.drop_duplicates(subset=["Orden"])
    df2 = df2.drop_duplicates(subset=["Actividades"])
    df = df1.merge(df2, on="Actividades", how="left")
    df = df.rename(columns={"Orden":"orden","Actividades":"actividad","TIEMPO (Hrs)":"duracion_h",
                            "ESPECIALIDAD":"especialidad","CRITICIDAD":"criticidad"})
    df["duracion_h"] = df["duracion_h"].fillna(1).astype(float)
    return df

def descomponer_ordenes(df):
    actividades=[]
    for _,row in df.iterrows():
        especs=[e.strip().upper() for e in str(row["especialidad"]).replace("/,",",").replace("/",",").split(",")]
        total=row["duracion_h"]
        if len(especs)==3: porcentajes=[0.5,0.3,0.2]
        elif len(especs)==2:
            porcentajes=[0.6,0.4]
        else: porcentajes=[1]
        for esp,pct in zip(especs,porcentajes):
            dur = total*pct
            dur = int(dur) if dur-int(dur)<1.5 else int(dur)+1
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

# ---------------------------------------------------------------------------
# OPTIMIZACIÓN SIMPLIFICADA CON CP-SAT
# ---------------------------------------------------------------------------
def optimizar_actividades(df_actividades, horas_paro):
    model = cp_model.CpModel()
    dias_paro = ceil(horas_paro / 24)
    max_horas_dia = 8

    max_tecnicos = len(df_actividades) * 2  # heurística: máximo 2 técnicos por actividad

    intervalos = {}
    variables = []

    for idx,row in df_actividades.iterrows():
        dur=row["duracion_h"]
        n_fragments = ceil(dur/max_horas_dia)
        fragment_horas = [max_horas_dia]*(n_fragments-1) + [dur-(n_fragments-1)*max_horas_dia]
        for f,fh in enumerate(fragment_horas):
            assigned = False
            for t in range(max_tecnicos):
                start_var = model.NewIntVar(0, horas_paro, f"s_{idx}_{f}_{t}")
                end_var = model.NewIntVar(0, horas_paro, f"e_{idx}_{f}_{t}")
                interval = model.NewIntervalVar(start_var, fh, end_var, f"int_{idx}_{f}_{t}")
                intervalos[(idx,f,t)] = interval
                variables.append((idx,f,t,start_var,end_var,fh))
    
    # No-overlap por técnico
    for t in range(max_tecnicos):
        tech_intervals = [inter for key,inter in intervalos.items() if key[2]==t]
        if tech_intervals:
            model.AddNoOverlap(tech_intervals)

    # Objetivo: minimizar el makespan
    makespan = model.NewIntVar(0, horas_paro, "makespan")
    model.AddMaxEquality(makespan, [e for _,_,_,_,e,_ in variables])
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    resultados=[]
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for idx,f,t,s_var,e_var,_ in variables:
            s_val = solver.Value(s_var)
            e_val = solver.Value(e_var)
            if e_val>s_val:
                row = df_actividades.loc[idx].to_dict()
                row.update({
                    "fragmento": f+1,
                    "tecnico_id": t+1,
                    "start": s_val,
                    "end": e_val
                })
                resultados.append(row)

    df_result = pd.DataFrame(resultados)
    return df_result

# ---------------------------------------------------------------------------
# GENERAR CRONOGRAMA POR HORAS
# ---------------------------------------------------------------------------
def generar_cronograma_horas(df_result, horas_paro):
    if df_result.empty: return pd.DataFrame()
    tecnicos = df_result["tecnico_id"].unique()
    cronograma = pd.DataFrame(index=tecnicos, columns=range(horas_paro))
    for _,row in df_result.iterrows():
        t=row["tecnico_id"]
        for h in range(int(row["start"]), int(row["end"])):
            if h<horas_paro: cronograma.loc[t,h]=row["actividad"]
    return cronograma.fillna("")

# ---------------------------------------------------------------------------
# EJECUCIÓN APP
# ---------------------------------------------------------------------------
if archivo1 and archivo2:
    df = cargar_datos(archivo1,archivo2)
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
        else:
            st.warning("No se pudo generar un cronograma. Revisa los datos o la duración del paro.")

        cronograma_horas = generar_cronograma_horas(resultado, horas_paro)
        st.subheader("Cronograma por técnico y hora")
        st.dataframe(cronograma_horas)

        if not resultado.empty:
            fig = px.timeline(resultado, x_start="inicio_real", x_end="fin_real",
                              y="tecnico_id", color="especialidad", title="Cronograma de Parada")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig,use_container_width=True)
else:
    st.info("Cargar los dos archivos Excel para iniciar.")
