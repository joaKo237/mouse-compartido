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
  * El motor le escribe eventos, uno por línea, en JSON:
        {"evento": "log", "texto": "..."}
        {"evento": "estado", "estado": "conectado", ...}   (ver estado.py)
Si la interfaz se cierra de golpe, la entrada se corta y el motor termina solo:
nunca queda un motor huérfano bloqueando el mouse.
"""

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
            elif orden == "salir":
                break
    except (OSError, ValueError):
        pass
    # Pidió salir, o se cerró la interfaz (fin de la entrada).
    nucleo.detener()


def correr_motor(config, entrada=None):
    """Arranca el servidor o el cliente según la configuración. Devuelve el código de salida."""
    registro.usar_json()
    informante = E.Informante(emitir=registro.emitir, rol=config.rol)
    problemas = config.errores()
    if problemas:
        informante.actualizar(estado=E.ERROR, detalle=" ".join(problemas))
        return SALIDA_CONFIG
    if not W.es_administrador():
        log("Aviso: sin permisos de Administrador no se controlan las ventanas elevadas "
            "(Administrador de tareas, instaladores, etc.).")

    if config.rol == SERVIDOR:
        nucleo = Servidor(config, informante=informante)
    else:
        nucleo = Cliente(config, informante=informante)

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
