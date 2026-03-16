# =============================================================================
# DESCOMPOSICIÓN Y PROGRAMACIÓN EN BLOQUES DE 8 HORAS
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# -------------------------------------------------------------------------
# CONFIGURACIÓN APP
# -------------------------------------------------------------------------
st.set_page_config(page_title="Programación Paro Planta", page_icon="🏭", layout="wide")
st.title("🏭 Programación de Actividades - Paro de Planta")

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
# FUNCIONES
# -------------------------------------------------------------------------
def limpiar_columnas(df):
    df.columns = df.columns.str.strip().str.replace("\n"," ",regex=True)
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

    df["duracion_h"] = df["duracion_h"].fillna(1)

    return df


# -------------------------------------------------------------------------
# DESCOMPOSICIÓN POR ESPECIALIDAD
# -------------------------------------------------------------------------
def descomponer_ordenes(df):

    actividades=[]

    for _,row in df.iterrows():

        especs=[e.strip().upper() for e in str(row["especialidad"]).replace("/",",").split(",")]

        total=row["duracion_h"]

        if len(especs)==2:
            porcentajes=[0.6,0.4]
        elif len(especs)==3:
            porcentajes=[0.5,0.3,0.2]
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
# PROGRAMACIÓN EN BLOQUES DE 8 HORAS
# -------------------------------------------------------------------------
def programar_bloques(df_actividades):

    bloques=[]

    tiempo_actual=0

    for _,row in df_actividades.iterrows():

        horas=row["duracion_h"]
        bloques_act=int(horas//8)
        resto=horas%8

        for b in range(bloques_act):

            inicio=inicio_paro+timedelta(hours=tiempo_actual)
            fin=inicio+timedelta(hours=8)

            bloques.append({

                "orden":row["orden"],
                "actividad":row["actividad"],
                "especialidad":row["especialidad"],
                "criticidad":row["criticidad"],
                "bloque":b+1,
                "hora_inicio":inicio,
                "hora_fin":fin,
                "horas_bloque":8

            })

            tiempo_actual+=8

        if resto>0:

            inicio=inicio_paro+timedelta(hours=tiempo_actual)
            fin=inicio+timedelta(hours=resto)

            bloques.append({

                "orden":row["orden"],
                "actividad":row["actividad"],
                "especialidad":row["especialidad"],
                "criticidad":row["criticidad"],
                "bloque":bloques_act+1,
                "hora_inicio":inicio,
                "hora_fin":fin,
                "horas_bloque":resto

            })

            tiempo_actual+=resto

    return pd.DataFrame(bloques)


# -------------------------------------------------------------------------
# EJECUCIÓN
# -------------------------------------------------------------------------
if archivo1 and archivo2:

    st.subheader("Parámetros del paro")

    st.write("Inicio paro:",inicio_paro)
    st.write("Duración paro:",horas_paro,"horas")

    df=cargar_datos(archivo1,archivo2)

    st.subheader("Datos cargados")
    st.dataframe(df)

    df_actividades=descomponer_ordenes(df)

    st.subheader("Actividades descompuestas")
    st.dataframe(df_actividades)

    df_programado=programar_bloques(df_actividades)

    st.subheader("Programación en bloques de 8 horas")
    st.dataframe(df_programado)

    st.write("Total bloques generados:",len(df_programado))
