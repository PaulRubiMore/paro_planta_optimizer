# =============================================================================
# OPTIMIZADOR DE PARADA DE PLANTA - ASIGNA AUTOMÁTICAMENTE TÉCNICOS
# =============================================================================

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from math import ceil
from ortools.sat.python import cp_model
import plotly.express as px

# -------------------------------------------------------------------------
# CONFIGURACIÓN APP
# -------------------------------------------------------------------------
st.set_page_config(page_title="Optimización Parada Planta", page_icon="🏭", layout="wide")
st.title("🏭 Optimización de Parada de Planta")

horas_paro = st.sidebar.number_input("Duración del paro (horas)", min_value=1, max_value=500, value=36)
fecha_inicio = st.sidebar.date_input("Fecha inicio del paro")
hora_inicio = st.sidebar.time_input("Hora inicio del paro")
inicio_parada = datetime.combine(fecha_inicio, hora_inicio)

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

# -------------------------------------------------------------------------
# Paso 1-4: Descomposición de órdenes y distribución de horas por especialidad
# -------------------------------------------------------------------------
def descomponer_ordenes(df):
    actividades=[]
    for _,row in df.iterrows():
        # Dividir especialidades
        especs=[e.strip().upper() for e in str(row["especialidad"]).replace("/,",",").replace("/",",").split(",")]
        total=row["duracion_h"]

        # Distribución de horas según combinación
        if len(especs)==3: porcentajes=[0.5,0.3,0.2]
        elif len(especs)==2:
            if "MECANICA" in especs and "ELECTRICA" in especs: porcentajes=[0.65,0.35]
            elif "ELECTRICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            elif "MECANICA" in especs and "INSTRUMENTACION" in especs: porcentajes=[0.6,0.4]
            else: porcentajes=[0.5,0.5]
        else: porcentajes=[1]

        # Crear actividad por especialidad
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

# -------------------------------------------------------------------------
# Paso 5-7: Optimización con CP-SAT
# -------------------------------------------------------------------------
def optimizar_asignacion(df_actividades, horas_paro):
    model = cp_model.CpModel()

    # Definir técnicos disponibles por centro y especialidad
    centros = df_actividades['centro'].unique()
    especialidades = ['MECANICA','ELECTRICA','INSTRUMENTACION']

    # Ejemplo: 2 técnicos por especialidad y centro
    tecnicos = {}
    for c in centros:
        tecnicos[c] = {}
        for e in especialidades:
            tecnicos[c][e] = [f"{c}_{e}_T1", f"{c}_{e}_T2"]

    # Capacidad por técnico
    dias_paro = ceil(horas_paro/24)
    capacidad_tecnico = dias_paro*8  # horas totales

    # Variables de inicio y asignación de técnicos
    variables = {}
    for idx, row in df_actividades.iterrows():
        act_id = f"{row['orden']}_{row['especialidad']}"
        dur = row['duracion_h']
        centro = row['centro']
        esp = row['especialidad']
        for t in tecnicos[centro][esp]:
            var = model.NewIntVar(0, horas_paro-dur, f'start_{act_id}_{t}')
            assigned = model.NewBoolVar(f'assigned_{act_id}_{t}')
            variables[(act_id,t)] = {'start':var, 'assigned':assigned, 'dur':dur}

    # Restricción: cada actividad cubierta al menos por un técnico
    for idx, row in df_actividades.iterrows():
        act_id = f"{row['orden']}_{row['especialidad']}"
        centro = row['centro']
        esp = row['especialidad']
        model.AddBoolOr([variables[(act_id,t)]['assigned'] for t in tecnicos[centro][esp]])

    # Restricción: un técnico no trabaja en dos actividades al mismo tiempo
    for c in centros:
        for e in especialidades:
            techs = tecnicos[c][e]
            for t in techs:
                acts = [variables[(f"{r['orden']}_{r['especialidad']}",t)] 
                        for _,r in df_actividades[df_actividades['especialidad']==e].iterrows() 
                        if r['centro']==c and (f"{r['orden']}_{r['especialidad']}",t) in variables]
                for i in range(len(acts)):
                    for j in range(i+1,len(acts)):
                        model.AddBoolOr([
                            acts[i]['start'] + acts[i]['dur'] <= acts[j]['start'],
                            acts[j]['start'] + acts[j]['dur'] <= acts[i]['start']
                        ])

    # Restricción: capacidad máxima del técnico
    for c in centros:
        for e in especialidades:
            for t in tecnicos[c][e]:
                asignaciones = [variables[(act_id,t)]['assigned']*variables[(act_id,t)]['dur'] 
                                for (act_id,te) in variables if te==t]
                if asignaciones:
                    model.Add(sum(asignaciones) <= capacidad_tecnico)

    # Objetivo: minimizar finalización total y priorizar criticidad
    criticidad_peso = {'ALTA':1000,'MEDIA':100,'BAJA':10}
    makespan_vars = []
    for (act_id,t), v in variables.items():
        crit = df_actividades[df_actividades['orden']==int(act_id.split('_')[0])]['criticidad'].values[0]
        peso = criticidad_peso.get(crit.upper(),10)
        makespan_vars.append(v['start'] + v['dur']*peso)

    model.Minimize(sum(makespan_vars))

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60
    status = solver.Solve(model)

    # Construir cronograma final
    cronograma = []
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        for (act_id,t), v in variables.items():
            if solver.Value(v['assigned']):
                start = solver.Value(v['start'])
                end = start + v['dur']
                orden, esp = act_id.split('_')
                row = df_actividades[df_actividades['orden']==int(orden)].iloc[0]
                cronograma.append({
                    'Orden': orden,
                    'Actividad': row['actividad'],
                    'Centro': row['centro'],
                    'Especialidad': esp,
                    'Técnico': t,
                    'Hora inicio': inicio_parada + timedelta(hours=start),
                    'Hora fin': inicio_parada + timedelta(hours=end),
                    'Criticidad': row['criticidad'],
                    'Duración': v['dur']
                })
    else:
        st.warning("No se encontró solución factible en el tiempo límite")

    return pd.DataFrame(cronograma)

# -------------------------------------------------------------------------
# EJECUCIÓN APP
# -------------------------------------------------------------------------
if archivo1 and archivo2:
    df = cargar_datos(archivo1, archivo2)
    df_actividades = descomponer_ordenes(df)
    st.subheader("Actividades descompuestas")
    st.dataframe(df_actividades)

    df_cronograma = optimizar_asignacion(df_actividades, horas_paro)
    st.subheader("Cronograma optimizado")
    st.dataframe(df_cronograma)

    # Gráfica Gantt
    if not df_cronograma.empty:
        fig = px.timeline(df_cronograma, x_start="Hora inicio", x_end="Hora fin",
                          y="Técnico", color="Especialidad", text="Actividad")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
