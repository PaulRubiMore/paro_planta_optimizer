# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA - ASIGNA AUTOMÁTICAMENTE TÉCNICOS
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px

# -------------------------------------------------------------------------
# CONFIGURACIÓN APP
# -------------------------------------------------------------------------
st.set_page_config(page_title="Optimización Parada Planta", page_icon="🏭", layout="wide")
st.title("🏭 Optimización de Parada de Planta")

horas_paro = st.sidebar.number_input("Duración del paro (horas)", min_value=1, max_value=500, value=36)
fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")
inicio_parada = datetime.combine(fecha_inicio, hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])

# -------------------------------------------------------------------------
# FUNCIONES AUXILIARES
# -------------------------------------------------------------------------
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
                            "ESPECIALIDAD":"especialidad","CRITICIDAD":"criticidad"})
    df["duracion_h"] = df["duracion_h"].fillna(1).astype(float)
    return df

# -------------------------------------------------------------------------
# Paso 1-4: Descomposición de órdenes y distribución de horas por especialidad
# -------------------------------------------------------------------------
def descomponer_ordenes(df):
    actividades=[]
    for _,row in df.iterrows():
        # Dividir especialidades
        especs=[e.strip().upper() for e in str(row["especialidad"]).replace("/,",",").replace("/",",").split(",")]
        total=row["duracion_h"]

        # Distribución de horas según combinación
        if len(especs)==3: porcentajes=[0.5,0.3,0.2]
        elif len(especs)==2:
            if "MECANICA" in especs and "ELECTRICA" in especs: porcentajes=[0.65,0.35]
            elif "ELECTRICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            elif "MECANICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            else: porcentajes=[0.5,0.5]
        else: porcentajes=[1]

        # Crear actividad por especialidad
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

# -------------------------------------------------------------------------
# OPTIMIZACIÓN CP-SAT
# -------------------------------------------------------------------------
def optimizar_actividades(df_actividades, horas_paro):
    dias_paro = ceil(horas_paro/24)
    capacidad_diaria = 8  # horas por día
    capacidad_total = dias_paro*capacidad_diaria

    model = cp_model.CpModel()
    horizon = horas_paro
    intervalos = {}
    resultados = []

    # Crear fragmentos de actividades según capacidad total diaria
    for idx,row in df_actividades.iterrows():
        dur = row["duracion_h"]
        n_fragmentos = ceil(dur/capacidad_total)
        # cada fragmento máximo capacidad_total
        frag_dur = [capacidad_total]*(n_fragmentos-1) + [dur-(n_fragmentos-1)*capacidad_total]
        intervalos[idx] = []
        for f,fdur in enumerate(frag_dur):
            s = model.NewIntVar(0,horizon,f"s_{idx}_{f}")
            e = model.NewIntVar(0,horizon,f"e_{idx}_{f}")
            interv = model.NewIntervalVar(s, fdur, e, f"int_{idx}_{f}")
            intervalos[idx].append((s,e,interv,f+1,fdur))

    # Agrupar por centro y especialidad
    grupos = df_actividades.groupby(["centro","especialidad"]).groups
    for (c,e), idxs in grupos.items():
        tech_intervals = []
        for idx in idxs:
            for s,e_,i,frag,fdur in intervalos[idx]:
                tech_intervals.append(i)
        model.AddNoOverlap(tech_intervals)

    # Objetivo: minimizar makespan
    makespan = model.NewIntVar(0,horizon,"makespan")
    all_ends = [e_ for idxs in intervalos.values() for s,e_,i,frag,fdur in idxs]
    model.AddMaxEquality(makespan,all_ends)
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        tecnico_counter = 0
        for idx,row in df_actividades.iterrows():
            for s,e_,i,frag,fdur in intervalos[idx]:
                # determinar cuantos técnicos necesitamos para esa actividad
                n_tecnicos = ceil(fdur/capacidad_diaria)
                for t in range(n_tecnicos):
                    resultados.append({
                        **row,
                        "fragmento": frag,
                        "start": solver.Value(s)+t*capacidad_diaria,
                        "end": min(solver.Value(s)+(t+1)*capacidad_diaria, solver.Value(e_)),
                        "tecnico_id": tecnico_counter+1
                    })
                    tecnico_counter += 1

    df_result = pd.DataFrame(resultados)
    return df_result

# -------------------------------------------------------------------------
# CRONOGRAMA POR HORAS
# -------------------------------------------------------------------------
def generar_cronograma_horas(df_result,horas_paro):
    if df_result.empty:
        return pd.DataFrame()
    tecnicos = df_result["tecnico_id"].unique()
    cronograma = pd.DataFrame(index=tecnicos, columns=range(horas_paro))
    for _,row in df_result.iterrows():
        t=row["tecnico_id"]
        for h in range(int(row["start"]),int(row["end"])):
            if h<horas_paro:
                cronograma.loc[t,h]=row["actividad"]
    return cronograma.fillna("")

# -------------------------------------------------------------------------
# EJECUCIÓN APP
# -------------------------------------------------------------------------
if archivo1 and archivo2:
    df=cargar_datos(archivo1,archivo2)
    st.subheader("Datos filtrados Massy Energy")
    st.dataframe(df)

    if st.button("Generar Cronograma"):
        df_actividades=descomponer_ordenes(df)
        st.subheader("Actividades descompuestas por especialidad")
        st.dataframe(df_actividades)

        st.subheader("Optimizando actividades...")
        resultado=optimizar_actividades(df_actividades,horas_paro)

        if not resultado.empty:
            resultado["inicio_real"] = resultado["start"].apply(lambda x: inicio_parada + timedelta(hours=x))
            resultado["fin_real"] = resultado["end"].apply(lambda x: inicio_parada + timedelta(hours=x))
            st.subheader("Cronograma optimizado")
            st.dataframe(resultado)

            cronograma_horas = generar_cronograma_horas(resultado, horas_paro)
            st.subheader("Cronograma por técnico y hora")
            st.dataframe(cronograma_horas)

            fig = px.timeline(resultado,
                              x_start="inicio_real",
                              x_end="fin_real",
                              y="tecnico_id",
                              color="especialidad",
                              title="Cronograma de Parada")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig,use_container_width=True)
        else:
            st.warning("No se pudo generar un cronograma. Revisa los datos o la duración del paro.")
else:
    st.info("Cargar los dos archivos Excel para iniciar.")
