# =============================================================================
# DESCOMPOSICIÓN DE ÓRDENES DE MANTENIMIENTO
# =============================================================================

import streamlit as st
import pandas as pd

# -------------------------------------------------------------------------
# CONFIGURACIÓN APP
# -------------------------------------------------------------------------
st.set_page_config(page_title="Descomposición de Actividades", page_icon="🏭", layout="wide")
st.title("🏭 Descomposición de Órdenes de Mantenimiento")

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

    # Buscar columna tiempo
    for col in df1.columns:
        if "TIEMPO" in col.upper():
            df1 = df1.rename(columns={col:"TIEMPO (Hrs)"})

    # Filtrar ejecutor massy
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
                "criticidad":str(row["criticidad"]).upper(),
                "duracion_h":dur,
                "duracion_total_orden":total

            })

    return pd.DataFrame(actividades)


# -------------------------------------------------------------------------
# EJECUCIÓN
# -------------------------------------------------------------------------
if archivo1 and archivo2:

    df = cargar_datos(archivo1, archivo2)

    st.subheader("Datos cargados")
    st.dataframe(df)

    df_actividades = descomponer_ordenes(df)

    # -------------------------------------------------
    # ORGANIZAR POR CRITICIDAD
    # -------------------------------------------------
    prioridad = {
        "ALTA":1,
        "MEDIA":2,
        "BAJA":3
    }

    df_actividades["prioridad"] = df_actividades["criticidad"].map(prioridad)

    df_actividades = df_actividades.sort_values(by="prioridad")

    df_actividades = df_actividades.drop(columns="prioridad")

    st.subheader("Actividades organizadas por criticidad")
    st.dataframe(df_actividades)

    st.write("Total actividades generadas:", len(df_actividades))
