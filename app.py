# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA CON DIAGNÓSTICO REAL
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px


# -----------------------------------------------------------------------------
# CONFIGURACIÓN
# -----------------------------------------------------------------------------

st.set_page_config(page_title="Optimización Parada Planta", page_icon="🏭", layout="wide")

st.title("🏭 Optimización de Parada de Planta")

horas_paro = st.sidebar.number_input("Duración del paro (horas)",1,500,36)

fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")

inicio_parada = datetime.combine(fecha_inicio,hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo",type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades",type=["xlsx"])


# -----------------------------------------------------------------------------
# LIMPIAR COLUMNAS
# -----------------------------------------------------------------------------

def limpiar_columnas(df):

    df.columns = df.columns.str.strip()
    df.columns = df.columns.str.replace("\n"," ",regex=True)
    df.columns = df.columns.str.replace("  "," ")

    return df


# -----------------------------------------------------------------------------
# CARGAR DATOS
# -----------------------------------------------------------------------------

def cargar_datos(archivo1,archivo2):

    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)

    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)

    for col in df1.columns:
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col:"TIEMPO (Hrs)"})

    df1 = df1[[
        "Centro planificación",
        "Actividades",
        "Orden",
        "TIEMPO (Hrs)",
        "ESTADO",
        "ESPECIALIDAD",
        "EJECUTOR",
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


# -----------------------------------------------------------------------------
# DESCOMPONER ORDENES
# -----------------------------------------------------------------------------

def descomponer_ordenes(df):

    actividades=[]

    for _,row in df.iterrows():

        especs = str(row["especialidad"]).replace("/",",").split(",")
        especs = [e.strip().upper() for e in especs]

        total = row["duracion_h"]

        if len(especs)==3:
            porcentajes=[0.5,0.3,0.2]

        elif len(especs)==2:

            if "MECANICA" in especs and "ELECTRICA" in especs:
                porcentajes=[0.65,0.35]

            elif "ELECTRICA" in especs and "INSTRUMENTACION" in especs:
                porcentajes=[0.6,0.4]

            else:
                porcentajes=[0.5,0.5]

        else:
            porcentajes=[1]

        for esp,pct in zip(especs,porcentajes):

            dur = total*pct

            if dur-int(dur)<1.5:
                dur=int(dur)
            else:
                dur=int(dur)+1

            actividades.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["centro"],
                "especialidad":esp,
                "criticidad":str(row["criticidad"]).upper(),
                "duracion_h":dur
            })

    return pd.DataFrame(actividades)


# -----------------------------------------------------------------------------
# DIAGNOSTICO
# -----------------------------------------------------------------------------

def diagnostico(df_actividades,horas_paro):

    dias_paro = ceil(horas_paro/24)
    capacidad = dias_paro*8

    reporte=[]

    for (centro,esp),grupo in df_actividades.groupby(["centro","especialidad"]):

        total = grupo["duracion_h"].sum()
        max_act = grupo["duracion_h"].max()

        tecnicos = ceil(total/capacidad)

        reporte.append({
            "Centro":centro,
            "Especialidad":esp,
            "Horas requeridas":total,
            "Actividad más larga":max_act,
            "Capacidad técnico":capacidad,
            "Técnicos necesarios":tecnicos
        })

    return pd.DataFrame(reporte)


# -----------------------------------------------------------------------------
# OPTIMIZADOR
# -----------------------------------------------------------------------------

def optimizar(df_actividades,horas_paro):

    model = cp_model.CpModel()

    dias_paro = ceil(horas_paro/24)
    capacidad = dias_paro*8

    tecnicos={}

    for (c,esp),grupo in df_actividades.groupby(["centro","especialidad"]):

        total=grupo["duracion_h"].sum()

        n=ceil(total/capacidad)
        n=max(1,n)

        tecnicos.setdefault(c,{})
        tecnicos[c][esp]=[f"{c}_{esp}_T{i}" for i in range(n)]

    intervalos={}
    asignaciones={}

    for i,row in df_actividades.iterrows():

        c=row["centro"]
        esp=row["especialidad"]
        dur=int(row["duracion_h"])

        for t in tecnicos[c][esp]:

            start=model.NewIntVar(0,horas_paro,f"s_{i}_{t}")
            end=model.NewIntVar(0,horas_paro,f"e_{i}_{t}")
            assigned=model.NewBoolVar(f"a_{i}_{t}")

            interval=model.NewOptionalIntervalVar(start,dur,end,assigned,f"int_{i}_{t}")

            intervalos[(i,t)]=interval
            asignaciones[(i,t)]=(start,end,assigned)

    for i,row in df_actividades.iterrows():

        c=row["centro"]
        esp=row["especialidad"]

        model.AddBoolOr([asignaciones[(i,t)][2] for t in tecnicos[c][esp]])

    for c in tecnicos:

        for esp in tecnicos[c]:

            for t in tecnicos[c][esp]:

                lista=[]

                for i,row in df_actividades.iterrows():

                    if row["centro"]==c and row["especialidad"]==esp:

                        if (i,t) in intervalos:
                            lista.append(intervalos[(i,t)])

                if len(lista)>1:
                    model.AddNoOverlap(lista)

    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=60

    status=solver.Solve(model)

    if status not in [cp_model.OPTIMAL,cp_model.FEASIBLE]:

        st.error("❌ No se pudo generar un cronograma")

        st.subheader("🔎 Diagnóstico del problema")

        df_diag = diagnostico(df_actividades,horas_paro)

        st.dataframe(df_diag)

        st.stop()

    cronograma=[]

    for (i,t),(start,end,assigned) in asignaciones.items():

        if solver.Value(assigned)==1:

            row=df_actividades.loc[i]

            cronograma.append({

                "Orden":row["orden"],
                "Actividad":row["actividad"],
                "Centro":row["centro"],
                "Especialidad":row["especialidad"],
                "Tecnico":t,
                "Inicio":inicio_parada+timedelta(hours=solver.Value(start)),
                "Fin":inicio_parada+timedelta(hours=solver.Value(end))
            })

    return pd.DataFrame(cronograma)


# -----------------------------------------------------------------------------
# EJECUCIÓN
# -----------------------------------------------------------------------------

if archivo1 and archivo2:

    df=cargar_datos(archivo1,archivo2)

    df_actividades=descomponer_ordenes(df)

    st.subheader("Actividades generadas")
    st.write("Total actividades:",len(df_actividades))

    if st.button("🚀 Ejecutar optimización"):

        st.info("Calculando cronograma...")

        cronograma=optimizar(df_actividades,horas_paro)

        st.success("Cronograma generado")

        st.dataframe(cronograma)

        fig=px.timeline(
            cronograma,
            x_start="Inicio",
            x_end="Fin",
            y="Tecnico",
            color="Especialidad",
            text="Orden"
        )

        fig.update_yaxes(autorange="reversed")

        st.plotly_chart(fig,use_container_width=True)
