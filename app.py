
# =============================================================================
# OPTIMIZADOR DE PARO DE PLANTA
# =============================================================================

import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model

# -------------------------------------------------------------------------
# CONFIGURACIÓN APP
# -------------------------------------------------------------------------
st.set_page_config(page_title="Optimización de Paro", page_icon="🏭", layout="wide")
st.title("🏭 Planificador de Paros de Mantenimiento")

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])

horas_paro = st.sidebar.number_input("Horas totales del paro", value=36)
horas_tecnico_dia = st.sidebar.number_input("Horas técnico por día", value=8)

# -------------------------------------------------------------------------
# LIMPIAR COLUMNAS
# -------------------------------------------------------------------------
def limpiar_columnas(df):
    df.columns = df.columns.str.strip().str.replace("\n"," ",regex=True).str.replace("  "," ")
    return df

# -------------------------------------------------------------------------
# CARGAR DATOS
# -------------------------------------------------------------------------
def cargar_datos(archivo1, archivo2):

    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)

    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)

    for col in df1.columns:
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col:"TIEMPO (Hrs)"})

    df1 = df1[df1["EJECUTOR"].str.contains("massy", case=False, na=False)]

    df1 = df1[[
        "Centro planificación",
        "Actividades",
        "Orden",
        "TIEMPO (Hrs)",
        "ESPECIALIDAD",
        "CRITICIDAD"
    ]]

    df2 = df2[["Actividades","Zona","Sector"]]

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
# DESCOMPOSICIÓN POR ESPECIALIDAD
# -------------------------------------------------------------------------
def descomponer_ordenes(df):

    actividades = []

    for _,row in df.iterrows():

        especs = [
            e.strip().upper()
            for e in str(row["especialidad"])
            .replace("/,",",")
            .replace("/",",")
            .split(",")
        ]

        total = row["duracion_h"]

        if len(especs)==3:
            porcentajes=[0.5,0.3,0.2]

        elif len(especs)==2:

            if "MECANICA" in especs and "ELECTRICA" in especs:
                porcentajes=[0.65,0.35]

            elif "ELECTRICA" in especs and "INSTRUMENTACION" in especs:
                porcentajes=[0.6,0.4]

            elif "MECANICA" in especs and "INSTRUMENTACION" in especs:
                porcentajes=[0.6,0.4]

            else:
                porcentajes=[0.5,0.5]

        else:
            porcentajes=[1]

        for esp,pct in zip(especs,porcentajes):

            dur = total * pct

            actividades.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["centro"],
                "especialidad":esp,
                "criticidad":str(row["criticidad"]).upper(),
                "duracion_h":round(dur,1)
            })

    return pd.DataFrame(actividades)

# -------------------------------------------------------------------------
# ORDENAR POR CRITICIDAD
# -------------------------------------------------------------------------
def ordenar_criticidad(df):

    prioridad = {
        "ALTA":1,
        "MEDIA":2,
        "BAJA":3
    }

    df["prioridad"] = df["criticidad"].map(prioridad)

    df = df.sort_values("prioridad")

    return df.drop(columns="prioridad")

# -------------------------------------------------------------------------
# FRAGMENTAR ACTIVIDADES EN BLOQUES DE 8H
# -------------------------------------------------------------------------
def fragmentar_actividades(df,max_horas=8):

    bloques=[]

    for _,row in df.iterrows():

        horas=row["duracion_h"]
        bloque=0

        while horas>0:

            dur=min(max_horas,horas)

            bloques.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["centro"],
                "especialidad":row["especialidad"],
                "duracion":dur,
                "bloque":bloque
            })

            horas-=dur
            bloque+=1

    return pd.DataFrame(bloques)

# -------------------------------------------------------------------------
# OPTIMIZACIÓN CP-SAT
# -------------------------------------------------------------------------
def optimizar_paro(df,horas_paro=36,max_tecnicos=30):

    model=cp_model.CpModel()

    n=len(df)

    start=[]
    end=[]
    interval=[]
    tecnico=[]

    for i in range(n):

        dur=int(df.loc[i,"duracion"])

        s=model.NewIntVar(0,horas_paro,f"start{i}")
        e=model.NewIntVar(0,horas_paro,f"end{i}")

        model.Add(e==s+dur)

        start.append(s)
        end.append(e)

        interval.append(model.NewIntervalVar(s,dur,e,f"interval{i}"))

        tecnico.append(model.NewIntVar(0,max_tecnicos-1,f"tec{i}"))

    for i in range(n):
        model.Add(end[i]<=horas_paro)

    for t in range(max_tecnicos):

        tareas=[]

        for i in range(n):

            b=model.NewBoolVar(f"t{t}_{i}")

            model.Add(tecnico[i]==t).OnlyEnforceIf(b)
            model.Add(tecnico[i]!=t).OnlyEnforceIf(b.Not())

            tareas.append(interval[i])

        model.AddNoOverlap(tareas)

    usados=[]

    for t in range(max_tecnicos):

        u=model.NewBoolVar(f"used{t}")
        usados.append(u)

    model.Minimize(sum(usados))

    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=15

    result=solver.Solve(model)

    cronograma=[]

    if result==cp_model.OPTIMAL or result==cp_model.FEASIBLE:

        for i in range(n):

            cronograma.append({
                "orden":df.loc[i,"orden"],
                "actividad":df.loc[i,"actividad"],
                "centro":df.loc[i,"centro"],
                "especialidad":df.loc[i,"especialidad"],
                "tecnico":solver.Value(tecnico[i]),
                "inicio":solver.Value(start[i]),
                "fin":solver.Value(end[i]),
                "duracion":df.loc[i,"duracion"]
            })

    return pd.DataFrame(cronograma)

# -------------------------------------------------------------------------
# EJECUCIÓN
# -------------------------------------------------------------------------
if archivo1 and archivo2:

    df=cargar_datos(archivo1,archivo2)

    st.subheader("Datos cargados")
    st.dataframe(df)

    df_actividades=descomponer_ordenes(df)

    df_actividades=ordenar_criticidad(df_actividades)

    st.subheader("Actividades descompuestas")
    st.dataframe(df_actividades)

    bloques=fragmentar_actividades(df_actividades,horas_tecnico_dia)

    st.subheader("Bloques de trabajo")
    st.dataframe(bloques)

    st.subheader("Ejecutando optimización")

    cronograma=optimizar_paro(bloques,horas_paro)

    st.subheader("Cronograma optimizado")

    st.dataframe(cronograma)

    st.write("Total tareas programadas:",len(cronograma))
