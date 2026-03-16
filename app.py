# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime
from ortools.sat.python import cp_model

# -------------------------------------------------------------------------
# CONFIGURACIÓN APP
# -------------------------------------------------------------------------
st.set_page_config(page_title="Optimización Paro Planta", page_icon="🏭", layout="wide")
st.title("🏭 Optimización de Parada de Planta")

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
# LIMPIAR COLUMNAS
# -------------------------------------------------------------------------
def limpiar_columnas(df):
    df.columns = df.columns.str.strip().str.replace("\n"," ",regex=True)
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

    return df

# -------------------------------------------------------------------------
# DESCOMPOSICIÓN POR ESPECIALIDAD
# -------------------------------------------------------------------------
def descomponer_ordenes(df):

    actividades = []

    for _,row in df.iterrows():

        especs=[e.strip().upper() for e in str(row["especialidad"]).replace("/",",").split(",")]

        total=row["duracion_h"]

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

            dur=round(total*pct)

            actividades.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["centro"],
                "especialidad":esp,
                "criticidad":row["criticidad"],
                "duracion_h":dur
            })

    return pd.DataFrame(actividades)

# -------------------------------------------------------------------------
# FRAGMENTAR EN BLOQUES DE 8 HORAS
# -------------------------------------------------------------------------
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
                "duracion":dur,
                "bloque":bloque
            })

            horas-=dur
            bloque+=1

    return pd.DataFrame(fragmentos)

# -------------------------------------------------------------------------
# OPTIMIZACIÓN ORTOOLS
# -------------------------------------------------------------------------
                "actividad":row["actividad"],

# -------------------------------------------------------------------------
# EJECUCIÓN
# -------------------------------------------------------------------------
if archivo1 and archivo2:

    st.subheader("Parámetros del paro")
    st.write("Duración paro:",horas_paro)
    st.write("Inicio paro:",inicio_paro)

    df=cargar_datos(archivo1,archivo2)

    st.subheader("Datos cargados")
    st.dataframe(df)

    df_actividades=descomponer_ordenes(df)

    st.subheader("Actividades descompuestas")
    st.dataframe(df_actividades)

    df_fragmentado=fragmentar_actividades(df_actividades)

    st.subheader("Actividades fragmentadas (bloques 8h)")
    st.dataframe(df_fragmentado)

    st.subheader("Optimización del paro")

    df_opt=optimizar_paro(df_fragmentado,horas_paro)

    st.dataframe(df_opt)

    st.write("Técnicos requeridos:",df_opt["Tecnico"].nunique())
