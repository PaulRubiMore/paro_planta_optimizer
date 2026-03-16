# =============================================================================
# OPTIMIZADOR PARADA DE PLANTA + DIAGNOSTICO REAL
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px


st.set_page_config(page_title="Optimización Parada Planta", layout="wide")

st.title("Optimización Parada de Planta")


# -----------------------------------------------------------------------------
# INPUTS
# -----------------------------------------------------------------------------

horas_paro = st.sidebar.number_input("Duración paro (horas)",1,500,36)

fecha_inicio = st.sidebar.date_input("Fecha inicio")
hora_inicio = st.sidebar.time_input("Hora inicio")

inicio_parada = datetime.combine(fecha_inicio,hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo OT",type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo actividades",type=["xlsx"])


# -----------------------------------------------------------------------------
# LIMPIAR COLUMNAS
# -----------------------------------------------------------------------------

def limpiar(df):

    df.columns = df.columns.str.strip()
    df.columns = df.columns.str.replace("\n"," ",regex=True)

    return df


# -----------------------------------------------------------------------------
# CARGA
# -----------------------------------------------------------------------------

def cargar_datos(a1,a2):

    df1 = pd.read_excel(a1)
    df2 = pd.read_excel(a2)

    df1 = limpiar(df1)
    df2 = limpiar(df2)

    for c in df1.columns:
        if "TIEMPO" in c.upper():
            df1 = df1.rename(columns={c:"TIEMPO"})

    df1 = df1[[
        "Centro planificación",
        "Actividades",
        "Orden",
        "TIEMPO",
        "ESPECIALIDAD",
        "CRITICIDAD"
    ]]

    df = df1.rename(columns={
        "Centro planificación":"centro",
        "Actividades":"actividad",
        "Orden":"orden",
        "TIEMPO":"duracion",
        "ESPECIALIDAD":"especialidad",
        "CRITICIDAD":"criticidad"
    })

    df["duracion"] = df["duracion"].fillna(1)

    return df


# -----------------------------------------------------------------------------
# DESCOMPONER
# -----------------------------------------------------------------------------

def descomponer(df):

    acts=[]

    for _,r in df.iterrows():

        especs = str(r["especialidad"]).replace("/",",").split(",")

        for e in especs:

            acts.append({
                "orden":r["orden"],
                "actividad":r["actividad"],
                "centro":r["centro"],
                "especialidad":e.strip().upper(),
                "duracion":int(r["duracion"])
            })

    return pd.DataFrame(acts)


# -----------------------------------------------------------------------------
# DIAGNOSTICO
# -----------------------------------------------------------------------------

def diagnostico(df,horas):

    dias = ceil(horas/24)
    cap = dias*8

    rep=[]

    for (c,e),g in df.groupby(["centro","especialidad"]):

        total = g["duracion"].sum()
        max_act = g["duracion"].max()

        tecnicos = ceil(total/cap)

        rep.append({
            "Centro":c,
            "Especialidad":e,
            "Horas totales":total,
            "Actividad más larga":max_act,
            "Capacidad técnico":cap,
            "Técnicos necesarios":tecnicos
        })

    return pd.DataFrame(rep)


# -----------------------------------------------------------------------------
# OPTIMIZADOR
# -----------------------------------------------------------------------------

def optimizar(df,horas):

    model = cp_model.CpModel()

    tecnicos={}

    capacidad = ceil(horas/24)*8

    for (c,e),g in df.groupby(["centro","especialidad"]):

        total = g["duracion"].sum()

        n = max(1,ceil(total/capacidad))

        tecnicos.setdefault(c,{})
        tecnicos[c][e] = [f"T{i}" for i in range(n)]

    asignaciones={}
    intervalos={}

    for i,r in df.iterrows():

        c=r["centro"]
        e=r["especialidad"]
        dur=int(r["duracion"])

        lista=[]

        for t in tecnicos[c][e]:

            s=model.NewIntVar(0,horas,f"s{i}{t}")
            e2=model.NewIntVar(0,horas,f"e{i}{t}")
            a=model.NewBoolVar(f"a{i}{t}")

            model.Add(e2 == s + dur)

            interval=model.NewOptionalIntervalVar(s,dur,e2,a,f"int{i}{t}")

            asignaciones[(i,t)] = (s,e2,a)
            intervalos[(i,t)] = interval

            lista.append(a)

        model.Add(sum(lista) == 1)

    for c in tecnicos:

        for e in tecnicos[c]:

            for t in tecnicos[c][e]:

                ints=[]

                for i,r in df.iterrows():

                    if r["centro"]==c and r["especialidad"]==e:

                        if (i,t) in intervalos:

                            ints.append(intervalos[(i,t)])

                if len(ints)>1:

                    model.AddNoOverlap(ints)

    solver=cp_model.CpSolver()

    solver.parameters.max_time_in_seconds = 20

    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL,cp_model.FEASIBLE]:

        return None

    cronograma=[]

    for (i,t),(s,e,a) in asignaciones.items():

        if solver.Value(a)==1:

            r=df.loc[i]

            cronograma.append({

                "Orden":r["orden"],
                "Actividad":r["actividad"],
                "Centro":r["centro"],
                "Especialidad":r["especialidad"],
                "Tecnico":t,
                "Inicio":inicio_parada + timedelta(hours=solver.Value(s)),
                "Fin":inicio_parada + timedelta(hours=solver.Value(e))
            })

    return pd.DataFrame(cronograma)


# -----------------------------------------------------------------------------
# APP
# -----------------------------------------------------------------------------

if archivo1 and archivo2:

    df = cargar_datos(archivo1,archivo2)

    acts = descomponer(df)

    st.write("Actividades generadas:",len(acts))

    if st.button("Ejecutar optimización"):

        cron = optimizar(acts,horas_paro)

        if cron is None:

            st.error("No existe solución factible")

            st.subheader("Diagnóstico")

            diag = diagnostico(acts,horas_paro)

            st.dataframe(diag)

        else:

            st.success("Cronograma generado")

            st.dataframe(cron)

            fig = px.timeline(
                cron,
                x_start="Inicio",
                x_end="Fin",
                y="Tecnico",
                color="Especialidad"
            )

            fig.update_yaxes(autorange="reversed")

            st.plotly_chart(fig,use_container_width=True)
