# =============================================================================
# DESCOMPOSICIÓN DE ÓRDENES DE MANTENIMIENTO
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime

# -------------------------------------------------------------------------
# CONFIGURACIÓN APP
# -------------------------------------------------------------------------
st.set_page_config(page_title="Descomposición de Actividades", page_icon="🏭", layout="wide")
st.title("🏭 Descomposición de Órdenes de Mantenimiento")

# -------------------------------------------------------------------------
# PARÁMETROS DEL PARO
# -------------------------------------------------------------------------
st.sidebar.subheader("Parámetros del paro")

horas_paro = st.sidebar.number_input(
    "Duración del paro (horas)",
    min_value=1,
    max_value=500,
    value=36
)

fecha_inicio_paro = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio_paro = st.sidebar.time_input("Hora inicio del paro")

inicio_paro = datetime.combine(fecha_inicio_paro, hora_inicio_paro)

# -------------------------------------------------------------------------
# CARGA ARCHIVOS
# -------------------------------------------------------------------------
archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])


# -------------------------------------------------------------------------
# FUNCIONES AUXILIARES
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
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col:"TIEMPO (Hrs)"})

    df1 = df1[df1["EJECUTOR"].str.contains("massy", case=False, na=False)]

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

    df["criticidad"] = df["criticidad"].astype(str).str.strip().str.upper()

    return df


# -------------------------------------------------------------------------
# DESCOMPOSICIÓN DE ÓRDENES
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
            if e.strip() != ""
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
            dur = int(dur) if dur-int(dur)<1.5 else int(dur)+1

            actividades.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["centro"],
                "especialidad":esp,
                "criticidad":row["criticidad"],
                "duracion_h":dur,
                "duracion_total_orden":total
            })

    return pd.DataFrame(actividades)


# -------------------------------------------------------------------------
# FRAGMENTAR ACTIVIDADES EN BLOQUES DE 8 HORAS
# -------------------------------------------------------------------------
def fragmentar_bloques(df_actividades):

    bloques = []

    for _,row in df_actividades.iterrows():

        duracion = int(row["duracion_h"])
        restante = duracion
        bloque = 1

        while restante > 0:

            horas = 8 if restante >= 8 else restante

            bloques.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["centro"],
                "especialidad":row["especialidad"],
                "criticidad":row["criticidad"],
                "bloque":bloque,
                "duracion_h":horas
            })

            restante -= horas
            bloque += 1

    return pd.DataFrame(bloques)


# -------------------------------------------------------------------------
# EJECUCIÓN
# -------------------------------------------------------------------------
if archivo1 and archivo2:

    st.subheader("Parámetros del paro")

    st.write("Duración del paro (horas):", horas_paro)
    st.write("Inicio del paro:", inicio_paro)

    df = cargar_datos(archivo1, archivo2)

    st.subheader("Datos cargados")
    st.dataframe(df)

    df_actividades = descomponer_ordenes(df)

    # -------------------------------------------------
    # FRAGMENTACIÓN EN BLOQUES DE 8 HORAS
    # -------------------------------------------------
    df_bloques = fragmentar_bloques(df_actividades)

    # -------------------------------------------------
    # ORGANIZAR POR CRITICIDAD
    # -------------------------------------------------
    prioridad = {
        "ALTA":1,
        "MEDIA":2,
        "BAJA":3
    }

    df_bloques["prioridad"] = df_bloques["criticidad"].map(prioridad)

    df_bloques = df_bloques.sort_values(
        by=["prioridad","duracion_h"],
        ascending=[True,False]
    )

    df_bloques = df_bloques.drop(columns="prioridad")

    st.subheader("Actividades fragmentadas en bloques de 8 horas")
    st.dataframe(df_bloques)

    st.write("Total bloques generados:", len(df_bloques))
