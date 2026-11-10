"""Dónde está cada cosa: la carpeta del programa y cómo volver a ejecutarlo.

Sirve para arrancar el motor desde la interfaz y para el inicio automático.
Contempla el caso de que el programa esté empaquetado como .exe (etapa final).
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MAIN = RAIZ / "main.py"


def empaquetado():
    return bool(getattr(sys, "frozen", False))


def python_sin_consola():
    """pythonw.exe si existe: el mismo Python, pero sin abrir una ventana negra."""
    ejecutable = Path(sys.executable)
    sin_consola = ejecutable.with_name("pythonw.exe")
    return sin_consola if sin_consola.exists() else ejecutable


def comando(*argumentos):
    """Devuelve (programa, lista de argumentos) para ejecutar main.py con esos argumentos."""
    if empaquetado():
        return Path(sys.executable), list(argumentos)
    return python_sin_consola(), [str(MAIN), *argumentos]
