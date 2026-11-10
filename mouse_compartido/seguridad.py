"""Verificación del PIN entre las dos PCs.

El PIN nunca viaja por la red. Cada lado demuestra que lo conoce firmando números
al azar de esa conexión (HMAC-SHA256), así que grabar un saludo no sirve para
repetirlo después. El cliente se identifica primero: a quien no conoce el PIN el
servidor no le entrega ninguna firma.

Importante: esto controla QUIÉN se conecta, pero el tráfico posterior no va
cifrado. Usalo solo en una red de confianza (ver README).
"""

import hashlib
import hmac
import os

from . import protocolo as P
from .pantallas import DERECHA, IZQUIERDA

_SAL = b"mouse-compartido:v1"
_LARGO_NONCE = 16
_LARGO_FIRMA = 32
_LADOS = {0: IZQUIERDA, 1: DERECHA}
_CODIGO_LADO = {IZQUIERDA: 0, DERECHA: 1}


class FalloAutenticacion(Exception):
    """El saludo falló (PIN incorrecto, versión distinta, otro programa, etc.)."""


def derivar_clave(pin):
    """Convierte el PIN en una clave. Es lento a propósito para dificultar probar PINs."""
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), _SAL, 200_000)


def _firma(clave, etiqueta, nonce_s, nonce_c):
    return hmac.new(clave, etiqueta + nonce_s + nonce_c, hashlib.sha256).digest()


def autenticar_como_servidor(conexion, clave, lado_retorno, timeout=5.0):
    """Verifica a quien se conecta. Lanza FalloAutenticacion si no corresponde."""
    tipo, cuerpo = conexion.esperar_marco(timeout)
    if tipo != P.Tipo.HOLA or len(cuerpo) != 6 or cuerpo[:4] != P.MAGIA:
        raise FalloAutenticacion("Se conectó algo que no es este programa")
    if cuerpo[4] != P.VERSION:
        conexion.enviar(P.marco(P.Tipo.RECHAZADO, bytes([P.RECHAZO_VERSION])))
        raise FalloAutenticacion("El otro lado corre una versión distinta")
    if cuerpo[5] != P.CANAL_ENTRADA:
        conexion.enviar(P.marco(P.Tipo.RECHAZADO, bytes([P.RECHAZO_CANAL])))
        raise FalloAutenticacion("Canal todavía no soportado")

    nonce_s = os.urandom(_LARGO_NONCE)
    conexion.enviar(P.marco(P.Tipo.DESAFIO, nonce_s))

    tipo, cuerpo = conexion.esperar_marco(timeout)
    if tipo != P.Tipo.RESPUESTA or len(cuerpo) != _LARGO_NONCE + _LARGO_FIRMA:
        raise FalloAutenticacion("Respuesta inválida")
    nonce_c, firma = cuerpo[:_LARGO_NONCE], cuerpo[_LARGO_NONCE:]
    if not hmac.compare_digest(firma, _firma(clave, b"cliente", nonce_s, nonce_c)):
        conexion.enviar(P.marco(P.Tipo.RECHAZADO, bytes([P.RECHAZO_PIN])))
        raise FalloAutenticacion("PIN incorrecto")

    cuerpo = _firma(clave, b"servidor", nonce_s, nonce_c) + bytes([_CODIGO_LADO[lado_retorno]])
    conexion.enviar(P.marco(P.Tipo.ACEPTADO, cuerpo))


def autenticar_como_cliente(conexion, clave, timeout=5.0):
    """Se identifica ante el servidor. Devuelve el borde por el que se vuelve."""
    conexion.enviar(P.marco(P.Tipo.HOLA, P.MAGIA + bytes([P.VERSION, P.CANAL_ENTRADA])))

    tipo, nonce_s = conexion.esperar_marco(timeout)
    if tipo == P.Tipo.RECHAZADO:
        raise FalloAutenticacion("El servidor corre una versión distinta")
    if tipo != P.Tipo.DESAFIO or len(nonce_s) != _LARGO_NONCE:
        raise FalloAutenticacion("Lo que respondió no es este programa")

    nonce_c = os.urandom(_LARGO_NONCE)
    conexion.enviar(P.marco(P.Tipo.RESPUESTA, nonce_c + _firma(clave, b"cliente", nonce_s, nonce_c)))

    tipo, cuerpo = conexion.esperar_marco(timeout)
    if tipo == P.Tipo.RECHAZADO:
        raise FalloAutenticacion("PIN incorrecto: revisá que sea igual en las dos PCs")
    if tipo != P.Tipo.ACEPTADO or len(cuerpo) != _LARGO_FIRMA + 1:
        raise FalloAutenticacion("Respuesta inválida del servidor")
    if not hmac.compare_digest(cuerpo[:_LARGO_FIRMA], _firma(clave, b"servidor", nonce_s, nonce_c)):
        raise FalloAutenticacion("El servidor no conoce el PIN")
    lado = _LADOS.get(cuerpo[_LARGO_FIRMA])
    if lado is None:
        raise FalloAutenticacion("Respuesta inválida del servidor")
    return lado
