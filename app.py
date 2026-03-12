# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA - ASIGNA AUTOMÁTICAMENTE TÉCNICOS
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
st.set_page_config(page_title="Optimización Parada Planta", page_icon="🏭", layout="wide")
st.title("🏭 Optimización de Parada de Planta")

horas_paro = st.sidebar.number_input("Duración del paro (horas)", min_value=1, max_value=500, value=36)
fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")
inicio_parada = datetime.combine(fecha_inicio, hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])

# -----------------------------------------------------------------------------  
# FUNCIONES AUXILIARES
# -----------------------------------------------------------------------------  
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

# -----------------------------------------------------------------------------  
# Paso 1-4: Descomposición de órdenes y distribución de horas por especialidad
# -----------------------------------------------------------------------------  
def descomponer_ordenes(df):
    actividades=[]
    for _,row in df.iterrows():
        # Dividir especialidades por coma o barra
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

        # Crear actividad independiente por especialidad
        for esp,pct in zip(especs,porcentajes):
            dur=total*pct
            # Redondeo: <1.5 hacia abajo, >=1.5 hacia arriba
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

# -----------------------------------------------------------------------------  
# OPTIMIZACIÓN AUTOMÁTICA
# -----------------------------------------------------------------------------  
def optimizar_actividades(df_actividades, horas_paro):
    dias_paro = ceil(horas_paro/8)  # días de 8h para técnico
    capacidad_por_tecnico = dias_paro*8  # total por técnico

    model = cp_model.CpModel()
    horizon = int(df_actividades["duracion_h"].sum()*1.2)  # suficiente para fragmentar
    intervalos={}
    resultados=[]

    # Priorizar por criticidad: ALTA > MEDIA > BAJA
    df_actividades = df_actividades.copy()
    criticidad_map = {"ALTA":0, "MEDIA":1, "BAJA":2}
    df_actividades["prioridad"] = df_actividades["criticidad"].map(criticidad_map).fillna(2)
    df_actividades = df_actividades.sort_values(["prioridad"])

    tecnico_counter=1  # contador global de técnicos

    for idx,row in df_actividades.iterrows():
        dur=row["duracion_h"]
        # cuántos técnicos necesito para esta actividad
        n_tecnicos = ceil(dur/capacidad_por_tecnico)
        frag_dur=[capacidad_por_tecnico]*(n_tecnicos-1)+[dur-(n_tecnicos-1)*capacidad_por_tecnico]
        intervalos[idx]=[]
        for f,fdur in enumerate(frag_dur):
            s=model.NewIntVar(0,horizon,f"s_{idx}_{f}")
            e=model.NewIntVar(0,horizon,f"e_{idx}_{f}")
            interv=model.NewIntervalVar(s,fdur,e,f"int_{idx}_{f}")
            intervalos[idx].append({
                "s": s, "e": e, "i": interv,
                "tecnico_id": tecnico_counter
            })
            tecnico_counter +=1

    # Restricción: un técnico solo trabaja en un centro/especialidad a la vez
    grupos = df_actividades.groupby(["centro","especialidad"]).groups
    for (c,e), idxs in grupos.items():
        tech_intervals=[]
        for idx in idxs:
            for frag in intervalos[idx]:
                tech_intervals.append(frag["i"])
        model.AddNoOverlap(tech_intervals)

    # Minimizar makespan
    makespan = model.NewIntVar(0,horizon,"makespan")
    all_ends = [frag["e"] for idx in intervalos for frag in intervalos[idx]]
    model.AddMaxEquality(makespan, all_ends)
    model.Minimize(makespan)

    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=30
    status = solver.Solve(model)

    # Guardar resultados
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for idx,row in df_actividades.iterrows():
            for frag in intervalos[idx]:
                resultados.append({
                    **row,
                    "tecnico_id": frag["tecnico_id"],
                    "start": solver.Value(frag["s"]),
                    "end": solver.Value(frag["e"])
                })

    df_result = pd.DataFrame(resultados)
    return df_result

# -----------------------------------------------------------------------------  
# CRONOGRAMA POR HORAS
# -----------------------------------------------------------------------------  
def generar_cronograma_horas(df_result,horas_paro):
    if df_result.empty:
        return pd.DataFrame()
    tecnicos = df_result["tecnico_id"].unique()
    cronograma=pd.DataFrame(index=tecnicos, columns=range(horas_paro))
    for _,row in df_result.iterrows():
        t=row["tecnico_id"]
        for h in range(int(row["start"]), int(row["end"])):
            if h<horas_paro: cronograma.loc[t,h]=row["actividad"]
    return cronograma.fillna("")

# -----------------------------------------------------------------------------  
# EJECUCIÓN APP
# -----------------------------------------------------------------------------  
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

            cronograma_horas=generar_cronograma_horas(resultado,horas_paro)
            st.subheader("Cronograma por técnico y hora")
            st.dataframe(cronograma_horas)

            fig=px.timeline(resultado,x_start="inicio_real",x_end="fin_real",y="tecnico_id",
                            color="especialidad",title="Cronograma de Parada")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig,use_container_width=True)
        else:
            st.warning("No se pudo generar un cronograma. Revisa los datos o la duración del paro.")
else:
    st.info("Cargar los dos archivos Excel para iniciar.")
