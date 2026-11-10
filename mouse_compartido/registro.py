"""Mensajes por consola que nunca frenan al mouse.

Si el hilo que atiende el mouse escribiera directo en la consola podría quedar
trabado (por ejemplo, Windows pausa las escrituras si seleccionás texto en la
ventana negra). Por eso los mensajes van a una cola y los imprime un hilo aparte.
"""

import queue
import threading
import time

_cola = queue.SimpleQueue()
_hilo = None


def log(mensaje):
    """Encola un mensaje para mostrarlo. Es seguro llamarla desde cualquier hilo."""
    _cola.put(f"[{time.strftime('%H:%M:%S')}] {mensaje}")


def _escritor():
    while True:
        print(_cola.get(), flush=True)


def iniciar():
    """Arranca el hilo que imprime. Se llama una sola vez al abrir el programa."""
    global _hilo
    if _hilo is None:
        _hilo = threading.Thread(target=_escritor, name="registro", daemon=True)
        _hilo.start()


def vaciar():
    """Da un instante para que se impriman los últimos mensajes antes de salir."""
    for _ in range(20):
        if _cola.empty():
            break
        time.sleep(0.01)
