"""Mensajes que nunca frenan al mouse.

Si el hilo que atiende el mouse escribiera directo en la consola podría quedar
trabado (por ejemplo, Windows pausa las escrituras si seleccionás texto en la
ventana negra). Por eso los mensajes van a una cola y los escribe un hilo aparte.

Hay dos formas de escribir:
  * Consola (menú de texto): cada mensaje es una línea legible con la hora.
  * JSON (motor manejado por la interfaz): cada línea es un objeto JSON, que la
    interfaz lee para mostrar el estado y la actividad.
"""

import json
import queue
import threading
import time

_cola = queue.SimpleQueue()
_hilo = None
_modo_json = False


def usar_json():
    """El motor corre bajo la interfaz: a partir de ahora todo sale como JSON."""
    global _modo_json
    _modo_json = True


def es_consola():
    return not _modo_json


def log(mensaje):
    """Encola un mensaje para mostrarlo. Es seguro llamarla desde cualquier hilo."""
    _cola.put(("log", f"[{time.strftime('%H:%M:%S')}] {mensaje}"))


def emitir(evento):
    """Encola un evento para la interfaz (un dict). En la consola no se muestra."""
    if _modo_json:
        _cola.put(("evento", evento))


def _escribir(tipo, dato):
    if _modo_json:
        if tipo == "log":
            dato = {"evento": "log", "texto": dato}
        # ensure_ascii deja todo en ASCII puro: los acentos viajan como á y
        # no hay problemas de codificación entre procesos.
        print(json.dumps(dato), flush=True)
    elif tipo == "log":
        print(dato, flush=True)


def _escritor():
    while True:
        tipo, dato = _cola.get()
        try:
            _escribir(tipo, dato)
        except (OSError, ValueError):
            pass  # La interfaz se cerró: no hay a quién escribirle.


def iniciar():
    """Arranca el hilo que escribe. Se llama una sola vez al abrir el programa."""
    global _hilo
    if _hilo is None:
        _hilo = threading.Thread(target=_escritor, name="registro", daemon=True)
        _hilo.start()


def vaciar():
    """Da un instante para que se escriban los últimos mensajes antes de salir."""
    for _ in range(50):
        if _cola.empty():
            break
        time.sleep(0.01)
    time.sleep(0.02)
