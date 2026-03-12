# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA - ASIGNA AUTOMÁTICAMENTE TÉCNICOS
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px

# ----------------------------------------------------------------------
# CONFIGURACIÓN APP
# ----------------------------------------------------------------------
st.set_page_config(page_title="Optimización Parada Planta", page_icon="🏭", layout="wide")
st.title("🏭 Optimización de Parada de Planta")

horas_paro = st.sidebar.number_input("Duración del paro (horas)", min_value=1, max_value=500, value=36)
fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")
inicio_parada = datetime.combine(fecha_inicio, hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])

# ----------------------------------------------------------------------
# FUNCIONES AUXILIARES
# ----------------------------------------------------------------------
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

# ----------------------------------------------------------------------
# Paso 1-4: Descomposición de órdenes y distribución de horas por especialidad
# ----------------------------------------------------------------------
def descomponer_ordenes(df):
    actividades=[]
    for _,row in df.iterrows():
        # Dividir especialidades por coma y limpiar espacios
        especs=[e.strip().upper() for e in str(row["especialidad"]).replace("/,",",").replace("/",",").split(",")]
        total=row["duracion_h"]

        # Distribución de horas según número y combinación de especialidades
        if len(especs)==3: porcentajes=[0.5,0.3,0.2]
        elif len(especs)==2:
            if "MECANICA" in especs and "ELECTRICA" in especs: porcentajes=[0.65,0.35]
            elif "ELECTRICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            elif "MECANICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            else: porcentajes=[0.5,0.5]
        else: porcentajes=[1]

        # Crear una actividad independiente por especialidad
        for esp,pct in zip(especs,porcentajes):
            dur=total*pct
            # Regla de redondeo
            dur=int(dur) if dur-int(dur)<1.5 else int(dur)+1
            actividades.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["Centro planificación"],
                "especialidad":esp,
                "criticidad":str(row["criticidad"]).upper(),
                "duracion_h": dur,
                "duracion_total_orden": total   # <-- nueva columna
            })

    return pd.DataFrame(actividades)

# ----------------------------------------------------------------------
# OPTIMIZACIÓN - Asigna automáticamente técnicos
# ----------------------------------------------------------------------
def optimizar_actividades(df_actividades, horas_paro):
    dias_paro = ceil(horas_paro/24)
    capacidad_por_tecnico = 8*dias_paro  # máximo que un técnico puede trabajar

    model = cp_model.CpModel()
    horizon = horas_paro
    intervalos = {}
    resultados = []

    # Calcular cuantos técnicos se necesitan por actividad
    tecnico_counter = 0
    tecnico_map = {}

    for idx,row in df_actividades.iterrows():
        dur = row["duracion_h"]
        n_tecnicos = ceil(dur / capacidad_por_tecnico)
        fragment_dur = [dur/n_tecnicos]*n_tecnicos

        intervalos[idx] = []
        for f,fdur in enumerate(fragment_dur):
            s = model.NewIntVar(0,horizon,f"s_{idx}_{f}")
            e = model.NewIntVar(0,horizon,f"e_{idx}_{f}")
            interv = model.NewIntervalVar(s, ceil(fdur), e, f"int_{idx}_{f}")
            
            # Asignar técnico único para cada fragmento
            key = (row["centro"], row["especialidad"], idx, f)
            if key not in tecnico_map:
                tecnico_counter += 1
                tecnico_map[key] = tecnico_counter
            
            intervalos[idx].append((s,e,interv,f+1, tecnico_map[key]))

    # Restricción: No solapamiento por técnico
    for tecnico_id in set(tecnico_map.values()):
        tech_intervals = [i for idx_list in intervalos.values() for s,e,i,f,t_id in idx_list if t_id==tecnico_id]
        model.AddNoOverlap(tech_intervals)

    # Objetivo: minimizar makespan
    makespan = model.NewIntVar(0,horizon,"makespan")
    all_ends = [e for idx_list in intervalos.values() for s,e,i,f,t_id in idx_list]
    model.AddMaxEquality(makespan, all_ends)
    model.Minimize(makespan)

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for idx,row in df_actividades.iterrows():
            for s,e,i,f,t_id in intervalos[idx]:
                resultados.append({
                    **row,
                    "fragmento": f,
                    "start": solver.Value(s),
                    "end": solver.Value(e),
                    "tecnico_id": t_id
                })

    df_result = pd.DataFrame(resultados)
    return df_result

# ----------------------------------------------------------------------
# CRONOGRAMA POR HORAS
# ----------------------------------------------------------------------
def generar_cronograma_horas(df_result,horas_paro):
    if df_result.empty: return pd.DataFrame()
    tecnicos = df_result["tecnico_id"].unique()
    cronograma = pd.DataFrame(index=tecnicos, columns=range(horas_paro))
    for _,row in df_result.iterrows():
        t=row["tecnico_id"]
        for h in range(row["start"],row["end"]):
            if h<horas_paro:
                cronograma.loc[t,h] = row["actividad"]
    return cronograma.fillna("")

# ----------------------------------------------------------------------
# EJECUCIÓN APP
# ----------------------------------------------------------------------
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
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No se pudo generar un cronograma. Revisa los datos o la duración del paro.")
else:
    st.info("Cargar los dos archivos Excel para iniciar.")
