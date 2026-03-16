# -------------------------------------------------------------------------
# Paso 5-7: Optimización con CP-SAT
# -------------------------------------------------------------------------
def optimizar_asignacion(df_actividades, horas_paro):
    model = cp_model.CpModel()

    # Definir técnicos disponibles por centro y especialidad
    centros = df_actividades['centro'].unique()
    especialidades = ['MECANICA','ELECTRICA','INSTRUMENTACION']

    # Suponemos 2 técnicos por especialidad y centro como ejemplo
    tecnicos = {}
    for c in centros:
        tecnicos[c] = {}
        for e in especialidades:
            # T1 y T2 por cada especialidad
            tecnicos[c][e] = [f"{c}_{e}_T1", f"{c}_{e}_T2"]

    # Calcular capacidad por técnico
    dias_paro = ceil(horas_paro/24)
    capacidad_tecnico = dias_paro*8  # horas totales por técnico

    # Crear variables de inicio y asignación de técnicos
    variables = {}
    for idx, row in df_actividades.iterrows():
        act_id = f"{row['orden']}_{row['especialidad']}"
        dur = row['duracion_h']
        centro = row['centro']
        esp = row['especialidad']
        # Variables de asignación: técnico y hora de inicio
        for t in tecnicos[centro][esp]:
            var = model.NewIntVar(0, horas_paro-dur, f'start_{act_id}_{t}')
            assigned = model.NewBoolVar(f'assigned_{act_id}_{t}')
            variables[(act_id,t)] = {'start':var, 'assigned':assigned, 'dur':dur}

    # Restricción: cada actividad debe ser cubierta por al menos un técnico
    for idx, row in df_actividades.iterrows():
        act_id = f"{row['orden']}_{row['especialidad']}"
        centro = row['centro']
        esp = row['especialidad']
        model.AddBoolOr([variables[(act_id,t)]['assigned'] for t in tecnicos[centro][esp]])

    # Restricción: un técnico no puede trabajar en dos actividades simultáneamente
    for c in centros:
        for e in especialidades:
            techs = tecnicos[c][e]
            for t in techs:
                acts = [variables[(f"{r['orden']}_{r['especialidad']}",t)] 
                        for _,r in df_actividades[df_actividades['especialidad']==e].iterrows() 
                        if r['centro']==c and (f"{r['orden']}_{r['especialidad']}",t) in variables]
                for i in range(len(acts)):
                    for j in range(i+1,len(acts)):
                        # No solapamiento: end_i <= start_j OR end_j <= start_i
                        end_i = acts[i]['start'] + acts[i]['dur']
                        end_j = acts[j]['start'] + acts[j]['dur']
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

    # Objetivo: minimizar hora de finalización total y priorizar criticidad
    # Asignamos ponderación: Alta=1000, Media=100, Baja=10
    criticidad_peso = {'ALTA':1000,'MEDIA':100,'BAJA':10}
    makespan_vars = []
    for (act_id,t), v in variables.items():
        # penalización por criticidad
        crit = df_actividades[df_actividades['orden']==int(act_id.split('_')[0])]['criticidad'].values[0]
        peso = criticidad_peso.get(crit.upper(),10)
        makespan_vars.append(v['start'] + v['dur']*peso)

    model.Minimize(sum(makespan_vars))

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60  # 1 minuto
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
