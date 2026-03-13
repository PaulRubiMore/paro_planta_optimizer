# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA - CP-SAT + STREAMLIT
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

horas_paro = st.sidebar.number_input("Duración del paro (horas)",1,500,36)

fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")

inicio_parada = datetime.combine(fecha_inicio,hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo",type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades",type=["xlsx"])

# -----------------------------------------------------------------------------
# FUNCIONES AUXILIARES
# -----------------------------------------------------------------------------

def limpiar_columnas(df):

    df.columns = df.columns.str.strip()

    df.columns = df.columns.str.replace("\n"," ",regex=True)

    df.columns = df.columns.str.replace("  "," ")

    return df


def cargar_datos(archivo1,archivo2):

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

            dur = total * pct

            if dur-int(dur) < 1.5:

                dur = int(dur)

            else:

                dur = int(dur)+1

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
# OPTIMIZADOR CP-SAT
# -----------------------------------------------------------------------------

def optimizar_asignacion(df_actividades,horas_paro):

    model = cp_model.CpModel()

    dias_paro = ceil(horas_paro/24)

    capacidad_tecnico = dias_paro*8

    centros = df_actividades["centro"].unique()

    especialidades=["MECANICA","ELECTRICA","INSTRUMENTACION"]

    tecnicos={}

    resumen=[]

    for c in centros:

        tecnicos[c]={}

        for e in especialidades:

            df_temp = df_actividades[
                (df_actividades["centro"]==c) &
                (df_actividades["especialidad"]==e)
            ]

            total_horas = df_temp["duracion_h"].sum()

            if total_horas==0:

                continue

            n_tecnicos = ceil(total_horas/capacidad_tecnico)

            n_tecnicos = max(1,n_tecnicos)

            tecnicos[c][e] = [
                f"{c}_{e}_T{i+1}" for i in range(n_tecnicos)
            ]

            resumen.append({
                "Centro":c,
                "Especialidad":e,
                "Horas trabajo":total_horas,
                "Capacidad técnico":capacidad_tecnico,
                "Técnicos requeridos":n_tecnicos
            })

    st.subheader("👷 Técnicos necesarios")

    st.dataframe(pd.DataFrame(resumen))

    intervalos={}

    asignaciones={}

    for i,row in df_actividades.iterrows():

        esp=row["especialidad"]

        centro=row["centro"]

        dur=int(row["duracion_h"])

        if esp not in tecnicos.get(centro,{}):
            continue

        for t in tecnicos[centro][esp]:

            start=model.NewIntVar(0,horas_paro,f"start_{i}_{t}")

            end=model.NewIntVar(0,horas_paro,f"end_{i}_{t}")

            assigned=model.NewBoolVar(f"assigned_{i}_{t}")

            interval=model.NewOptionalIntervalVar(
                start,
                dur,
                end,
                assigned,
                f"interval_{i}_{t}"
            )

            intervalos[(i,t)] = interval

            asignaciones[(i,t)] = (start,end,assigned,dur)

    for i,row in df_actividades.iterrows():

        esp=row["especialidad"]

        centro=row["centro"]

        if esp not in tecnicos.get(centro,{}):
            continue

        model.AddBoolOr([

            asignaciones[(i,t)][2]

            for t in tecnicos[centro][esp]

        ])

    for c in tecnicos:

        for e in tecnicos[c]:

            for t in tecnicos[c][e]:

                lista=[]

                for i,row in df_actividades.iterrows():

                    if row["centro"]==c and row["especialidad"]==e:

                        if (i,t) in intervalos:

                            lista.append(intervalos[(i,t)])

                if len(lista)>1:

                    model.AddNoOverlap(lista)

    for c in tecnicos:

        for e in tecnicos[c]:

            for t in tecnicos[c][e]:

                horas=[]

                for (i,tt),(start,end,assigned,dur) in asignaciones.items():

                    if tt==t:

                        horas.append(assigned*dur)

                model.Add(sum(horas)<=capacidad_tecnico)

    criticidad_peso={"ALTA":1000,"MEDIA":100,"BAJA":10}

    objetivo=[]

    for (i,t),(start,end,assigned,dur) in asignaciones.items():

        crit=df_actividades.loc[i,"criticidad"]

        peso=criticidad_peso.get(crit,10)

        objetivo.append(end*peso)

    model.Minimize(sum(objetivo))

    solver=cp_model.CpSolver()

    solver.parameters.max_time_in_seconds=60

    status=solver.Solve(model)

    cronograma=[]

    if status in [cp_model.OPTIMAL,cp_model.FEASIBLE]:

        for (i,t),(start,end,assigned,dur) in asignaciones.items():

            if solver.Value(assigned)==1:

                row=df_actividades.loc[i]

                cronograma.append({

                    "Orden":row["orden"],
                    "Actividad":row["actividad"],
                    "Centro":row["centro"],
                    "Especialidad":row["especialidad"],
                    "Técnico":t,
                    "Hora inicio":inicio_parada + timedelta(hours=solver.Value(start)),
                    "Hora fin":inicio_parada + timedelta(hours=solver.Value(end)),
                    "Duración":dur,
                    "Criticidad":row["criticidad"]

                })

    return pd.DataFrame(cronograma)


# -----------------------------------------------------------------------------
# EJECUCIÓN
# -----------------------------------------------------------------------------

if archivo1 and archivo2:

    df=cargar_datos(archivo1,archivo2)

    st.subheader("Datos cargados")

    st.dataframe(df.head())

    df_actividades=descomponer_ordenes(df)

    st.subheader("Actividades generadas")

    st.dataframe(df_actividades.head())

    st.info("Calculando cronograma...")

    cronograma=optimizar_asignacion(df_actividades,horas_paro)

    st.subheader("Cronograma optimizado")

    st.dataframe(cronograma)

    if not cronograma.empty:

        fig=px.timeline(

            cronograma,

            x_start="Hora inicio",

            x_end="Hora fin",

            y="Técnico",

            color="Especialidad",

            text="Orden"

        )

        fig.update_yaxes(autorange="reversed")

        st.plotly_chart(fig,use_container_width=True)
