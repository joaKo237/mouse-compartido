"""Las placas de red de esta PC: qué IP tiene cada una y si es por cable o Wi-Fi.

Sirve para dos cosas:
  * Anunciarse en TODAS las redes (Windows, si no se le dice nada, manda los
    avisos solo por la principal, y el cable directo entre dos PCs quedaría afuera).
  * Elegir el mejor camino hasta la otra PC: si se la ve por cable y por Wi-Fi,
    se usa el cable (menos demora y sin cortes).

Se le pregunta a Windows con GetIpAddrTable (IP, máscara y número de placa) y
ConvertInterfaceIndexToLuid (de ahí sale el tipo de placa).
"""

import ctypes
import ipaddress
import socket
import struct
from ctypes import wintypes as wt
from dataclasses import dataclass

CABLE = 0
WIFI = 1
OTRA = 2
SIN_RUTA = 3  # La otra PC no está en ninguna de las redes de esta (pasa por un router).

NOMBRES_RUTA = {CABLE: "cable", WIFI: "Wi-Fi", OTRA: "red", SIN_RUTA: "red"}

_TIPO_ETHERNET = 6
_TIPO_WIFI = 71
_TIPO_LOOPBACK = 24
_DESCONECTADA = 0x08
_BORRADA = 0x40


class _FILA(ctypes.Structure):  # MIB_IPADDRROW
    _fields_ = [
        ("dwAddr", wt.DWORD),
        ("dwIndex", wt.DWORD),
        ("dwMask", wt.DWORD),
        ("dwBCastAddr", wt.DWORD),
        ("dwReasmSize", wt.DWORD),
        ("unused1", ctypes.c_ushort),
        ("wType", ctypes.c_ushort),
    ]


try:
    _iphlpapi = ctypes.WinDLL("iphlpapi")
    _iphlpapi.GetIpAddrTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.ULONG), wt.BOOL]
    _iphlpapi.GetIpAddrTable.restype = wt.DWORD
    _iphlpapi.ConvertInterfaceIndexToLuid.argtypes = [
        wt.DWORD, ctypes.POINTER(ctypes.c_uint64)]
    _iphlpapi.ConvertInterfaceIndexToLuid.restype = wt.DWORD
except (OSError, AttributeError):  # Fuera de Windows (no debería pasar).
    _iphlpapi = None


@dataclass(frozen=True)
class Placa:
    ip: str
    mascara: str
    tipo: int  # CABLE, WIFI u OTRA

    @property
    def red(self):
        return ipaddress.IPv4Network(f"{self.ip}/{self.mascara}", strict=False)

    @property
    def difusion(self):
        """Dirección para avisarle a toda esa red (por ejemplo 192.168.1.255)."""
        return str(self.red.broadcast_address)


def _ip(valor):
    # Windows guarda la IP en el orden de la red: se la convierte así.
    return socket.inet_ntoa(struct.pack("<I", valor))


def _tipo(indice):
    luid = ctypes.c_uint64()
    if _iphlpapi.ConvertInterfaceIndexToLuid(indice, ctypes.byref(luid)) != 0:
        return OTRA
    tipo = (luid.value >> 48) & 0xFFFF  # El tipo de placa está en los 16 bits de arriba.
    if tipo == _TIPO_ETHERNET:
        return CABLE
    if tipo == _TIPO_WIFI:
        return WIFI
    if tipo == _TIPO_LOOPBACK:
        return None
    return OTRA


def placas():
    """Devuelve las placas con IPv4 que están conectadas (sin la de 127.0.0.1)."""
    if _iphlpapi is None:
        return []
    largo = wt.ULONG(0)
    _iphlpapi.GetIpAddrTable(None, ctypes.byref(largo), False)
    if not largo.value:
        return []
    memoria = ctypes.create_string_buffer(largo.value)
    if _iphlpapi.GetIpAddrTable(memoria, ctypes.byref(largo), False) != 0:
        return []
    cantidad = struct.unpack_from("<I", memoria)[0]
    filas = (_FILA * cantidad).from_buffer(memoria, 4)
    resultado = []
    for fila in filas:
        if fila.wType & (_DESCONECTADA | _BORRADA):
            continue
        ip = _ip(fila.dwAddr)
        if ip.startswith("127.") or ip == "0.0.0.0":
            continue
        tipo = _tipo(fila.dwIndex)
        if tipo is None:
            continue
        resultado.append(Placa(ip, _ip(fila.dwMask), tipo))
    resultado.sort(key=lambda p: p.tipo)
    return resultado


def prioridad(ip_otra, lista=None):
    """¿Por dónde se llega a esa IP? CABLE, WIFI, OTRA o SIN_RUTA (menor = mejor)."""
    try:
        destino = ipaddress.IPv4Address(ip_otra)
    except ValueError:
        return SIN_RUTA
    mejor = SIN_RUTA
    for placa in placas() if lista is None else lista:
        if destino in placa.red and placa.tipo < mejor:
            mejor = placa.tipo
    return mejor
