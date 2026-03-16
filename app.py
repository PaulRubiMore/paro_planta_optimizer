# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime
from ortools.sat.python import cp_model

# -----------------------------------------------------------------------------
# CONFIGURACION APP
# -----------------------------------------------------------------------------

st.set_page_config(page_title="Optimizador Paro Planta", layout="wide")
st.title("Optimización Parada de Planta")

# -----------------------------------------------------------------------------
# PARAMETROS DEL PARO
# -----------------------------------------------------------------------------

st.sidebar.header("Parametros del paro")

horas_paro = st.sidebar.number_input(
    "Duracion del paro (horas)",
    min_value=1,
    max_value=500,
    value=36
)

fecha_inicio = st.sidebar.date_input("Fecha inicio paro")
hora_inicio = st.sidebar.time_input("Hora inicio paro")

inicio_paro = datetime.combine(fecha_inicio, hora_inicio)

# -----------------------------------------------------------------------------
# CARGA ARCHIVOS
# -----------------------------------------------------------------------------

archivo1 = st.sidebar.file_uploader("Archivo SAP actividades", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo zonas", type=["xlsx"])

# -----------------------------------------------------------------------------
# LIMPIEZA COLUMNAS
# -----------------------------------------------------------------------------

def limpiar_columnas(df):

    df.columns = (
        df.columns
        .str.strip()
        .str.replace("\n"," ",regex=True)
    )

    return df

# -----------------------------------------------------------------------------
# CARGA DATOS
# -----------------------------------------------------------------------------

def cargar_datos(archivo1, archivo2):

    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)

    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)

    for col in df1.columns:
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col:"TIEMPO (Hrs)"})

    df1 = df1[df1["EJECUTOR"].str.contains("massy",case=False,na=False)]

    df1 = df1[[
        "Centro planificación",
        "Actividades",
        "Orden",
        "TIEMPO (Hrs)",
        "ESPECIALIDAD",
        "CRITICIDAD"
    ]]

    df2 = df2[[
        "Actividades",
        "Zona",
        "Sector"
    ]]

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

# -----------------------------------------------------------------------------
# DESCOMPOSICION POR ESPECIALIDAD
# -----------------------------------------------------------------------------

def descomponer_ordenes(df):

    actividades = []

    for _,row in df.iterrows():

        especs = [
            e.strip().upper()
            for e in str(row["especialidad"])
            .replace("/",",")
            .split(",")
        ]

        total = row["duracion_h"]

        if len(especs)==3:
            porcentajes=[0.5,0.3,0.2]

        elif len(especs)==2:
            porcentajes=[0.6,0.4]

        else:
            porcentajes=[1]

        for esp,pct in zip(especs,porcentajes):

            dur = round(total*pct)

            actividades.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["centro"],
                "especialidad":esp,
                "criticidad":row["criticidad"],
                "duracion_h":dur
            })

    return pd.DataFrame(actividades)

# -----------------------------------------------------------------------------
# FRAGMENTAR EN BLOQUES 8H
# -----------------------------------------------------------------------------

def fragmentar_actividades(df):

    fragmentos=[]

    for _,row in df.iterrows():

        horas=row["duracion_h"]
        bloque=1

        while horas>0:

            dur=min(8,horas)

            fragmentos.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["centro"],
                "especialidad":row["especialidad"],
                "bloque":bloque,
                "duracion":dur
            })

            horas-=dur
            bloque+=1

    return pd.DataFrame(fragmentos)

# -----------------------------------------------------------------------------
# OPTIMIZADOR ORTOOLS
# -----------------------------------------------------------------------------

def optimizar_paro(df_fragmentado, horas_paro):

    model = cp_model.CpModel()

    n = len(df_fragmentado)
    max_tecnicos = 100

    start=[]
    end=[]
    tecnico=[]

    for i,row in df_fragmentado.iterrows():

        dur=int(row["duracion"])

        s=model.NewIntVar(0,horas_paro,f"start_{i}")
        e=model.NewIntVar(0,horas_paro,f"end_{i}")
        t=model.NewIntVar(0,max_tecnicos-1,f"tec_{i}")

        model.Add(e==s+dur)

        start.append(s)
        end.append(e)
        tecnico.append(t)

    # no solapamiento

    for tec in range(max_tecnicos):

        intervalos=[]

        for i,row in df_fragmentado.iterrows():

            dur=int(row["duracion"])

            is_t=model.NewBoolVar(f"is_{i}_{tec}")

            model.Add(tecnico[i]==tec).OnlyEnforceIf(is_t)
            model.Add(tecnico[i]!=tec).OnlyEnforceIf(is_t.Not())

            intervalo=model.NewOptionalIntervalVar(
                start[i],
                dur,
                end[i],
                is_t,
                f"int_{i}_{tec}"
            )

            intervalos.append(intervalo)

        model.AddNoOverlap(intervalos)

    tecnico_usado=model.NewIntVar(0,max_tecnicos,"max_tecnico")

    model.AddMaxEquality(tecnico_usado,tecnico)

    model.Minimize(tecnico_usado)

    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=30

    status=solver.Solve(model)

    resultado=[]

    if status in [cp_model.OPTIMAL,cp_model.FEASIBLE]:

        for i,row in df_fragmentado.iterrows():

            resultado.append({
                "Tecnico":f"T{solver.Value(tecnico[i])+1}",
                "Orden":row["orden"],
                "Actividad":row["actividad"],
                "Centro":row["centro"],
                "Especialidad":row["especialidad"],
                "Bloque":row["bloque"],
                "Inicio_h":solver.Value(start[i]),
                "Fin_h":solver.Value(end[i]),
                "Duracion":row["duracion"]
            })

    return pd.DataFrame(resultado)

# -----------------------------------------------------------------------------
# EJECUCION
# -----------------------------------------------------------------------------

if archivo1 and archivo2:

    st.subheader("Parametros del paro")
    st.write("Duracion:", horas_paro)
    st.write("Inicio:", inicio_paro)

    df = cargar_datos(archivo1, archivo2)

    st.subheader("Datos cargados")
    st.dataframe(df)

    df_act = descomponer_ordenes(df)

    st.subheader("Actividades por especialidad")
    st.dataframe(df_act)

    df_frag = fragmentar_actividades(df_act)

    st.subheader("Bloques de trabajo (8h)")
    st.dataframe(df_frag)

    st.subheader("Optimización")

    df_opt = optimizar_paro(df_frag, horas_paro)

    st.dataframe(df_opt)

    st.success(f"Técnicos requeridos: {df_opt['Tecnico'].nunique()}")
