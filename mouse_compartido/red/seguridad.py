"""El saludo entre las dos PCs: se reconocen por el emparejamiento y arman claves nuevas.

Al emparejarlas (una sola vez, ver emparejamiento.py) las dos PCs se quedan con
la misma clave secreta de 32 bytes. Esa clave nunca viaja por la red. En cada
conexión:

  1. El cliente dice quién es (su número de identidad) y manda un número al azar.
  2. El servidor dice quién es y manda otro número al azar.
  3. Cada uno demuestra que conoce la clave firmando todo lo que se dijo
     (HMAC-SHA256). El cliente firma primero: a quien no tiene la clave el
     servidor no le muestra ninguna firma.
  4. Con la clave y los dos números al azar, cada lado calcula dos claves nuevas,
     una para cada sentido, que solo sirven para esta conexión. Desde ahí, todo
     lo que viaja va cifrado con AES-GCM (ver sistema/cripto.py).

Grabar una conexión no sirve de nada: la próxima usa números al azar distintos.
"""

import hashlib
import hmac
import os
from dataclasses import dataclass

from ..comun.pantallas import ABAJO, ARRIBA, DERECHA, IZQUIERDA
from ..sistema.cripto import hkdf
from . import protocolo as P

LARGO_ID = 16
_LARGO_NONCE = 16
_LARGO_FIRMA = 32
_LARGO_HOLA = len(P.MAGIA) + 2 + LARGO_ID + _LARGO_NONCE
_LARGO_DESAFIO = LARGO_ID + _LARGO_NONCE
_LADOS = {0: IZQUIERDA, 1: DERECHA, 2: ARRIBA, 3: ABAJO}
_CODIGO_LADO = {lado: codigo for codigo, lado in _LADOS.items()}


class FalloAutenticacion(Exception):
    """El saludo falló (no está emparejada, versión distinta, otro programa, etc.)."""


class CanalNoDisponible(FalloAutenticacion):
    """La otra PC no atiende ese canal, ahora o nunca. No es un problema de clave."""


class NoEmparejada(FalloAutenticacion):
    """La otra PC no reconoce a esta (por ejemplo, la olvidaron o se emparejó con otra)."""


@dataclass(frozen=True)
class Emparejamiento:
    """Lo que esta PC sabe de la otra: quién es cada una y la clave que comparten."""

    id_propio: bytes
    id_otra: bytes
    clave: bytes

    @classmethod
    def desde_config(cls, config):
        """Lo arma con lo guardado en config.json. Devuelve None si falta emparejar."""
        try:
            id_propio = bytes.fromhex(config.id_pc)
            id_otra = bytes.fromhex(config.emparejado_id)
            clave = bytes.fromhex(config.emparejado_clave)
        except ValueError:
            return None
        if len(id_propio) != LARGO_ID or len(id_otra) != LARGO_ID or len(clave) != 32:
            return None
        return cls(id_propio, id_otra, clave)


@dataclass(frozen=True)
class ClavesSesion:
    """Resultado del saludo: para qué es la conexión y con qué claves se cifra."""

    canal: int
    lado: str  # En el cliente: por qué borde se vuelve. En el servidor: "".
    envio: bytes
    recepcion: bytes


def nuevo_id():
    """Un número de identidad nuevo para esta PC (en hexadecimal, para el config)."""
    return os.urandom(LARGO_ID).hex()


def _firma(clave, etiqueta, transcripcion):
    return hmac.new(clave, etiqueta + transcripcion, hashlib.sha256).digest()


def _claves(clave, nonce_c, nonce_s, canal):
    """Dos claves de 32 bytes: (del cliente al servidor, del servidor al cliente)."""
    material = hkdf(clave, nonce_c + nonce_s, b"mouse-compartido sesion" + bytes([canal]), 64)
    return material[:32], material[32:]


def autenticar_como_servidor(conexion, emparejamiento, lado_retorno, timeout=5.0,
                             canales=(P.CANAL_ENTRADA,)):
    """Verifica a quien se conecta. Devuelve ClavesSesion.

    `canales` son los que se atienden en este momento. Lanza FalloAutenticacion si
    no corresponde, o CanalNoDisponible si pidió un canal que ahora no se atiende.
    """
    tipo, hola = conexion.esperar_marco(timeout)
    if tipo != P.Tipo.HOLA or len(hola) < 6 or hola[:4] != P.MAGIA:
        raise FalloAutenticacion("Se conectó algo que no es este programa")
    if hola[4] != P.VERSION:
        conexion.enviar(P.marco(P.Tipo.RECHAZADO, bytes([P.RECHAZO_VERSION])))
        raise FalloAutenticacion("El otro lado corre una versión distinta del programa")
    if len(hola) != _LARGO_HOLA:
        raise FalloAutenticacion("Saludo inválido")
    canal = hola[5]
    if canal not in (P.CANAL_ENTRADA, P.CANAL_DATOS):
        conexion.enviar(P.marco(P.Tipo.RECHAZADO, bytes([P.RECHAZO_CANAL])))
        raise CanalNoDisponible("Pidió un canal que este programa no conoce")
    if emparejamiento is None or hola[6:6 + LARGO_ID] != emparejamiento.id_otra:
        conexion.enviar(P.marco(P.Tipo.RECHAZADO, bytes([P.RECHAZO_DESCONOCIDO])))
        raise NoEmparejada("Se conectó una PC que no está emparejada con esta")
    if canal not in canales:
        # Lo conocemos, pero ahora no corresponde (por ejemplo, el canal de datos sin
        # una sesión abierta). Se corta sin responder y el otro lado reintenta después.
        raise CanalNoDisponible("Ese canal no se atiende en este momento")
    nonce_c = hola[6 + LARGO_ID:]

    nonce_s = os.urandom(_LARGO_NONCE)
    desafio = emparejamiento.id_propio + nonce_s
    conexion.enviar(P.marco(P.Tipo.DESAFIO, desafio))
    transcripcion = hola + desafio

    tipo, cuerpo = conexion.esperar_marco(timeout)
    if tipo != P.Tipo.RESPUESTA or len(cuerpo) != _LARGO_FIRMA:
        raise FalloAutenticacion("Respuesta inválida")
    clave = emparejamiento.clave
    if not hmac.compare_digest(cuerpo, _firma(clave, b"cliente", transcripcion)):
        conexion.enviar(P.marco(P.Tipo.RECHAZADO, bytes([P.RECHAZO_CLAVE])))
        raise NoEmparejada("La otra PC no tiene la clave del emparejamiento")

    cuerpo = _firma(clave, b"servidor", transcripcion) + bytes([_CODIGO_LADO[lado_retorno]])
    conexion.enviar(P.marco(P.Tipo.ACEPTADO, cuerpo))
    del_cliente, del_servidor = _claves(clave, nonce_c, nonce_s, canal)
    return ClavesSesion(canal, "", envio=del_servidor, recepcion=del_cliente)


def autenticar_como_cliente(conexion, emparejamiento, timeout=5.0, canal=P.CANAL_ENTRADA):
    """Se identifica ante el servidor. Devuelve ClavesSesion (con el borde de regreso)."""
    nonce_c = os.urandom(_LARGO_NONCE)
    hola = P.MAGIA + bytes([P.VERSION, canal]) + emparejamiento.id_propio + nonce_c
    conexion.enviar(P.marco(P.Tipo.HOLA, hola))

    tipo, desafio = conexion.esperar_marco(timeout)
    if tipo == P.Tipo.RECHAZADO:
        motivo = desafio[:1]
        if motivo == bytes([P.RECHAZO_CANAL]):
            raise CanalNoDisponible(
                "La otra PC tiene una versión del programa sin esta función: actualizala"
            )
        if motivo == bytes([P.RECHAZO_DESCONOCIDO]):
            raise NoEmparejada(
                "La otra PC no reconoce a esta. Emparejalas de nuevo (página Conexión)"
            )
        raise FalloAutenticacion(
            "La otra PC tiene otra versión del programa: instalá la misma en las dos"
        )
    if tipo != P.Tipo.DESAFIO or len(desafio) != _LARGO_DESAFIO:
        raise FalloAutenticacion("Lo que respondió no es este programa")
    if desafio[:LARGO_ID] != emparejamiento.id_otra:
        raise NoEmparejada("En esa dirección hay otra PC, no la emparejada")
    nonce_s = desafio[LARGO_ID:]
    transcripcion = hola + desafio
    clave = emparejamiento.clave
    conexion.enviar(P.marco(P.Tipo.RESPUESTA, _firma(clave, b"cliente", transcripcion)))

    tipo, cuerpo = conexion.esperar_marco(timeout)
    if tipo == P.Tipo.RECHAZADO:
        raise NoEmparejada(
            "La otra PC no acepta la clave de esta. Emparejalas de nuevo (página Conexión)"
        )
    if tipo != P.Tipo.ACEPTADO or len(cuerpo) != _LARGO_FIRMA + 1:
        raise FalloAutenticacion("Respuesta inválida del servidor")
    if not hmac.compare_digest(cuerpo[:_LARGO_FIRMA], _firma(clave, b"servidor", transcripcion)):
        raise NoEmparejada("La PC que respondió no tiene la clave del emparejamiento")
    lado = _LADOS.get(cuerpo[_LARGO_FIRMA])
    if lado is None:
        raise FalloAutenticacion("Respuesta inválida del servidor")
    del_cliente, del_servidor = _claves(clave, nonce_c, nonce_s, canal)
    return ClavesSesion(canal, lado, envio=del_cliente, recepcion=del_servidor)
