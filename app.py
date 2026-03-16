import streamlit as st
import pandas as pd
from datetime import datetime
from math import ceil
from ortools.sat.python import cp_model

st.set_page_config(page_title="Optimizador Paro Planta", layout="wide")
st.title("Optimización Parada de Planta")

# ---------------------------------------------------------
# PARAMETROS PARO
# ---------------------------------------------------------

st.sidebar.header("Parametros paro")

horas_paro = st.sidebar.number_input(
    "Duracion paro (horas)",
    min_value=1,
    max_value=500,
    value=36
)

fecha_inicio = st.sidebar.date_input("Fecha inicio paro")
hora_inicio = st.sidebar.time_input("Hora inicio paro")

inicio_paro = datetime.combine(fecha_inicio, hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo actividades SAP", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo zonas", type=["xlsx"])

# ---------------------------------------------------------
# LIMPIAR COLUMNAS
# ---------------------------------------------------------

def limpiar_columnas(df):
    df.columns = df.columns.str.strip().str.replace("\n"," ",regex=True)
    return df

# ---------------------------------------------------------
# CARGAR DATOS
# ---------------------------------------------------------

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

    df2 = df2[["Actividades","Zona","Sector"]]

    df = df1.merge(df2,on="Actividades",how="left")

    df = df.rename(columns={
        "Orden":"orden",
        "Actividades":"actividad",
        "TIEMPO (Hrs)":"duracion_h",
        "ESPECIALIDAD":"especialidad",
        "CRITICIDAD":"criticidad",
        "Centro planificación":"centro"
    })

    df["duracion_h"] = df["duracion_h"].fillna(1)

    return df

# ---------------------------------------------------------
# DESCOMPONER POR ESPECIALIDAD
# ---------------------------------------------------------

def descomponer_ordenes(df):

    actividades=[]

    for _,row in df.iterrows():

        especs=[e.strip().upper() for e in str(row["especialidad"]).replace("/",",").split(",")]

        total=row["duracion_h"]

        if len(especs)==3:
            porcentajes=[0.5,0.3,0.2]
        elif len(especs)==2:
            porcentajes=[0.6,0.4]
        else:
            porcentajes=[1]

        for esp,pct in zip(especs,porcentajes):

            dur=round(total*pct)

            actividades.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["centro"],
                "especialidad":esp,
                "duracion_h":dur
            })

    return pd.DataFrame(actividades)

# ---------------------------------------------------------
# FRAGMENTAR BLOQUES 8H
# ---------------------------------------------------------

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

# ---------------------------------------------------------
# OPTIMIZADOR
# ---------------------------------------------------------

def optimizar_paro(df_fragmentado, horas_paro):

    model = cp_model.CpModel()

    dias_paro = ceil(horas_paro / 24)
    capacidad_tecnico = dias_paro * 8

    max_tecnicos = 100
    tareas = len(df_fragmentado)

    # grupos actividad
    df_fragmentado["grupo"] = (
        df_fragmentado["orden"].astype(str) + "_" +
        df_fragmentado["actividad"].astype(str)
    )

    duraciones = df_fragmentado.groupby("grupo")["duracion"].sum()

    combos = df_fragmentado[["centro","especialidad"]].drop_duplicates()

    tecnicos = {}

    for _,row in combos.iterrows():

        c = row["centro"]
        e = row["especialidad"]

        tecnicos[(c,e)] = [f"{c}_{e}_T{i+1}" for i in range(max_tecnicos)]

    asignacion = {}

    # variables
    for i in range(tareas):

        c = df_fragmentado.iloc[i]["centro"]
        e = df_fragmentado.iloc[i]["especialidad"]

        for t in tecnicos[(c,e)]:

            asignacion[(i,t)] = model.NewBoolVar(f"a_{i}_{t}")

    # cada bloque tiene tecnico
    for i in range(tareas):

        c = df_fragmentado.iloc[i]["centro"]
        e = df_fragmentado.iloc[i]["especialidad"]

        model.Add(
            sum(asignacion[(i,t)] for t in tecnicos[(c,e)]) == 1
        )

    # capacidad tecnico
    for (c,e),lista_tecnicos in tecnicos.items():

        for t in lista_tecnicos:

            tareas_tecnico = [
                asignacion[(i,t)]
                for i in range(tareas)
                if (i,t) in asignacion
            ]

            if len(tareas_tecnico) > 0:

                model.Add(
                    sum(
                        asignacion[(i,t)] * int(df_fragmentado.iloc[i]["duracion"])
                        for i in range(tareas)
                        if (i,t) in asignacion
                    ) <= capacidad_tecnico
                )

    # continuidad de actividad
    grupos = df_fragmentado.groupby("grupo")

    for grupo_id,grupo in grupos:

        if duraciones[grupo_id] <= capacidad_tecnico:

            indices = grupo.index.tolist()

            if len(indices) > 1:

                for i in range(len(indices)-1):

                    a = indices[i]
                    b = indices[i+1]

                    c = df_fragmentado.loc[a,"centro"]
                    e = df_fragmentado.loc[a,"especialidad"]

                    for t in tecnicos[(c,e)]:

                        if (a,t) in asignacion and (b,t) in asignacion:

                            model.Add(
                                asignacion[(a,t)] == asignacion[(b,t)]
                            )

    # minimizar tecnicos
    tecnico_usado = []

    for (c,e),lista_tecnicos in tecnicos.items():

        for t in lista_tecnicos:

            tareas_tecnico = [
                asignacion[(i,t)]
                for i in range(tareas)
                if (i,t) in asignacion
            ]

            if len(tareas_tecnico) > 0:

                usado = model.NewBoolVar(f"usado_{t}")

                model.AddMaxEquality(usado, tareas_tecnico)

                tecnico_usado.append(usado)

    model.Minimize(sum(tecnico_usado))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60

    status = solver.Solve(model)

    resultado = []

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:

        for (i,t),var in asignacion.items():

            if solver.Value(var) == 1:

                row = df_fragmentado.iloc[i]

                resultado.append({
                    "Tecnico": t,
                    "Centro": row["centro"],
                    "Especialidad": row["especialidad"],
                    "Orden": row["orden"],
                    "Actividad": row["actividad"],
                    "Bloque": row["bloque"],
                    "Duracion": row["duracion"]
                })

    return pd.DataFrame(resultado)
# ---------------------------------------------------------
# EJECUCION
# ---------------------------------------------------------

if archivo1 and archivo2:

    df = cargar_datos(archivo1,archivo2)

    st.subheader("Datos SAP")
    st.dataframe(df)

    df_act = descomponer_ordenes(df)

    st.subheader("Actividades especialidad")
    st.dataframe(df_act)

    df_frag = fragmentar_actividades(df_act)

    st.subheader("Bloques trabajo")
    st.dataframe(df_frag)

    st.subheader("Optimización")

    df_opt = optimizar_paro(df_frag, horas_paro)

    if not df_opt.empty:

        st.dataframe(df_opt)

        st.success(f"Tecnicos requeridos: {df_opt['Tecnico'].nunique()}")

    else:

        st.error("El optimizador no encontró solución con las restricciones actuales")
