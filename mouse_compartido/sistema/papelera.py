"""Mandar un archivo a la Papelera de reciclaje (en vez de borrarlo para siempre).

La carpeta compartida usa esto cuando un archivo se borró en la otra PC: si fue
un error, lo recuperás de la Papelera.
"""

import ctypes
from ctypes import wintypes as wt

_FO_DELETE = 3
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040  # Esto es lo que hace que vaya a la Papelera.
_FOF_NOERRORUI = 0x0400


class _OPERACION(ctypes.Structure):  # SHFILEOPSTRUCTW
    _fields_ = [
        ("hwnd", wt.HWND),
        ("wFunc", wt.UINT),
        ("pFrom", wt.LPCWSTR),
        ("pTo", wt.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wt.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wt.LPCWSTR),
    ]


_shell32 = ctypes.WinDLL("shell32")
_shell32.SHFileOperationW.argtypes = [ctypes.POINTER(_OPERACION)]
_shell32.SHFileOperationW.restype = ctypes.c_int


def a_la_papelera(ruta):
    """Lanza OSError si Windows no pudo."""
    operacion = _OPERACION()
    operacion.wFunc = _FO_DELETE
    operacion.pFrom = str(ruta) + "\0"  # La lista termina con dos ceros (ctypes pone uno).
    operacion.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI
    resultado = _shell32.SHFileOperationW(ctypes.byref(operacion))
    if resultado != 0 or operacion.fAnyOperationsAborted:
        raise OSError(f"Windows no pudo mandarlo a la Papelera (código {resultado})")
