"""Escribir en el portapapeles de Windows directamente, sin pasar por Qt.

¿Por qué no con Qt? Al poner una imagen, Qt la ofrece en unos 20 formatos (BMP,
JPEG, TIFF, WebP, íconos...) y para dejarla guardada en Windows tiene que
convertirla a todos. Con una captura de pantalla común tardaba un segundo, con la
ventana trabada. Acá se ponen solo los formatos que de verdad usan los programas.

Para leer sí se usa Qt (ui/portapapeles.py): ahí se pide un formato a la vez.
"""

import ctypes
import time
from ctypes import wintypes as wt

from .win32 import kernel32, user32

CF_DIB = 8  # Imagen "clásica" de Windows: la entienden Paint, Word, WhatsApp...
CF_UNICODETEXT = 13
CF_HDROP = 15
_GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = (wt.HWND,)
user32.OpenClipboard.restype = wt.BOOL
user32.CloseClipboard.argtypes = ()
user32.CloseClipboard.restype = wt.BOOL
user32.EmptyClipboard.argtypes = ()
user32.EmptyClipboard.restype = wt.BOOL
user32.SetClipboardData.argtypes = (wt.UINT, wt.HANDLE)
user32.SetClipboardData.restype = wt.HANDLE
user32.RegisterClipboardFormatW.argtypes = (wt.LPCWSTR,)
user32.RegisterClipboardFormatW.restype = wt.UINT
kernel32.GlobalAlloc.argtypes = (wt.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalLock.argtypes = (wt.HGLOBAL,)
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = (wt.HGLOBAL,)
kernel32.GlobalUnlock.restype = wt.BOOL
kernel32.GlobalFree.argtypes = (wt.HGLOBAL,)
kernel32.GlobalFree.restype = wt.HGLOBAL

_registrados = {}


def formato(nombre):
    """El número que Windows le asigna a un formato con nombre (por ejemplo "PNG")."""
    numero = _registrados.get(nombre)
    if numero is None:
        numero = user32.RegisterClipboardFormatW(nombre)
        if not numero:
            raise OSError(f"Windows no registró el formato {nombre}")
        _registrados[nombre] = numero
    return numero


def _abrir(intentos=50):
    """Otro programa puede tener el portapapeles abierto un instante: se reintenta."""
    for _ in range(intentos):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.01)
    raise OSError("Otro programa tiene ocupado el portapapeles")


def _memoria_con(datos):
    """Copia los datos a un bloque de memoria que después pasa a ser de Windows."""
    bloque = kernel32.GlobalAlloc(_GMEM_MOVEABLE, max(1, len(datos)))
    if not bloque:
        raise MemoryError("No hay memoria para el portapapeles")
    puntero = kernel32.GlobalLock(bloque)
    if not puntero:
        kernel32.GlobalFree(bloque)
        raise MemoryError("No hay memoria para el portapapeles")
    ctypes.memmove(puntero, datos, len(datos))
    kernel32.GlobalUnlock(bloque)
    return bloque


def poner(formatos):
    """Reemplaza el portapapeles por estos formatos: lista de (número de formato, bytes).

    Lanza OSError si otro programa lo tiene ocupado demasiado tiempo.
    """
    _abrir()
    try:
        if not user32.EmptyClipboard():
            raise OSError("Windows no dejó vaciar el portapapeles")
        for numero, datos in formatos:
            bloque = _memoria_con(datos)
            if not user32.SetClipboardData(numero, bloque):
                kernel32.GlobalFree(bloque)  # Si Windows no lo aceptó, sigue siendo nuestro.
    finally:
        user32.CloseClipboard()
