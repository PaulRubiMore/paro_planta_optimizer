# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA - OR-TOOLS CP-SAT CON CAPACIDAD DIARIA
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px

st.set_page_config(page_title="Optimización Parada Planta", page_icon="🏭", layout="wide")
st.title("🏭 Optimización de Parada de Planta")

# ---------------------------- INPUTS ----------------------------
horas_paro = st.sidebar.number_input("Duración del paro (horas)", min_value=1, max_value=500, value=36)
fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")
inicio_parada = datetime.combine(fecha_inicio, hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])

# ---------------------------- AUX ----------------------------
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
    df = df.rename(columns={"Orden":"orden","Actividades":"actividad","TIEMPO (Hrs)":"duracion_h",
                            "ESPECIALIDAD":"especialidad","CRITICIDAD":"criticidad","Centro planificación":"centro"})
    df["duracion_h"] = df["duracion_h"].fillna(1).astype(float)
    return df

# ------------------- DESCOMPOSICIÓN -------------------
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
                "centro":row["centro"],
                "especialidad":esp,
                "criticidad":str(row["criticidad"]).upper(),
                "duracion_h": dur,
                "duracion_total_orden": total
            })
    return pd.DataFrame(actividades)

# ------------------- OPTIMIZADOR CP-SAT -------------------
def optimizar_con_reglas(df_actividades, horas_paro):
    dias_paro = ceil(horas_paro/24)
    capacidad_diaria = 8
    capacidad_total = dias_paro * capacidad_diaria

    model = cp_model.CpModel()
    all_tareas = []

    tecnico_counter = {}  # Para crear técnicos por centro/especialidad

    for idx,row in df_actividades.iterrows():
        dur_restante = row["duracion_h"]
        centro = row["centro"]
        esp = row["especialidad"]
        key = f"{centro}_{esp}"
        if key not in tecnico_counter:
            tecnico_counter[key] = 1

        while dur_restante > 0:
            dur_fragment = min(dur_restante, capacidad_total)  # max que un técnico puede cubrir en todo el paro
            s = model.NewIntVar(0, horas_paro, f's_{idx}_{tecnico_counter[key]}')
            e = model.NewIntVar(0, horas_paro, f'e_{idx}_{tecnico_counter[key]}')
            interval = model.NewIntervalVar(s, dur_fragment, e, f'int_{idx}_{tecnico_counter[key]}')
            all_tareas.append({
                "interval": interval,
                "start": s,
                "end": e,
                "orden": row["orden"],
                "actividad": row["actividad"],
                "centro": centro,
                "especialidad": esp,
                "tecnico_id": f"{centro}_{esp}_T{tecnico_counter[key]}",
                "dur_fragment": dur_fragment
            })
            dur_restante -= dur_fragment
            tecnico_counter[key] += 1

    # Restricción: No-overlap por técnico
    tech_intervals = {}
    for t in all_tareas:
        t_id = t["tecnico_id"]
        if t_id not in tech_intervals: tech_intervals[t_id] = []
        tech_intervals[t_id].append(t["interval"])
    for t_id, ivs in tech_intervals.items():
        model.AddNoOverlap(ivs)

    # Minimizar makespan
    makespan = model.NewIntVar(0, horas_paro, "makespan")
    model.AddMaxEquality(makespan, [t["end"] for t in all_tareas])
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    resultados=[]
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for t in all_tareas:
            resultados.append({
                "orden": t["orden"],
                "actividad": t["actividad"],
                "centro": t["centro"],
                "especialidad": t["especialidad"],
                "tecnico_id": t["tecnico_id"],
                "start": solver.Value(t["start"]),
                "end": solver.Value(t["end"])
            })
    return pd.DataFrame(resultados)

# ------------------- CRONOGRAMA -------------------
def generar_cronograma_horas(df_result, horas_paro):
    tecnicos = df_result["tecnico_id"].unique()
    cronograma=pd.DataFrame(index=tecnicos, columns=range(horas_paro))
    for _,row in df_result.iterrows():
        t=row["tecnico_id"]
        for h in range(int(row["start"]), int(row["end"])):
            if h<horas_paro: cronograma.loc[t,h]=row["actividad"]
    return cronograma.fillna("")

# ------------------- EJECUCIÓN APP -------------------
if archivo1 and archivo2:
    df=cargar_datos(archivo1,archivo2)
    st.subheader("Datos filtrados Massy Energy")
    st.dataframe(df)

    if st.button("Generar Cronograma"):
        df_actividades = descomponer_ordenes(df)
        st.subheader("Actividades descompuestas por especialidad")
        st.dataframe(df_actividades)

        st.subheader("Optimizando actividades con OR-Tools CP-SAT...")
        resultado = optimizar_con_reglas(df_actividades, horas_paro)

        if not resultado.empty:
            resultado["inicio_real"] = resultado["start"].apply(lambda x: inicio_parada + timedelta(hours=x))
            resultado["fin_real"] = resultado["end"].apply(lambda x: inicio_parada + timedelta(hours=x))
            st.subheader("Cronograma optimizado")
            st.dataframe(resultado)

            cronograma_horas = generar_cronograma_horas(resultado, horas_paro)
            st.subheader("Cronograma por técnico y hora")
            st.dataframe(cronograma_horas)

            fig = px.timeline(resultado, x_start="inicio_real", x_end="fin_real",
                              y="tecnico_id", color="especialidad", title="Cronograma de Parada")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No se pudo generar un cronograma. Revisa los datos o la duración del paro.")
else:
    st.info("Cargar los dos archivos Excel para iniciar.")
