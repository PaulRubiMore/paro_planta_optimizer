import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px

st.set_page_config(layout="wide")
st.title("OPTIMIZADOR PARADA DE PLANTA")

# ---------------------------------------------------------
# PARAMETROS
# ---------------------------------------------------------

horas_paro = st.sidebar.number_input("Duración paro (h)", 1, 500, 36)
fecha_inicio = st.sidebar.date_input("Fecha inicio")
hora_inicio = st.sidebar.time_input("Hora inicio")

inicio_paro = datetime.combine(fecha_inicio, hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo SAP", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo zonas", type=["xlsx"])

# ---------------------------------------------------------
# LIMPIEZA
# ---------------------------------------------------------

def limpiar_columnas(df):
    df.columns = df.columns.str.strip().str.replace("\n"," ",regex=True)
    return df

# ---------------------------------------------------------
# CARGA
# ---------------------------------------------------------

def cargar_datos(a1,a2):

    df1 = limpiar_columnas(pd.read_excel(a1))
    df2 = limpiar_columnas(pd.read_excel(a2))

    for col in df1.columns:
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col:"TIEMPO (Hrs)"})

    df1 = df1[df1["EJECUTOR"].str.contains("massy",case=False,na=False)]

    df1 = df1[[
        "Centro planificación","Actividades","Orden",
        "TIEMPO (Hrs)","ESPECIALIDAD","CRITICIDAD"
    ]]

    df2 = df2[["Actividades","Zona","Sector"]]

    df = df1.merge(df2,on="Actividades",how="left")

    df = df.rename(columns={
        "Orden":"orden",
        "Actividades":"actividad",
        "TIEMPO (Hrs)":"duracion_h",
        "ESPECIALIDAD":"especialidad",
        "Centro planificación":"centro"
    })

    df["duracion_h"] = df["duracion_h"].fillna(1)

    return df

# ---------------------------------------------------------
# DESCOMPOSICION
# ---------------------------------------------------------

def descomponer(df):

    out=[]

    for _,r in df.iterrows():

        especs = str(r["especialidad"]).replace("/",",").split(",")
        especs=[e.strip().upper() for e in especs]

        total=r["duracion_h"]

        if len(especs)==3: p=[0.5,0.3,0.2]
        elif len(especs)==2: p=[0.6,0.4]
        else: p=[1]

        for e,pp in zip(especs,p):

            out.append({
                "orden":r["orden"],
                "actividad":r["actividad"],
                "centro":r["centro"],
                "especialidad":e,
                "duracion_h":round(total*pp)
            })

    return pd.DataFrame(out)

# ---------------------------------------------------------
# FRAGMENTAR
# ---------------------------------------------------------

def fragmentar(df):

    out=[]

    for _,r in df.iterrows():

        h=r["duracion_h"]
        b=1

        while h>0:

            d=min(8,h)

            out.append({
                "orden":r["orden"],
                "actividad":r["actividad"],
                "centro":r["centro"],
                "especialidad":r["especialidad"],
                "bloque":b,
                "duracion":d
            })

            h-=d
            b+=1

    return pd.DataFrame(out)

# ---------------------------------------------------------
# OPTIMIZADOR
# ---------------------------------------------------------

def optimizar(df, horas_paro):

    model=cp_model.CpModel()

    dias=ceil(horas_paro/24)
    cap=dias*8

    df["grupo"]=df["orden"].astype(str)+"_"+df["actividad"].astype(str)
    dur_total=df.groupby("grupo")["duracion"].sum()

    combos=df[["centro","especialidad"]].drop_duplicates()

    tecnicos={}

    for _,r in combos.iterrows():
        c,e=r["centro"],r["especialidad"]
        tecnicos[(c,e)]=[f"{c}_{e}_T{i}" for i in range(1,101)]

    asignacion={}
    n=len(df)

    for i in range(n):
        c=df.iloc[i]["centro"]
        e=df.iloc[i]["especialidad"]

        for t in tecnicos[(c,e)]:
            asignacion[(i,t)]=model.NewBoolVar(f"a_{i}_{t}")

    # asignacion unica
    for i in range(n):
        c=df.iloc[i]["centro"]
        e=df.iloc[i]["especialidad"]

        model.Add(sum(asignacion[(i,t)] for t in tecnicos[(c,e)])==1)

    # capacidad
    for (c,e),lista in tecnicos.items():
        for t in lista:

            tareas=[(i,t) for i in range(n) if (i,t) in asignacion]

            if tareas:

                model.Add(
                    sum(asignacion[(i,t)]*int(df.iloc[i]["duracion"]) for (i,t) in tareas) <= cap
                )

   # continuidad fuerte (MISMO TECNICO)
   for g,grp in df.groupby("grupo"):
       if dur_total[g] <= cap:
           idx = grp.index.tolist()
           c = df.loc[idx[0],"centro"]
           e = df.loc[idx[0],"especialidad"]
           # crear variable por tecnico (elige 1 tecnico para TODA la actividad)
           selector_tecnico = {}
           for t in tecnicos[(c,e)]:
               selector_tecnico[t] = model.NewBoolVar(f"sel_{g}_{t}")
           # SOLO UN tecnico para toda la actividad
           model.Add(sum(selector_tecnico[t] for t in tecnicos[(c,e)]) == 1)
           # todos los bloques usan ese tecnico
           for i in idx:
               for t in tecnicos[(c,e)]:
                   if (i,t) in asignacion:
                       model.Add(
                           asignacion[(i,t)] == selector_tecnico[t]
                       )
                       
    # minimizar tecnicos
    usados=[]

    for (c,e),lista in tecnicos.items():

        for t in lista:

            vars_t=[asignacion[(i,t)] for i in range(n) if (i,t) in asignacion]

            if vars_t:

                u=model.NewBoolVar(f"u_{t}")
                model.AddMaxEquality(u,vars_t)
                usados.append(u)

    model.Minimize(sum(usados))

    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=60

    status=solver.Solve(model)

    res=[]

    if status in [cp_model.OPTIMAL,cp_model.FEASIBLE]:

        for (i,t),v in asignacion.items():
            if solver.Value(v)==1:

                r=df.iloc[i]

                res.append({
                    "Tecnico":t,
                    "Centro":r["centro"],
                    "Especialidad":r["especialidad"],
                    "Orden":r["orden"],
                    "Actividad":r["actividad"],
                    "Bloque":r["bloque"],
                    "Duracion":r["duracion"]
                })

    return pd.DataFrame(res)

# ---------------------------------------------------------
# CRONOGRAMA
# ---------------------------------------------------------

def cronograma(df, inicio):

    if df.empty: return df

    df=df.sort_values(["Tecnico","Orden","Bloque"])

    out=[]

    for t,g in df.groupby("Tecnico"):

        tiempo=inicio
        horas_dia=0
        dia=1

        for _,r in g.iterrows():

            h=r["Duracion"]

            while h>0:

                disp=8-horas_dia

                if disp==0:
                    tiempo+=timedelta(hours=(24-horas_dia))
                    horas_dia=0
                    dia+=1
                    disp=8

                uso=min(disp,h)

                ini=tiempo
                fin=ini+timedelta(hours=uso)

                out.append({
                    **r,
                    "Inicio":ini,
                    "Fin":fin,
                    "Dia":dia
                })

                tiempo=fin
                horas_dia+=uso
                h-=uso

    return pd.DataFrame(out)

# ---------------------------------------------------------
# GANTT
# ---------------------------------------------------------

def gantt(df):

    if df.empty: return

    fig=px.timeline(
        df,
        x_start="Inicio",
        x_end="Fin",
        y="Tecnico",
        color="Actividad"
    )

    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------
# EJECUCION
# ---------------------------------------------------------

if archivo1 and archivo2:

    df=cargar_datos(archivo1,archivo2)
    st.dataframe(df)

    df2=descomponer(df)
    df3=fragmentar(df2)

    df_opt=optimizar(df3, horas_paro)

    if not df_opt.empty:

        st.subheader("Asignación")
        st.dataframe(df_opt)

        st.success(f"Tecnicos: {df_opt['Tecnico'].nunique()}")

        df_crono=cronograma(df_opt,inicio_paro)

        st.subheader("Cronograma")
        st.dataframe(df_crono)

        gantt(df_crono)

    else:
        st.error("Sin solución")
