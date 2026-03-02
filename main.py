from fastapi import FastAPI, Request, Form, Query
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from db import Session, Dispositivo, Historial, Reporte
from ping3 import ping
import datetime
import time
import os
import json

app = FastAPI()

# Crear directorios si no existen
os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Variable temporal para guardar resultados del último ping
ultimo_ping_resultado = {}

# Lista ESTÁTICA de tipos/categorías disponibles
TIPOS_DISPONIBLES = [
    'APs',
    'Switches',
    'Servidores',
    'Servidores Suecia',
    'Impresoras',
    'Cajas',
    'Pinpads/Datáfonos'
]

# --- FUNCIÓN PARA OBTENER TODAS LAS TIENDAS DINÁMICAMENTE ---
def obtener_todas_las_tiendas():
    """Obtiene todas las tiendas que existen en la base de datos"""
    db = Session()
    try:
        tiendas = db.query(Dispositivo.tienda).distinct().all()
        tiendas_list = sorted(list(set([t[0] for t in tiendas])))
        return tiendas_list
    finally:
        db.close()

# --- FUNCIÓN PARA HACER PING CON REINTENTOS (ULTRA RÁPIDO) ---
def hacer_ping_con_reintentos_generador(ip: str, hostname: str = None, max_intentos: int = 3, timeout: int = 0.2):
    """
    Intenta hacer ping a la IP con reintentos.
    Genera eventos para cada intento (ultra optimizado para velocidad).
    timeout: 0.2s = 200ms (como cmd de Windows)
    """
    for intento in range(1, max_intentos + 1):
        try:
            # Intentar con IP
            resultado = ping(ip, timeout=timeout)
            if resultado and resultado is not False:
                yield {
                    "evento": "intento",
                    "intento": intento,
                    "max_intentos": max_intentos,
                    "exito": True,
                    "metodo": "IP"
                }
                return True, intento
        except Exception as e:
            pass
        
        # Si la IP falla y hay hostname, intentar con hostname
        if hostname:
            try:
                resultado = ping(hostname, timeout=timeout)
                if resultado and resultado is not False:
                    yield {
                        "evento": "intento",
                        "intento": intento,
                        "max_intentos": max_intentos,
                        "exito": True,
                        "metodo": "Hostname"
                    }
                    return True, intento
            except Exception as e:
                pass
        
        # Enviar evento de intento fallido (SIN PAUSA - es rápido)
        yield {
            "evento": "intento",
            "intento": intento,
            "max_intentos": max_intentos,
            "exito": False,
            "metodo": "IP/Hostname"
        }
    
    return False, max_intentos

# --- PÁGINA PRINCIPAL: MENÚ POR TIENDA ---
@app.get("/")
def menu(request: Request, tienda: str = Query(None)):
    db = Session()
    try:
        # Obtener todas las tiendas dinámicamente
        todas_tiendas = obtener_todas_las_tiendas()
        
        # Si no hay tiendas, mostrar página vacía
        if not todas_tiendas:
            return templates.TemplateResponse("menu_vacio.html", {
                "request": request
            })
        
        # Si no se especifica tienda, usar la primera
        if not tienda:
            tienda = todas_tiendas[0]
        
        # Si la tienda actual no existe en la lista, redirigir a la primera
        if tienda not in todas_tiendas:
            tienda = todas_tiendas[0]
        
        # Filtramos dispositivos según la tienda seleccionada
        dispositivos_tienda = db.query(Dispositivo).filter(Dispositivo.tienda == tienda).all()
        
        # Crear un diccionario con el conteo de dispositivos por tipo
        conteo_por_tipo = {}
        for tipo in TIPOS_DISPONIBLES:
            conteo_por_tipo[tipo] = len([d for d in dispositivos_tienda if d.tipo == tipo])
        
        # Pasar dispositivos como JSON para búsqueda en cliente
        dispositivos_json = json.dumps([
            {
                "id": d.id,
                "nombre": d.nombre,
                "ip": d.ip,
                "hostname": d.hostname if d.hostname else "",
                "tipo": d.tipo,
                "tienda": d.tienda
            }
            for d in dispositivos_tienda
        ])
        
        return templates.TemplateResponse("menu.html", {
            "request": request,
            "tienda_actual": tienda,
            "todas_tiendas": todas_tiendas,
            "tipos": TIPOS_DISPONIBLES,
            "conteo_por_tipo": conteo_por_tipo,
            "dispositivos_json": dispositivos_json
        })
    finally:
        db.close()

# --- RUTA PARA INICIAR PING POR TIPO (REDIRIGE A RESULTADO) ---
@app.post("/ping_tipo")
def ping_tipo(
    tipo: str = Form(...),
    tienda: str = Form(...)
):
    """Redirige a la página de resultado que hará el streaming"""
    return RedirectResponse(f"/resultado?tipo={tipo}&tienda={tienda}", status_code=303)

# --- PÁGINA DE RESULTADO CON STREAMING ---
@app.get("/resultado")
def resultado(request: Request, tipo: str = Query(...), tienda: str = Query(...)):
    """Página que iniciará el streaming de ping"""
    return templates.TemplateResponse("resultado.html", {
        "request": request,
        "tipo": tipo,
        "tienda": tienda
    })

# --- ENDPOINT PARA STREAMING DE PING POR TIPO (OPTIMIZADO) ---
@app.get("/api/ping_stream")
async def ping_stream(tipo: str = Query(...), tienda: str = Query(...)):
    """
    Endpoint que hace streaming de los resultados del ping.
    Optimizado para velocidad máxima.
    """
    import asyncio
    
    db = Session()
    
    async def generate():
        try:
            dispositivos = db.query(Dispositivo).filter(
                Dispositivo.tipo == tipo,
                Dispositivo.tienda == tienda
            ).all()
            
            resultados_finales = []
            
            # Enviar el inicio del stream (SIN ESPERA)
            yield f"data: {json.dumps({'evento': 'inicio', 'total': len(dispositivos)})}\n\n"
            
            for index, d in enumerate(dispositivos, 1):
                # Usar el generador de ping
                exito = False
                intento_final = 0
                
                print(f"\n{'='*80}")
                print(f"⏳ [{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] INICIANDO PING: {d.nombre}")
                print(f"   📍 IP: {d.ip} | Hostname: {d.hostname if d.hostname else 'N/A'}")
                print(f"   🔄 Intentos: 3 | Timeout: 200ms")
                print(f"{'='*80}")
                
                for evento_intento in hacer_ping_con_reintentos_generador(
                    d.ip, 
                    d.hostname, 
                    max_intentos=3, 
                    timeout=0.2
                ):
                    # Enviar evento de intento individual
                    if evento_intento["evento"] == "intento":
                        intento_final = evento_intento["intento"]
                        exito = evento_intento["exito"]
                        
                        estado_icon = "✅ RESPONDE" if exito else "❌ SIN RESPUESTA"
                        print(f"   [{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Intento {intento_final}/3: {estado_icon}")
                        
                        # Enviar el evento del intento
                        yield f"data: {json.dumps({
                            'evento': 'intento_ping',
                            'dispositivo_id': d.id,
                            'nombre': d.nombre,
                            'ip': d.ip,
                            'hostname': d.hostname if d.hostname else "N/A",
                            'intento': intento_final,
                            'max_intentos': evento_intento["max_intentos"],
                            'exito': exito
                        })}\n\n"
                        
                        # Si tuvo éxito, salir del bucle
                        if exito:
                            break
                
                # Resultado final del dispositivo
                estado = "🟢 Online" if exito else "🔴 Offline"
                
                resultado = {
                    "id": d.id,
                    "nombre": d.nombre, 
                    "ip": d.ip,
                    "hostname": d.hostname if d.hostname else "N/A",
                    "estado": estado,
                    "intentos": intento_final,
                    "posicion": index,
                    "total": len(dispositivos)
                }
                
                resultados_finales.append(resultado)
                
                # Enviar resultado final del dispositivo
                print(f"   ✨ RESULTADO FINAL: {estado} (Intento {intento_final}/3)")
                print(f"{'='*80}\n")
                
                yield f"data: {json.dumps({'evento': 'resultado', 'datos': resultado})}\n\n"
                
                # Guardar en historial
                historial = Historial(
                    dispositivo=d.nombre, 
                    estado=estado, 
                    fecha=datetime.datetime.now()
                )
                db.add(historial)
            
            db.commit()
            
            # Guardar resultados finales en variable global
            global ultimo_ping_resultado
            ultimo_ping_resultado = {
                "tipo": tipo, 
                "tienda": tienda, 
                "resultados": resultados_finales
            }
            
            # Enviar señal de fin
            yield f"data: {json.dumps({'evento': 'fin', 'total_procesados': len(resultados_finales)})}\n\n"
            
            # Guardar REPORTE POR TIPO
            total_online = sum(1 for r in resultados_finales if '🟢' in r['estado'])
            total_offline = sum(1 for r in resultados_finales if '🔴' in r['estado'])
            
            # Obtener la fecha de hoy
            fecha_hoy = datetime.datetime.now().date()
            
            # Buscar si ya existe un reporte para hoy, esta tienda Y este tipo
            reporte_existente = db.query(Reporte).filter(
                Reporte.tienda == tienda,
                Reporte.tipo == tipo,
                Reporte.fecha >= datetime.datetime.combine(fecha_hoy, datetime.time.min),
                Reporte.fecha < datetime.datetime.combine(fecha_hoy, datetime.time.max)
            ).first()
            
            if reporte_existente:
                # Actualizar reporte existente (si hacemos ping dos veces al mismo tipo el mismo día)
                reporte_existente.total_dispositivos = len(resultados_finales)
                reporte_existente.dispositivos_online = total_online
                reporte_existente.dispositivos_offline = total_offline
            else:
                # Crear nuevo reporte
                nuevo_reporte = Reporte(
                    fecha=datetime.datetime.now(),
                    tienda=tienda,
                    tipo=tipo,
                    total_dispositivos=len(resultados_finales),
                    dispositivos_online=total_online,
                    dispositivos_offline=total_offline
                )
                db.add(nuevo_reporte)
            
            db.commit()
            
        except Exception as e:
            print(f"Error en ping_stream: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'evento': 'error', 'mensaje': str(e)})}\n\n"
        finally:
            db.close()
    
    return StreamingResponse(generate(), media_type="text/event-stream")

# --- NUEVA RUTA PARA PING INDIVIDUAL ---
@app.get("/ping_individual")
def ping_individual(
    request: Request,
    id: int = Query(...),
    nombre: str = Query(...),
    ip: str = Query(...),
    hostname: str = Query(default="")
):
    """Página para hacer ping a un dispositivo individual"""
    return templates.TemplateResponse("ping_individual.html", {
        "request": request,
        "dispositivo_id": id,
        "nombre": nombre,
        "ip": ip,
        "hostname": hostname
    })

# --- NUEVO ENDPOINT PARA STREAMING DE PING INDIVIDUAL ---
@app.get("/api/ping_individual")
async def ping_individual_stream(id: int = Query(...), ip: str = Query(...), hostname: str = Query(default="")):
    """
    Endpoint que hace streaming de un ping individual.
    """
    import asyncio
    
    db = Session()
    
    async def generate():
        try:
            # Obtener dispositivo
            dispositivo = db.query(Dispositivo).filter(Dispositivo.id == id).first()
            if not dispositivo:
                yield f"data: {json.dumps({'evento': 'error', 'mensaje': 'Dispositivo no encontrado'})}\n\n"
                return
            
            # Enviar inicio
            yield f"data: {json.dumps({'evento': 'inicio', 'nombre': dispositivo.nombre, 'ip': ip})}\n\n"
            
            # Hacer ping
            exito = False
            intento_final = 0
            
            print(f"\n{'='*80}")
            print(f"🎯 [{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] PING INDIVIDUAL: {dispositivo.nombre}")
            print(f"   📍 IP: {ip} | Hostname: {dispositivo.hostname if dispositivo.hostname else 'N/A'}")
            print(f"   🔄 Intentos: 3 | Timeout: 200ms")
            print(f"{'='*80}")
            
            for evento_intento in hacer_ping_con_reintentos_generador(
                ip,
                dispositivo.hostname if dispositivo.hostname else hostname,
                max_intentos=3,
                timeout=0.2
            ):
                if evento_intento["evento"] == "intento":
                    intento_final = evento_intento["intento"]
                    exito = evento_intento["exito"]
                    
                    estado_icon = "✅ RESPONDE" if exito else "❌ SIN RESPUESTA"
                    print(f"   [{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Intento {intento_final}/3: {estado_icon}")
                    
                    yield f"data: {json.dumps({
                        'evento': 'intento_ping',
                        'intento': intento_final,
                        'max_intentos': evento_intento["max_intentos"],
                        'exito': exito
                    })}\n\n"
                    
                    if exito:
                        break
            
            # Resultado final
            estado = "🟢 Online" if exito else "🔴 Offline"
            
            resultado = {
                "id": id,
                "nombre": dispositivo.nombre,
                "ip": ip,
                "hostname": dispositivo.hostname if dispositivo.hostname else hostname,
                "estado": estado,
                "intentos": intento_final
            }
            
            print(f"   ✨ RESULTADO FINAL: {estado} (Intento {intento_final}/3)")
            print(f"{'='*80}\n")
            
            yield f"data: {json.dumps({'evento': 'resultado', 'datos': resultado})}\n\n"
            
            # Guardar en historial
            historial = Historial(
                dispositivo=dispositivo.nombre,
                estado=estado,
                fecha=datetime.datetime.now()
            )
            db.add(historial)
            db.commit()
            
            # Enviar fin
            yield f"data: {json.dumps({'evento': 'fin'})}\n\n"
            
        except Exception as e:
            print(f"Error en ping_individual_stream: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'evento': 'error', 'mensaje': str(e)})}\n\n"
        finally:
            db.close()
    
    return StreamingResponse(generate(), media_type="text/event-stream")

# --- PÁGINA DE GESTIÓN DE DISPOSITIVOS ---
@app.get("/dispositivos")
def dispositivos(request: Request, tienda: str = Query(None)):
    db = Session()
    try:
        # Obtener todas las tiendas dinámicamente
        todas_tiendas = obtener_todas_las_tiendas()
        
        # Si no hay tiendas, mostrar página vacía
        if not todas_tiendas:
            return templates.TemplateResponse("dispositivos_vacio.html", {
                "request": request
            })
        
        # Si no se especifica tienda, usar la primera
        if not tienda:
            tienda = todas_tiendas[0]
        
        # Si la tienda actual no existe en la lista, usar la primera
        if tienda not in todas_tiendas:
            tienda = todas_tiendas[0]
        
        # Filtramos dispositivos según la tienda seleccionada
        dispositivos_tienda = db.query(Dispositivo).filter(Dispositivo.tienda == tienda).all()
        
        # Crear un diccionario con el conteo de dispositivos por tipo
        conteo_por_tipo = {}
        for tipo in TIPOS_DISPONIBLES:
            conteo_por_tipo[tipo] = len([d for d in dispositivos_tienda if d.tipo == tipo])
        
        return templates.TemplateResponse("dispositivos.html", {
            "request": request,
            "tienda_actual": tienda,
            "todas_tiendas": todas_tiendas,
            "tipos": TIPOS_DISPONIBLES,
            "conteo_por_tipo": conteo_por_tipo
        })
    finally:
        db.close()

# --- PÁGINA DE DETALLES DE DISPOSITIVOS POR TIPO ---
@app.get("/dispositivos/tipo")
def dispositivos_por_tipo(request: Request, tipo: str = Query(...), tienda: str = Query(None)):
    db = Session()
    try:
        todas_tiendas = obtener_todas_las_tiendas()
        
        # Si no hay tiendas
        if not todas_tiendas:
            return templates.TemplateResponse("dispositivos_vacio.html", {
                "request": request
            })
        
        # Si no se especifica tienda, usar la primera
        if not tienda:
            tienda = todas_tiendas[0]
        
        # Si la tienda actual no existe, usar la primera
        if tienda not in todas_tiendas:
            tienda = todas_tiendas[0]
        
        # Obtener dispositivos de ese tipo y tienda
        dispositivos = db.query(Dispositivo).filter(
            Dispositivo.tipo == tipo,
            Dispositivo.tienda == tienda
        ).all()
        
        return templates.TemplateResponse("dispositivos_tipo.html", {
            "request": request,
            "tienda_actual": tienda,
            "todas_tiendas": todas_tiendas,
            "tipo": tipo,
            "dispositivos": dispositivos
        })
    finally:
        db.close()

# --- FORMULARIO PARA AÑADIR DISPOSITIVO ---
@app.get("/add_dispositivo")
def add_dispositivo_form(request: Request):
    todas_tiendas = obtener_todas_las_tiendas()
    return templates.TemplateResponse("add_dispositivo.html", {
        "request": request,
        "tipos": TIPOS_DISPONIBLES,
        "todas_tiendas": todas_tiendas
    })

# --- RUTA POST PARA GUARDAR DISPOSITIVO ---
@app.post("/add_dispositivo")
def add_dispositivo_post(
    nombre: str = Form(...),
    ip: str = Form(...),
    hostname: str = Form(default=""),
    tipo: str = Form(...),
    tipo_tienda: str = Form(...),
    tienda: str = Form(default=""),
    nueva_tienda: str = Form(default="")
):
    db = Session()
    try:
        # Determinar cuál tienda usar
        tienda_final = ""
        
        if tipo_tienda == "existente" and tienda:
            tienda_final = tienda
        elif tipo_tienda == "nueva" and nueva_tienda:
            tienda_final = nueva_tienda.strip().upper()
        
        # Validación
        if not tienda_final:
            todas_tiendas = obtener_todas_las_tiendas()
            return templates.TemplateResponse("add_dispositivo.html", {
                "request": request,
                "tipos": TIPOS_DISPONIBLES,
                "todas_tiendas": todas_tiendas,
                "error": "Por favor, selecciona o crea una tienda válida"
            }, status_code=400)
        
        # Si hostname está vacío, dejarlo como None
        hostname_final = hostname.strip() if hostname else None
        
        nuevo_dispositivo = Dispositivo(
            nombre=nombre, 
            ip=ip,
            hostname=hostname_final,
            tipo=tipo, 
            tienda=tienda_final
        )
        db.add(nuevo_dispositivo)
        db.commit()
        
        return RedirectResponse("/?tienda=" + tienda_final, status_code=303)
    except Exception as e:
        print(f"Error al añadir dispositivo: {e}")
        todas_tiendas = obtener_todas_las_tiendas()
        return templates.TemplateResponse("add_dispositivo.html", {
            "request": request,
            "tipos": TIPOS_DISPONIBLES,
            "todas_tiendas": todas_tiendas,
            "error": f"Error al guardar: {str(e)}"
        }, status_code=400)
    finally:
        db.close()

# --- RUTA PARA ACTUALIZAR DISPOSITIVO ---
@app.post("/actualizar_dispositivo/{dispositivo_id}")
def actualizar_dispositivo(
    dispositivo_id: int,
    nombre: str = Form(...),
    ip: str = Form(...),
    hostname: str = Form(default=""),
    tipo: str = Form(...),
    tienda: str = Form(...)
):
    db = Session()
    try:
        dispositivo = db.query(Dispositivo).filter(Dispositivo.id == dispositivo_id).first()
        
        if dispositivo:
            dispositivo.nombre = nombre
            dispositivo.ip = ip
            dispositivo.hostname = hostname.strip() if hostname else None
            dispositivo.tipo = tipo
            db.commit()
            print(f"✅ Dispositivo {dispositivo_id} actualizado correctamente")
        
        return RedirectResponse(f"/dispositivos/tipo?tipo={tipo}&tienda={tienda}&actualizado={dispositivo_id}", status_code=303)
    except Exception as e:
        print(f"Error al actualizar dispositivo: {e}")
        return RedirectResponse(f"/dispositivos?tienda={tienda}", status_code=303)
    finally:
        db.close()

# --- RUTA PARA ELIMINAR DISPOSITIVO ---
@app.post("/eliminar_dispositivo/{dispositivo_id}")
def eliminar_dispositivo(dispositivo_id: int, tipo: str = Form(...), tienda: str = Form(...)):
    db = Session()
    try:
        dispositivo = db.query(Dispositivo).filter(Dispositivo.id == dispositivo_id).first()
        
        if dispositivo:
            nombre_dispositivo = dispositivo.nombre
            db.delete(dispositivo)
            db.commit()
            print(f"✅ Dispositivo {nombre_dispositivo} ({dispositivo_id}) eliminado correctamente")
        
        return RedirectResponse(f"/dispositivos/tipo?tipo={tipo}&tienda={tienda}&eliminado={dispositivo_id}", status_code=303)
    except Exception as e:
        print(f"Error al eliminar dispositivo: {e}")
        return RedirectResponse(f"/dispositivos/tipo?tipo={tipo}&tienda={tienda}", status_code=303)
    finally:
        db.close()

# --- RUTA PARA ELIMINAR TIENDA COMPLETA ---
@app.post("/eliminar_tienda")
def eliminar_tienda(tienda: str = Form(...)):
    db = Session()
    try:
        # Eliminar todos los dispositivos de esa tienda
        dispositivos = db.query(Dispositivo).filter(Dispositivo.tienda == tienda).all()
        for dispositivo in dispositivos:
            db.delete(dispositivo)
        
        db.commit()
        print(f"✅ Tienda {tienda} y todos sus dispositivos eliminados")
        
        # Redirigir a la primera tienda disponible
        todas_tiendas = obtener_todas_las_tiendas()
        
        if todas_tiendas:
            tienda_redireccion = todas_tiendas[0]
            return RedirectResponse(f"/?tienda={tienda_redireccion}", status_code=303)
        else:
            # Si no hay más tiendas, redirigir a la página vacía
            return RedirectResponse("/", status_code=303)
    except Exception as e:
        print(f"Error al eliminar tienda: {e}")
        return RedirectResponse(f"/?tienda={tienda}", status_code=303)
    finally:
        db.close()

# --- PÁGINA DE HISTORIAL DE REPORTES ---
@app.get("/reportes")
def ver_reportes(request: Request, tienda: str = Query(None)):
    db = Session()
    try:
        # Obtener todas las tiendas dinámicamente
        todas_tiendas = obtener_todas_las_tiendas()
        
        # Si no hay tiendas, mostrar página vacía
        if not todas_tiendas:
            return templates.TemplateResponse("reportes_vacio.html", {
                "request": request
            })
        
        # Si no se especifica tienda, usar la primera
        if not tienda:
            tienda = todas_tiendas[0]
        
        # Si la tienda actual no existe, usar la primera
        if tienda not in todas_tiendas:
            tienda = todas_tiendas[0]
        
        # Obtener reportes de la tienda ordenados por fecha descendente
        reportes = db.query(Reporte).filter(
            Reporte.tienda == tienda
        ).order_by(Reporte.fecha.desc()).all()
        
        # Agrupar reportes por día
        reportes_por_dia = {}
        for reporte in reportes:
            fecha_dia = reporte.fecha.date()
            if fecha_dia not in reportes_por_dia:
                reportes_por_dia[fecha_dia] = {
                    'fecha': fecha_dia,
                    'reportes': []
                }
            reportes_por_dia[fecha_dia]['reportes'].append(reporte)
        
        # Convertir a lista ordenada por fecha descendente
        dias_ordenados = sorted(reportes_por_dia.items(), key=lambda x: x[0], reverse=True)
        
        return templates.TemplateResponse("reportes.html", {
            "request": request,
            "tienda_actual": tienda,
            "todas_tiendas": todas_tiendas,
            "reportes_por_dia": dias_ordenados
        })
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)