import streamlit as st
import pandas as pd
import math
from ortools.sat.python import cp_model


# -----------------------------------------------------------------------------
# LIMPIAR COLUMNAS
# -----------------------------------------------------------------------------

def limpiar_columnas(df):

    df.columns = (
        df.columns
        .str.strip()
        .str.replace("\n", " ", regex=True)
        .str.replace("  ", " ")
    )

    return df


# -----------------------------------------------------------------------------
# CARGAR DATOS
# -----------------------------------------------------------------------------

def cargar_datos(archivo1, archivo2):

    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)

    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)

    # detectar columna tiempo
    for col in df1.columns:
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col: "TIEMPO (Hrs)"})

    # filtrar ejecutor massy
    df1 = df1[
        df1["EJECUTOR"].str.contains(
            "massy",
            case=False,
            na=False
        )
    ]

    df1 = df1[
        [
            "Centro planificación",
            "Actividades",
            "Orden",
            "TIEMPO (Hrs)",
            "ESTADO",
            "ESPECIALIDAD",
            "EJECUTOR",
            "CRITICIDAD"
        ]
    ]

    df2 = df2[
        [
            "Actividades",
            "Zona",
            "Sector"
        ]
    ]

    df1 = df1.drop_duplicates(subset=["Orden"])
    df2 = df2.drop_duplicates(subset=["Actividades"])

    df = df1.merge(
        df2,
        on="Actividades",
        how="left"
    )

    df = df.rename(
        columns={
            "Orden": "orden",
            "Actividades": "actividad",
            "Centro planificación": "centro",
            "TIEMPO (Hrs)": "duracion_h",
            "ESPECIALIDAD": "especialidad",
            "CRITICIDAD": "criticidad"
        }
    )

    df["duracion_h"] = df["duracion_h"].fillna(1).astype(int)

    return df


# -----------------------------------------------------------------------------
# CREAR TECNICOS
# -----------------------------------------------------------------------------

def crear_tecnicos(centros):

    tecnicos = []

    especialidades = [
        "MECANICA",
        "ELECTRICA",
        "INSTRUMENTACION"
    ]

    for c in centros:

        for e in especialidades:

            for i in range(1,6):

                tecnicos.append({

                    "tecnico":f"{c}_{e}_T{i}",
                    "centro":c,
                    "especialidad":e
                })

    return pd.DataFrame(tecnicos)


# -----------------------------------------------------------------------------
# OPTIMIZADOR
# -----------------------------------------------------------------------------

def optimizar(df, tecnicos, duracion_paro):

    model = cp_model.CpModel()

    horas = range(duracion_paro)

    x = {}

    for t in tecnicos.index:
        for a in df.index:
        for h in horas:

                if (
                    tecnicos.loc[t,"centro"] == df.loc[a,"centro"]
                    and
                    tecnicos.loc[t,"especialidad"] == df.loc[a,"especialidad"]
                ):

                    x[t,a,h] = model.NewBoolVar(f"x_{t}_{a}_{h}")

    # tecnico una actividad por hora
    for t in tecnicos.index:
        for h in horas:

            model.Add(

                sum(
                    x[t,a,h]
                    for a in df.index
                    if (t,a,h) in x
                ) <= 1

            )

    # cumplir duración
    for a in df.index:

        model.Add(

            sum(
                x[t,a,h]
                for t in tecnicos.index
                for h in horas
                if (t,a,h) in x
            ) == df.loc[a,"duracion_h"]

        )

    solver = cp_model.CpSolver()

    solver.parameters.max_time_in_seconds = 10

    solver.Solve(model)

    cronograma = pd.DataFrame(
        "",
        index=tecnicos["tecnico"],
        columns=horas
    )

    for (t,a,h) in x:

        if solver.Value(x[t,a,h]) == 1:

            tecnico = tecnicos.loc[t,"tecnico"]
            orden = df.loc[a,"orden"]

            cronograma.loc[tecnico,h] = orden

    return cronograma


# -----------------------------------------------------------------------------
# STREAMLIT
# -----------------------------------------------------------------------------

st.title("Optimizador de Parada de Planta")

duracion_paro = st.sidebar.number_input(
    "Duración del paro (horas)",
    1,
    120,
    36
)

archivo1 = st.sidebar.file_uploader(
    "Excel órdenes SAP",
    type=["xlsx"]
)

archivo2 = st.sidebar.file_uploader(
    "Excel zonas",
    type=["xlsx"]
)

if archivo1 and archivo2:

    df = cargar_datos(archivo1, archivo2)

    st.subheader("Datos cargados")

    st.dataframe(df)

    centros = df["centro"].unique()

    tecnicos = crear_tecnicos(centros)

    if st.button("Optimizar cronograma"):

        cronograma = optimizar(df, tecnicos, duracion_paro)

        st.subheader("Cronograma técnico × hora")

        st.dataframe(cronograma)

        st.download_button(
            "Descargar cronograma",
            cronograma.to_csv(),
            "cronograma.csv"
        )
