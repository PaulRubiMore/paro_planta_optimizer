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

@st.cache_data
def cargar_datos(a1,a2):

    df1 = limpiar_columnas(pd.read_excel(a1))

    tiempo_col = None
    for col in df1.columns:
        if "TIEMPO" in col.upper():
            tiempo_col = col
            break

    df1 = df1.rename(columns={tiempo_col:"duracion_h"})

    df1 = df1[df1["EJECUTOR"].str.contains("massy",case=False,na=False)]

    df = df1[[
        "Centro planificación","Actividades","Orden",
        "duracion_h","ESPECIALIDAD"
    ]].rename(columns={
        "Orden":"orden",
        "Actividades":"actividad",
        "ESPECIALIDAD":"especialidad",
        "Centro planificación":"centro"
    })

    df["duracion_h"] = pd.to_numeric(df["duracion_h"], errors="coerce").fillna(1)

    return df

# ---------------------------------------------------------
# DESCOMPOSICION
# ---------------------------------------------------------

@st.cache_data
def descomponer(df):

    out=[]

    for _,r in df.iterrows():

        especs = str(r["especialidad"]).replace("/",",").split(",")
        especs=[e.strip().upper() for e in especs if e.strip()]

        total = float(r["duracion_h"])

        if len(especs)==3: p=[0.5,0.3,0.2]
        elif len(especs)==2: p=[0.6,0.4]
        else: p=[1]

        duraciones = [int(total*pp) for pp in p]
        diff = int(total - sum(duraciones))

        if duraciones:
            duraciones[0] += diff

        for e,d in zip(especs,duraciones):

            if d <= 0:
                continue

            out.append({
                "orden":r["orden"],
                "actividad":r["actividad"],
                "centro":r["centro"],
                "especialidad":e,
                "duracion_h":d
            })

    return pd.DataFrame(out)

# ---------------------------------------------------------
# FRAGMENTAR
# ---------------------------------------------------------

@st.cache_data
def fragmentar(df):

    out=[]

    for _,r in df.iterrows():

        h=int(r["duracion_h"])
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


@st.cache_data
def optimizar(df, horas_paro):

    model = cp_model.CpModel()

    dias = ceil(horas_paro / 24)
    cap = dias * 8

    # -----------------------------
    # GRUPO (continuidad lógica)
    # -----------------------------
    df["grupo"] = (
        df["orden"].astype(str) + "_" +
        df["actividad"].astype(str) + "_" +
        df["centro"].astype(str) + "_" +
        df["especialidad"].astype(str)
    )

    combos = df[["centro","especialidad"]].drop_duplicates()

    tecnicos = {}

    for _, r in combos.iterrows():
        c, e = r["centro"], r["especialidad"]

        carga = df[(df["centro"] == c) & (df["especialidad"] == e)]["duracion"].sum()
        max_tecnicos = ceil(carga / cap) + 2

        tecnicos[(c,e)] = [f"{c}_{e}_T{i}" for i in range(1, max_tecnicos+1)]

    # -----------------------------
    # VARIABLES
    # -----------------------------
    asignacion = {}
    n = len(df)

    for i in range(n):
        c = df.iloc[i]["centro"]
        e = df.iloc[i]["especialidad"]

        for t in tecnicos[(c,e)]:
            asignacion[(i,t)] = model.NewBoolVar(f"a_{i}_{t}")

    # -----------------------------
    # 1. Cada bloque → 1 técnico
    # -----------------------------
    for i in range(n):
        c = df.iloc[i]["centro"]
        e = df.iloc[i]["especialidad"]

        model.Add(
            sum(asignacion[(i,t)] for t in tecnicos[(c,e)]) == 1
        )

    # -----------------------------
    # 2. Capacidad técnico
    # -----------------------------
    for (c,e), lista in tecnicos.items():
        for t in lista:

            tareas = [(i,t) for i in range(n) if (i,t) in asignacion]

            if tareas:
                model.Add(
                    sum(
                        asignacion[(i,t)] * int(df.iloc[i]["duracion"])
                        for (i,t) in tareas
                    ) <= cap
                )

    # -----------------------------
    # 3. CONTINUIDAD SUAVE 🔥
    # -----------------------------
    grupos = df["grupo"].unique()
    penalizacion_split = []

    for g in grupos:

        idxs = df[df["grupo"] == g].index.tolist()

        c = df.loc[idxs[0], "centro"]
        e = df.loc[idxs[0], "especialidad"]

        vars_g = []

        for t in tecnicos[(c,e)]:

            v = model.NewBoolVar(f"g_{g}_{t}")
            vars_g.append(v)

            # Si técnico participa → al menos un bloque
            model.Add(
                sum(asignacion[(i,t)] for i in idxs) >= v
            )

            # Si bloque usa técnico → técnico pertenece al grupo
            for i in idxs:
                model.Add(asignacion[(i,t)] <= v)

        # Penalizar usar más de 1 técnico
        exceso = model.NewIntVar(0, len(vars_g), f"exceso_{g}")
        model.Add(exceso == sum(vars_g) - 1)

        penalizacion_split.append(exceso)

    # -----------------------------
    # 4. Técnicos usados
    # -----------------------------
    usados = []

    for (c,e), lista in tecnicos.items():
        for t in lista:

            vars_t = [asignacion[(i,t)] for i in range(n) if (i,t) in asignacion]

            if vars_t:
                u = model.NewBoolVar(f"u_{t}")
                model.AddMaxEquality(u, vars_t)
                usados.append(u)

    # -----------------------------
    # OBJETIVO
    # -----------------------------
    model.Minimize(
        sum(usados) * 100 +          # minimizar técnicos globales
        sum(penalizacion_split) * 10 # evitar dividir actividades
    )

    # -----------------------------
    # SOLVER
    # -----------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60

    status = solver.Solve(model)

    res = []

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:

        for (i,t), v in asignacion.items():
            if solver.Value(v) == 1:

                r = df.iloc[i]

                res.append({
                    "Tecnico": t,
                    "Centro": r["centro"],
                    "Especialidad": r["especialidad"],
                    "Orden": r["orden"],
                    "Actividad": r["actividad"],
                    "Bloque": r["bloque"],
                    "Duracion": r["duracion"]
                })

    return pd.DataFrame(res)
# ---------------------------------------------------------
# CRONOGRAMA
# ---------------------------------------------------------

@st.cache_data
def cronograma(df, inicio_paro, horas_paro):

    if df.empty:
        return df

    inicio_real = inicio_paro + timedelta(hours=2)
    fin_real = inicio_paro + timedelta(hours=horas_paro - 2)

    df=df.sort_values(["Tecnico","Orden","Bloque"])

    out=[]

    for t,g in df.groupby("Tecnico"):

        tiempo=inicio_real
        horas_dia=0
        dia=1

        for _,r in g.iterrows():

            h=r["Duracion"]

            while h>0:

                if tiempo >= fin_real:
                    break

                if 12 <= tiempo.hour < 13:
                    tiempo = tiempo.replace(hour=13, minute=0)
                    continue

                disp=8-horas_dia

                if disp<=0:
                    tiempo+=timedelta(hours=(24-horas_dia))
                    horas_dia=0
                    dia+=1
                    continue

                uso=min(disp,h)

                if tiempo + timedelta(hours=uso) > fin_real:
                    uso=max(0,(fin_real-tiempo).total_seconds()/3600)

                if uso<=0:
                    break

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

def gantt(df, inicio_paro, horas_paro):

    if df.empty:
        return

    inicio_real = inicio_paro + timedelta(hours=2)
    fin_real = inicio_paro + timedelta(hours=horas_paro - 2)
    fin_total = inicio_paro + timedelta(hours=horas_paro)

    fig=px.timeline(
        df,
        x_start="Inicio",
        x_end="Fin",
        y="Tecnico",
        color="Actividad"
    )

    fig.add_vrect(x0=inicio_paro,x1=inicio_real,fillcolor="black",opacity=0.2,line_width=0)
    fig.add_vrect(x0=fin_real,x1=fin_total,fillcolor="black",opacity=0.2,line_width=0)

    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------
# EJECUCION
# ---------------------------------------------------------

if archivo1 and archivo2:

    df = cargar_datos(archivo1,archivo2)
    df2 = descomponer(df)
    df3 = fragmentar(df2)

    df_opt = optimizar(df3, horas_paro)

    if not df_opt.empty:

        st.subheader("Asignación óptima")
        st.dataframe(df_opt)

        df_crono = cronograma(df_opt, inicio_paro, horas_paro)

        # -------------------------------
        # FILTRO (NO RECALCULA)
        # -------------------------------
        centros = sorted(df_crono["Centro"].dropna().unique())

        centro_sel = st.selectbox(
            "Filtrar por Centro",
            ["Todos"] + centros,
            key="centro_filtro"
        )

        if centro_sel != "Todos":
            df_view = df_crono[df_crono["Centro"] == centro_sel]
        else:
            df_view = df_crono

        st.subheader("Cronograma")
        st.dataframe(df_view)

        if not df_view.empty:
            gantt(df_view, inicio_paro, horas_paro)
        else:
            st.warning("Sin datos para el centro seleccionado")

    else:
        st.error("Sin solución")
