"""El motor corriendo como proceso aparte, manejado por la interfaz.

¿Por qué otro proceso? Python ejecuta un solo hilo a la vez dentro de cada
proceso (el famoso "GIL"). Si la interfaz y el mouse compartieran proceso, cada
vez que la ventana se redibuja (por ejemplo, al arrastrar un rectángulo en el
editor de pantallas) el mouse podría esperar unos milisegundos. En procesos
separados, Windows los atiende en paralelo y la interfaz no le agrega ni un
microsegundo al cursor.

Cómo se hablan (el "canal de control"), por la entrada y salida estándar:
  * La interfaz le escribe órdenes, una por línea, en JSON:
        {"orden": "pausar"}   {"orden": "reanudar"}   {"orden": "salir"}
        {"orden": "canal_datos"}   (pide abrir de nuevo el canal de datos)
        {"orden": "destinos", "ips": [["10.0.0.1", 0], ["192.168.1.28", 1]]}
            (dónde se vio a la otra PC en la red; 0 = por cable. Solo le sirve al cliente)
  * El motor le escribe eventos, uno por línea, en JSON:
        {"evento": "log", "texto": "..."}
        {"evento": "estado", "estado": "conectado", ...}   (ver estado.py)
        {"evento": "canal_datos", "socket": "...", "claves": "..."}   (ver más abajo)
Si la interfaz se cierra de golpe, la entrada se corta y el motor termina solo:
nunca queda un motor huérfano bloqueando el mouse.

El canal de datos (portapapeles, archivos, carpeta) lo abre el motor, porque es
el que tiene el puerto y hace el saludo, pero lo usa la interfaz. Se lo pasa con
socket.share(): Windows copia la conexión abierta al proceso de la interfaz, y
por la salida estándar viaja solo el "pase" (unos cientos de bytes en base64) y
las claves de cifrado de esa conexión. La salida estándar es un caño privado
entre los dos procesos: nadie más la puede leer.
"""

import base64
import json
import sys
import threading

from ..comun import registro
from ..comun.config import SERVIDOR
from ..comun.registro import log
from ..sistema import win32 as W
from . import estado as E
from .cliente import Cliente
from .servidor import Servidor

# Códigos de salida, para que la interfaz sepa cómo terminó.
SALIDA_OK = 0
SALIDA_CONFIG = 2  # Falta algún dato en la configuración.
SALIDA_ERROR = 3  # Puerto ocupado, PIN rechazado, etc.


def _leer_ordenes(nucleo, entrada):
    """Corre en un hilo: atiende lo que manda la interfaz."""
    try:
        for linea in entrada:
            try:
                orden = json.loads(linea).get("orden")
            except (ValueError, AttributeError):
                continue
            if orden == "pausar":
                nucleo.pausar(True)
            elif orden == "reanudar":
                nucleo.pausar(False)
            elif orden == "canal_datos":
                nucleo.pedir_canal_datos()
            elif orden == "destinos":
                nucleo.poner_destinos(json.loads(linea).get("ips") or [])
            elif orden == "salir":
                break
    except (OSError, ValueError):
        pass
    # Pidió salir, o se cerró la interfaz (fin de la entrada).
    nucleo.detener()


def _entregador(pid_app):
    """Devuelve la función que pasa un canal de datos a la interfaz (o None si no hay interfaz)."""
    if not pid_app:
        return None

    def entregar(sock, claves):
        try:
            pase = sock.share(pid_app)
        except OSError as error:
            log(f"No se pudo pasar el canal de datos a la ventana: {error}")
            return
        finally:
            sock.close()  # La interfaz ya tiene su propia copia de la conexión.
        registro.emitir({
            "evento": "canal_datos",
            "socket": base64.b64encode(pase).decode("ascii"),
            "claves": claves.envio.hex() + claves.recepcion.hex(),
        })

    return entregar


def correr_motor(config, entrada=None, pid_app=None):
    """Arranca el servidor o el cliente según la configuración. Devuelve el código de salida.

    `pid_app` es el proceso de la interfaz, al que se le pasa el canal de datos.
    """
    registro.usar_json()
    informante = E.Informante(emitir=registro.emitir, rol=config.rol)
    problemas = config.errores()
    if problemas:
        informante.actualizar(estado=E.ERROR, detalle=" ".join(problemas))
        return SALIDA_CONFIG
    if not W.es_administrador():
        log("Aviso: sin permisos de Administrador no se controlan las ventanas elevadas "
            "(Administrador de tareas, instaladores, etc.).")

    entregar_canal = _entregador(pid_app)
    if config.rol == SERVIDOR:
        nucleo = Servidor(config, informante=informante, entregar_canal=entregar_canal)
    else:
        nucleo = Cliente(config, informante=informante, entregar_canal=entregar_canal)

    hilo = threading.Thread(
        target=_leer_ordenes, args=(nucleo, entrada or sys.stdin), name="ordenes", daemon=True
    )
    hilo.start()
    try:
        nucleo.correr()
    except OSError as error:
        detalle = f"No se pudo abrir el puerto {config.puerto}: {error}"
        log(detalle)
        informante.actualizar(estado=E.ERROR, detalle=detalle)
        return SALIDA_ERROR
    if getattr(nucleo, "error", None):
        return SALIDA_ERROR
    return SALIDA_OK
