# =============================================================================
# APP STREAMLIT - OPTIMIZACIÓN PARADA DE PLANTA
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px

# -------------------------------------------------------------------------
# Configuración de la app
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
# Funciones auxiliares
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
    df = df.rename(columns={
        "Orden":"orden",
        "Actividades":"actividad",
        "TIEMPO (Hrs)":"duracion_h",
        "ESPECIALIDAD":"especialidad",
        "CRITICIDAD":"criticidad",
        "Centro planificación":"centro"
    })
    df["duracion_h"] = df["duracion_h"].fillna(1).astype(float)
    return df

# -------------------------------------------------------------------------
# Paso 1-4: Descomposición de órdenes
# -------------------------------------------------------------------------
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

# -------------------------------------------------------------------------
# Crear bloques diarios y técnicos necesarios
# -------------------------------------------------------------------------
def crear_bloques(df_actividades, horas_paro):
    dias_paro = ceil(horas_paro / 24)
    capacidad_dia = 8
    capacidad_tecnico = dias_paro * capacidad_dia
    bloques=[]
    for _,row in df_actividades.iterrows():
        dur_total = row["duracion_h"]
        min_tecnicos = ceil(dur_total / capacidad_tecnico)

        for t in range(min_tecnicos):
            horas_restantes = dur_total - t*capacidad_tecnico
            dur_tecnico = min(capacidad_tecnico, horas_restantes)
            for d in range(dias_paro):
                inicio = d*capacidad_dia
                fin = inicio + min(capacidad_dia, dur_tecnico - d*capacidad_dia)
                if fin > inicio:
                    bloques.append({
                        "orden": row["orden"],
                        "actividad": row["actividad"],
                        "centro": row["centro"],
                        "especialidad": row["especialidad"],
                        "tecnico_idx": t+1,
                        "dia": d+1,
                        "inicio_rel": inicio,
                        "fin_rel": fin
                    })
    return pd.DataFrame(bloques)

# -------------------------------------------------------------------------
# Optimización con CP-SAT
# -------------------------------------------------------------------------
def optimizar(bloques):
    model = cp_model.CpModel()
    interval_vars={}
    for idx,row in bloques.iterrows():
        start = model.NewIntVar(row["inicio_rel"], row["fin_rel"], f'start_{idx}')
        end = model.NewIntVar(row["inicio_rel"], row["fin_rel"], f'end_{idx}')
        interval = model.NewIntervalVar(start, row["fin_rel"]-row["inicio_rel"], end, f'int_{idx}')
        interval_vars[idx]=(start,end,interval)

    for (centro, esp, tec), g in bloques.groupby(["centro","especialidad","tecnico_idx"]):
        vars_tecnico = [interval_vars[idx][2] for idx in g.index]
        if vars_tecnico:
            model.AddNoOverlap(vars_tecnico)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=30
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        resultados=[]
        for idx,row in bloques.iterrows():
            s,e,_ = interval_vars[idx]
            resultados.append({
                **row,
                "start": solver.Value(s),
                "end": solver.Value(e),
                "inicio_real": inicio_parada + timedelta(hours=solver.Value(s)),
                "fin_real": inicio_parada + timedelta(hours=solver.Value(e))
            })
        return pd.DataFrame(resultados)
    else:
        return pd.DataFrame()

# -------------------------------------------------------------------------
# Cronograma por técnico y hora
# -------------------------------------------------------------------------
def generar_cronograma(df_result, horas_paro):
    if df_result.empty: return pd.DataFrame()
    tecnicos = df_result["tecnico_idx"].unique()
    cronograma = pd.DataFrame(index=tecnicos, columns=range(horas_paro))
    for _,row in df_result.iterrows():
        t = row["tecnico_idx"]
        for h in range(int(row["start"]), int(row["end"])):
            if h < horas_paro:
                cronograma.loc[t,h] = row["actividad"]
    return cronograma.fillna("")

# -------------------------------------------------------------------------
# Ejecución app
# -------------------------------------------------------------------------
if archivo1 and archivo2:
    df = cargar_datos(archivo1, archivo2)
    st.subheader("Datos filtrados Massy Energy")
    st.dataframe(df)

    if st.button("Generar Cronograma"):
        df_actividades = descomponer_ordenes(df)
        st.subheader("Actividades descompuestas por especialidad")
        st.dataframe(df_actividades)

        st.subheader("Creando bloques y asignando técnicos...")
        bloques = crear_bloques(df_actividades, horas_paro)
        st.dataframe(bloques)

        st.subheader("Optimizando actividades...")
        resultado = optimizar(bloques)

        if not resultado.empty:
            st.subheader("Cronograma optimizado")
            st.dataframe(resultado)
            
            cronograma_horas = generar_cronograma(resultado, horas_paro)
            st.subheader("Cronograma por técnico y hora")
            st.dataframe(cronograma_horas)

            fig = px.timeline(resultado,
                              x_start="inicio_real",
                              x_end="fin_real",
                              y="tecnico_idx",
                              color="especialidad",
                              title="Cronograma de Parada")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig,use_container_width=True)
        else:
            st.warning("No se pudo generar un cronograma. Revisa los datos o la duración del paro.")
else:
    st.info("Cargar los dos archivos Excel para iniciar.")
