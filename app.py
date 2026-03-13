# =============================================================================
# APP DE PARADA DE PLANTA - ASIGNA ACTIVIDADES POR DÍA (SIN OPTIMIZACIÓN)
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
import plotly.express as px

# ---------------------------------------------------------------------------
# CONFIGURACIÓN APP
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Parada Planta Simple", page_icon="🏭", layout="wide")
st.title("🏭 Cronograma de Parada de Planta (Sin Optimización)")

horas_paro = st.sidebar.number_input("Duración del paro (horas)", min_value=1, max_value=500, value=36)
fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")
inicio_parada = datetime.combine(fecha_inicio, hora_inicio)

archivo1 = st.sidebar.file_uploader("Archivo 1 - Paro de bombeo", type=["xlsx"])
archivo2 = st.sidebar.file_uploader("Archivo 2 - Lista de actividades", type=["xlsx"])

# ---------------------------------------------------------------------------
# FUNCIONES AUXILIARES
# ---------------------------------------------------------------------------
def limpiar_columnas(df):
    df.columns = df.columns.str.strip().str.replace("\n"," ",regex=True).str.replace("  "," ")
    return df

def cargar_datos(archivo1, archivo2):
    df1 = pd.read_excel(archivo1)
    df2 = pd.read_excel(archivo2)
    df1 = limpiar_columnas(df1)
    df2 = limpiar_columnas(df2)
    for col in df1.columns:
        if "TIEMPO" in col.upper(): df1 = df1.rename(columns={col:"TIEMPO (Hrs)"} )
    df1 = df1[df1["EJECUTOR"].str.contains("massy", case=False, na=False)]
    df1 = df1[["Centro planificación","Actividades","Orden","TIEMPO (Hrs)","ESTADO","ESPECIALIDAD","EJECUTOR","CRITICIDAD"]]
    df2 = df2[["Actividades","Zona","Sector"]]
    df1 = df1.drop_duplicates(subset=["Orden"])
    df2 = df2.drop_duplicates(subset=["Actividades"])
    df = df1.merge(df2, on="Actividades", how="left")
    df = df.rename(columns={"Orden":"orden","Actividades":"actividad","TIEMPO (Hrs)":"duracion_h",
                            "ESPECIALIDAD":"especialidad","CRITICIDAD":"criticidad"})
    df["duracion_h"] = df["duracion_h"].fillna(1).astype(float)
    return df

def descomponer_ordenes(df):
    actividades=[]
    for _,row in df.iterrows():
        especs=[e.strip().upper() for e in str(row["especialidad"]).replace("/,",",").replace("/",",").split(",")]
        total=row["duracion_h"]
        if len(especs)==3: porcentajes=[0.5,0.3,0.2]
        elif len(especs)==2:
            if "MECANICA" in especs and "ELECTRICA" in especs: porcentajes=[0.65,0.35]
            elif "ELECTRICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            elif "MECANICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            else: porcentajes=[0.5,0.5]
        else: porcentajes=[1]
        for esp,pct in zip(especs,porcentajes):
            dur=total*pct
            dur=int(dur) if dur-int(dur)<1.5 else int(dur)+1
            actividades.append({
                "orden":row["orden"],
                "actividad":row["actividad"],
                "centro":row["Centro planificación"],
                "especialidad":esp,
                "criticidad":str(row["criticidad"]).upper(),
                "duracion_h": dur,
                "duracion_total_orden": total
            })
    return pd.DataFrame(actividades)

# ---------------------------------------------------------------------------
# GENERAR CRONOGRAMA SIMPLE POR HORAS
# ---------------------------------------------------------------------------
def generar_cronograma_simple(df_actividades, inicio_parada, max_horas_dia=8):
    df_actividades = df_actividades.copy()
    df_actividades["dia"] = 1
    df_actividades["tecnico_id"] = 1  # Asignación simple
    df_actividades["start"] = 0
    df_actividades["end"] = df_actividades["duracion_h"]
    df_actividades["inicio_real"] = df_actividades["start"].apply(lambda x: inicio_parada + timedelta(hours=x))
    df_actividades["fin_real"] = df_actividades["end"].apply(lambda x: inicio_parada + timedelta(hours=x))
    return df_actividades

# ---------------------------------------------------------------------------
# EJECUCIÓN APP
# ---------------------------------------------------------------------------
if archivo1 and archivo2:
    df=cargar_datos(archivo1,archivo2)
    st.subheader("Datos filtrados Massy Energy")
    st.dataframe(df)
    
    if st.button("Generar Cronograma"):
        df_actividades=descomponer_ordenes(df)
        st.subheader("Actividades descompuestas por especialidad")
        st.dataframe(df_actividades)
        
        resultado = generar_cronograma_simple(df_actividades, inicio_parada)
        st.subheader("Cronograma simple")
        st.dataframe(resultado)
        
        fig = px.timeline(resultado, x_start="inicio_real", x_end="fin_real",
                          y="tecnico_id", color="especialidad", title="Cronograma de Parada")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig,use_container_width=True)
else:
    st.info("Cargar los dos archivos Excel para iniciar.")
