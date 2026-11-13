"""Cifrado con la biblioteca que trae Windows (CNG, "bcrypt.dll").

¿Por qué no una biblioteca de Python? Porque esta viene con Windows: no hay que
instalar nada, el .exe pesa menos y está muy probada (es la misma que usa
Windows para sus propias conexiones seguras).

Se usan dos cosas:
  * AES-GCM: cifra cada mensaje y le agrega un "sello" de 16 bytes. Si alguien
    de la red cambia un solo bit, el sello no coincide y el mensaje se descarta.
  * ECDH P-256: dos PCs que nunca se vieron acuerdan una clave secreta mandándose
    solo datos públicos. Se usa una vez, al emparejar (ver red/emparejamiento.py).
"""

import ctypes
import hashlib
import hmac
from ctypes import wintypes as wt

_bcrypt = ctypes.WinDLL("bcrypt")

_STATUS_OK = 0
_STATUS_SELLO_INVALIDO = 0xC000A002  # STATUS_AUTH_TAG_MISMATCH
_VERSION_INFO_AUTENTICADA = 1
_MAGIA_ECDH_P256_PUBLICA = 0x314B4345  # "ECK1"

LARGO_CLAVE = 32
LARGO_SELLO = 16
LARGO_NONCE = 12
LARGO_PUBLICA = 64  # Punto de la curva: X e Y de 32 bytes cada uno.

_PUNTERO = ctypes.c_void_p
_ULONG = wt.ULONG


class _INFO_AUTENTICADA(ctypes.Structure):  # BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO
    _fields_ = [
        ("cbSize", _ULONG),
        ("dwInfoVersion", _ULONG),
        ("pbNonce", _PUNTERO),
        ("cbNonce", _ULONG),
        ("pbAuthData", _PUNTERO),
        ("cbAuthData", _ULONG),
        ("pbTag", _PUNTERO),
        ("cbTag", _ULONG),
        ("pbMacContext", _PUNTERO),
        ("cbMacContext", _ULONG),
        ("cbAAD", _ULONG),
        ("cbData", ctypes.c_ulonglong),
        ("dwFlags", _ULONG),
    ]


class _CABECERA_ECC(ctypes.Structure):  # BCRYPT_ECCKEY_BLOB
    _fields_ = [("dwMagic", _ULONG), ("cbKey", _ULONG)]


def _firmas():
    b = _bcrypt
    b.BCryptOpenAlgorithmProvider.argtypes = [
        ctypes.POINTER(_PUNTERO), wt.LPCWSTR, wt.LPCWSTR, _ULONG]
    b.BCryptSetProperty.argtypes = [_PUNTERO, wt.LPCWSTR, _PUNTERO, _ULONG, _ULONG]
    b.BCryptGenerateSymmetricKey.argtypes = [
        _PUNTERO, ctypes.POINTER(_PUNTERO), _PUNTERO, _ULONG, _PUNTERO, _ULONG, _ULONG]
    for nombre in ("BCryptEncrypt", "BCryptDecrypt"):
        getattr(b, nombre).argtypes = [
            _PUNTERO, _PUNTERO, _ULONG, _PUNTERO, _PUNTERO, _ULONG, _PUNTERO, _ULONG,
            ctypes.POINTER(_ULONG), _ULONG]
    b.BCryptDestroyKey.argtypes = [_PUNTERO]
    b.BCryptGenerateKeyPair.argtypes = [_PUNTERO, ctypes.POINTER(_PUNTERO), _ULONG, _ULONG]
    b.BCryptFinalizeKeyPair.argtypes = [_PUNTERO, _ULONG]
    b.BCryptExportKey.argtypes = [
        _PUNTERO, _PUNTERO, wt.LPCWSTR, _PUNTERO, _ULONG, ctypes.POINTER(_ULONG), _ULONG]
    b.BCryptImportKeyPair.argtypes = [
        _PUNTERO, _PUNTERO, wt.LPCWSTR, ctypes.POINTER(_PUNTERO), _PUNTERO, _ULONG, _ULONG]
    b.BCryptSecretAgreement.argtypes = [_PUNTERO, _PUNTERO, ctypes.POINTER(_PUNTERO), _ULONG]
    b.BCryptDeriveKey.argtypes = [
        _PUNTERO, wt.LPCWSTR, _PUNTERO, _PUNTERO, _ULONG, ctypes.POINTER(_ULONG), _ULONG]
    b.BCryptDestroySecret.argtypes = [_PUNTERO]
    for funcion in (
        b.BCryptOpenAlgorithmProvider, b.BCryptSetProperty, b.BCryptGenerateSymmetricKey,
        b.BCryptEncrypt, b.BCryptDecrypt, b.BCryptDestroyKey, b.BCryptGenerateKeyPair,
        b.BCryptFinalizeKeyPair, b.BCryptExportKey, b.BCryptImportKeyPair,
        b.BCryptSecretAgreement, b.BCryptDeriveKey, b.BCryptDestroySecret,
    ):
        funcion.restype = _ULONG  # NTSTATUS, sin signo para comparar fácil.


_firmas()


class ErrorCripto(Exception):
    """Windows no pudo cifrar o descifrar (o el mensaje fue alterado)."""


def _revisar(estado, que):
    if estado != _STATUS_OK:
        raise ErrorCripto(f"{que} falló (código 0x{estado:08X})")


def _abrir_algoritmo(nombre, modo=None):
    manejador = _PUNTERO()
    _revisar(_bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(manejador), nombre, None, 0),
             f"Abrir {nombre}")
    if modo:
        valor = ctypes.create_unicode_buffer(modo)
        _revisar(_bcrypt.BCryptSetProperty(manejador, "ChainingMode", valor,
                                           ctypes.sizeof(valor), 0), "Elegir modo")
    return manejador


# Los "proveedores" se abren una sola vez: abrirlos es lo más lento de todo.
_AES_GCM = _abrir_algoritmo("AES", "ChainingModeGCM")
_ECDH_P256 = _abrir_algoritmo("ECDH_P256")


# =====================================================================================
# Claves derivadas (HKDF con SHA-256, RFC 5869)
# =====================================================================================
def hkdf(clave, sal, info, largo):
    """Saca `largo` bytes de clave nueva a partir de una clave y datos públicos."""
    prk = hmac.new(sal or bytes(32), clave, hashlib.sha256).digest()
    salida, bloque, contador = b"", b"", 1
    while len(salida) < largo:
        bloque = hmac.new(prk, bloque + info + bytes([contador]), hashlib.sha256).digest()
        salida += bloque
        contador += 1
    return salida[:largo]


# =====================================================================================
# AES-GCM
# =====================================================================================
class Cifrador:
    """Cifra (o descifra) los mensajes de UN sentido de una conexión.

    Cada mensaje usa un número de orden distinto (el "nonce"): 0, 1, 2... Nunca se
    repite con la misma clave, y por eso cada sentido tiene su propia clave. Si
    alguien graba un mensaje y lo vuelve a mandar, llega con el número viejo y no
    se puede descifrar.

    No es seguro usar el mismo objeto desde dos hilos a la vez: quien lo usa tiene
    que protegerlo (Conexion y CanalDatos ya lo hacen).
    """

    _MAXIMO_CORTO = 4096  # Hasta este tamaño se reusa la memoria (mouse y teclado).

    def __init__(self, clave):
        if len(clave) != LARGO_CLAVE:
            raise ValueError("La clave tiene que medir 32 bytes")
        self._clave = _PUNTERO()
        self._memoria_clave = ctypes.create_string_buffer(bytes(clave), len(clave))
        _revisar(_bcrypt.BCryptGenerateSymmetricKey(
            _AES_GCM, ctypes.byref(self._clave), None, 0, self._memoria_clave, len(clave), 0),
            "Crear la clave")
        self._contador = 0
        self._nonce = ctypes.create_string_buffer(LARGO_NONCE)
        self._sello = ctypes.create_string_buffer(LARGO_SELLO)
        self._salida = ctypes.create_string_buffer(self._MAXIMO_CORTO)
        self._largo = _ULONG()
        info = _INFO_AUTENTICADA()
        info.cbSize = ctypes.sizeof(info)
        info.dwInfoVersion = _VERSION_INFO_AUTENTICADA
        info.pbNonce = ctypes.cast(self._nonce, _PUNTERO)
        info.cbNonce = LARGO_NONCE
        info.pbTag = ctypes.cast(self._sello, _PUNTERO)
        info.cbTag = LARGO_SELLO
        self._info = info
        self._info_ref = ctypes.byref(info)
        self._largo_ref = ctypes.byref(self._largo)

    def _proximo_nonce(self):
        # 4 bytes en cero + 8 bytes de contador. Con 2^64 mensajes no se acaba nunca.
        ctypes.memmove(self._nonce, (self._contador << 32).to_bytes(12, "little"), LARGO_NONCE)
        self._contador += 1

    def cifrar(self, datos):
        """Devuelve los datos cifrados seguidos del sello de 16 bytes."""
        self._proximo_nonce()
        largo = len(datos)
        salida = self._salida if largo <= self._MAXIMO_CORTO else ctypes.create_string_buffer(largo)
        estado = _bcrypt.BCryptEncrypt(
            self._clave, datos, largo, self._info_ref, None, 0, salida, largo,
            self._largo_ref, 0)
        _revisar(estado, "Cifrar")
        return salida.raw[:largo] + self._sello.raw

    def descifrar(self, paquete):
        """Recibe datos cifrados + sello. Lanza ErrorCripto si alguien los tocó."""
        largo = len(paquete) - LARGO_SELLO
        if largo < 0:
            raise ErrorCripto("Mensaje cifrado demasiado corto")
        paquete = bytes(paquete)
        self._proximo_nonce()
        ctypes.memmove(self._sello, paquete[largo:], LARGO_SELLO)
        salida = self._salida if largo <= self._MAXIMO_CORTO else ctypes.create_string_buffer(
            max(largo, 1))
        estado = _bcrypt.BCryptDecrypt(
            self._clave, paquete, largo, self._info_ref, None, 0, salida, largo,
            self._largo_ref, 0)
        if estado == _STATUS_SELLO_INVALIDO:
            raise ErrorCripto("El mensaje llegó alterado o con una clave que no es la de la sesión")
        _revisar(estado, "Descifrar")
        return salida.raw[:largo]

    def __del__(self):
        clave = getattr(self, "_clave", None)
        if clave:
            _bcrypt.BCryptDestroyKey(clave)
            self._clave = None


# =====================================================================================
# ECDH P-256 (acordar una clave entre dos PCs que no comparten ningún secreto)
# =====================================================================================
class ParDeClaves:
    """Una clave privada (no sale nunca de esta PC) y su parte pública (se manda)."""

    def __init__(self):
        self._clave = _PUNTERO()
        _revisar(_bcrypt.BCryptGenerateKeyPair(_ECDH_P256, ctypes.byref(self._clave), 256, 0),
                 "Generar el par de claves")
        _revisar(_bcrypt.BCryptFinalizeKeyPair(self._clave, 0), "Terminar el par de claves")
        memoria = ctypes.create_string_buffer(ctypes.sizeof(_CABECERA_ECC) + LARGO_PUBLICA)
        largo = _ULONG()
        _revisar(_bcrypt.BCryptExportKey(
            self._clave, None, "ECCPUBLICBLOB", memoria, len(memoria), ctypes.byref(largo), 0),
            "Exportar la clave pública")
        self.publica = memoria.raw[ctypes.sizeof(_CABECERA_ECC):largo.value]

    def acordar(self, publica_otra):
        """Devuelve 32 bytes secretos, iguales en las dos PCs. Lanza ErrorCripto si no sirve."""
        if len(publica_otra) != LARGO_PUBLICA:
            raise ErrorCripto("La clave pública de la otra PC no tiene el tamaño esperado")
        cabecera = _CABECERA_ECC(_MAGIA_ECDH_P256_PUBLICA, LARGO_PUBLICA // 2)
        blob = bytes(cabecera) + bytes(publica_otra)
        otra = _PUNTERO()
        secreto = _PUNTERO()
        # Windows comprueba al importar que el punto sea de la curva: una clave
        # pública trucada se rechaza acá.
        _revisar(_bcrypt.BCryptImportKeyPair(
            _ECDH_P256, None, "ECCPUBLICBLOB", ctypes.byref(otra), blob, len(blob), 0),
            "Leer la clave pública de la otra PC")
        try:
            _revisar(_bcrypt.BCryptSecretAgreement(self._clave, otra, ctypes.byref(secreto), 0),
                     "Acordar el secreto")
            try:
                salida = ctypes.create_string_buffer(64)
                largo = _ULONG()
                # "TRUNCATE" entrega el secreto tal cual; después se pasa por HKDF.
                _revisar(_bcrypt.BCryptDeriveKey(
                    secreto, "TRUNCATE", None, salida, 32, ctypes.byref(largo), 0),
                    "Derivar el secreto")
                return salida.raw[:largo.value]
            finally:
                _bcrypt.BCryptDestroySecret(secreto)
        finally:
            _bcrypt.BCryptDestroyKey(otra)

    def __del__(self):
        clave = getattr(self, "_clave", None)
        if clave:
            _bcrypt.BCryptDestroyKey(clave)
            self._clave = None
