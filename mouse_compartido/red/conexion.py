"""Conexión TCP ajustada para latencia mínima.

Puntos clave:
  * TCP_NODELAY: desactiva el algoritmo de Nagle, que junta mensajes chicos y
    los demora. Cada evento sale apenas se genera.
  * Envío NO bloqueante: el envío se hace desde el hilo del mouse, y ese hilo
    jamás puede quedarse esperando a la red (si tarda, Windows frena el mouse de
    toda la PC y termina quitando el gancho). Si el buffer de TCP se llena, los
    bytes quedan en `_pendiente` y salen en cuanto se pueda.
  * Cifrado: después del saludo, cada marco viaja cifrado y sellado (ver
    activar_cifrado). Cifrar un movimiento tarda unos 3 microsegundos.
"""

import select
import socket
import struct
import threading
import time

from ..sistema.cripto import Cifrador
from . import protocolo as P

_S_LARGO = struct.Struct("<H")


class ConexionCerrada(Exception):
    """La conexión se cortó."""


def ips_locales():
    """Devuelve las IPv4 de esta PC, primero la que se usa para salir a la red."""
    ips = []
    sonda = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # connect() en UDP no manda nada: solo hace que Windows elija la interfaz.
        sonda.connect(("10.255.255.255", 1))
        ips.append(sonda.getsockname()[0])
    except OSError:
        pass
    finally:
        sonda.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips


class Conexion:
    LIMITE_PENDIENTE = 256 * 1024  # Si se acumula tanto, la red está muerta.

    def __init__(self, sock):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # Buffer de envío chico: ante un corte breve no se apilan movimientos viejos.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32 * 1024)
        sock.setblocking(False)
        self._sock = sock
        self._candado = threading.Lock()
        self._pendiente = bytearray()
        self._cerrada = False
        self._lector = P.LectorMarcos()
        self._memoria = bytearray(64 * 1024)
        self._cifrador = None  # Para lo que se manda (None = todavía sin cifrar).

    @property
    def cifrada(self):
        return self._cifrador is not None

    def activar_cifrado(self, clave_envio, clave_recepcion):
        """Desde ahora, todo lo que se manda y recibe va cifrado (se llama tras el saludo)."""
        with self._candado:
            self._cifrador = Cifrador(clave_envio)
            self._lector = P.LectorMarcos(descifrar=Cifrador(clave_recepcion).descifrar)

    def _sellar(self, datos):
        """Cifra cada marco de `datos`, que puede traer uno o varios seguidos."""
        cifrar = self._cifrador.cifrar
        largo = _S_LARGO.unpack_from(datos)[0]
        if largo + 2 == len(datos):  # Lo normal: un solo marco.
            cifrado = cifrar(bytes(datos[2:]))
            return _S_LARGO.pack(len(cifrado)) + cifrado
        salida = bytearray()
        posicion = 0
        while posicion < len(datos):
            largo = _S_LARGO.unpack_from(datos, posicion)[0]
            cifrado = cifrar(bytes(datos[posicion + 2:posicion + 2 + largo]))
            salida += _S_LARGO.pack(len(cifrado)) + cifrado
            posicion += 2 + largo
        return bytes(salida)

    @property
    def cerrada(self):
        return self._cerrada

    def enviar(self, datos):
        """Envía sin bloquear nunca. Devuelve False si la conexión ya no sirve."""
        with self._candado:
            if self._cerrada:
                return False
            if self._cifrador is not None:
                # Dentro del candado: el orden de cifrado tiene que ser el de envío.
                datos = self._sellar(datos)
            if self._pendiente:
                self._pendiente += datos
                return self._vaciar_sin_candado()
            try:
                enviados = self._sock.send(datos)
            except BlockingIOError:
                enviados = 0
            except OSError:
                self._cerrar_sin_candado()
                return False
            if enviados < len(datos):
                self._pendiente += datos[enviados:]
            return True

    def vaciar(self):
        """Intenta mandar lo que haya quedado pendiente."""
        with self._candado:
            if not self._cerrada and self._pendiente:
                self._vaciar_sin_candado()

    def _vaciar_sin_candado(self):
        while self._pendiente:
            try:
                enviados = self._sock.send(self._pendiente)
            except BlockingIOError:
                break
            except OSError:
                self._cerrar_sin_candado()
                return False
            del self._pendiente[:enviados]
        if len(self._pendiente) > self.LIMITE_PENDIENTE:
            self._cerrar_sin_candado()
            return False
        return True

    def recibir(self, timeout):
        """Espera hasta `timeout` segundos y devuelve los marcos recibidos (o lista vacía)."""
        try:
            listos, _, _ = select.select([self._sock], [], [], timeout)
            if not listos:
                return []
            cantidad = self._sock.recv_into(self._memoria)
        except BlockingIOError:
            return []
        except (OSError, ValueError) as error:
            self.cerrar()
            raise ConexionCerrada(str(error)) from error
        if cantidad == 0:
            self.cerrar()
            raise ConexionCerrada("El otro lado cerró la conexión")
        try:
            return self._lector.alimentar(memoryview(self._memoria)[:cantidad])
        except P.ErrorProtocolo as error:
            self.cerrar()
            raise ConexionCerrada(str(error)) from error

    def esperar_marco(self, timeout):
        """Devuelve un solo marco, sin cifrar. Lo usa el saludo.

        Lee justo los bytes de ese marco y ni uno más: lo que venga después (ya
        cifrado, o del canal de datos) queda intacto para quien siga. Lanza
        TimeoutError si no llega a tiempo.
        """
        limite = time.perf_counter() + timeout
        cabecera = self._leer_justo(2, limite)
        largo = _S_LARGO.unpack(cabecera)[0]
        if largo == 0:
            self.cerrar()
            raise ConexionCerrada("Marco de largo cero")
        datos = self._leer_justo(largo, limite)
        return datos[0], datos[1:]

    def _leer_justo(self, cantidad, limite):
        datos = bytearray()
        while len(datos) < cantidad:
            restante = limite - time.perf_counter()
            if restante <= 0:
                raise TimeoutError("El otro lado no respondió a tiempo")
            try:
                listos, _, _ = select.select([self._sock], [], [], restante)
                if not listos:
                    continue
                parte = self._sock.recv(cantidad - len(datos))
            except BlockingIOError:
                continue
            except (OSError, ValueError) as error:
                self.cerrar()
                raise ConexionCerrada(str(error)) from error
            if not parte:
                self.cerrar()
                raise ConexionCerrada("El otro lado cerró la conexión")
            datos += parte
        return bytes(datos)

    def entregar_socket(self):
        """Deja de usar la conexión y devuelve el socket tal cual, en modo bloqueante.

        Sirve para pasarle el canal de datos a la interfaz (otro proceso) apenas
        terminó el saludo. Lanza ConexionCerrada si quedaron bytes a medio mandar o
        a medio leer: pasar el socket así mezclaría los mensajes.
        """
        with self._candado:
            if self._cerrada or self._pendiente or not self._lector.vacio:
                self._cerrar_sin_candado()
                raise ConexionCerrada("La conexión no quedó limpia para entregarla")
            self._cerrada = True
            sock = self._sock
        sock.setblocking(True)
        return sock

    def _cerrar_sin_candado(self):
        self._cerrada = True
        try:
            self._sock.close()
        except OSError:
            pass

    def cerrar(self):
        with self._candado:
            if not self._cerrada:
                self._cerrar_sin_candado()


class Sesion:
    """Lo que necesita una función extra (portapapeles, etc.) para usar la conexión."""

    def __init__(self, conexion):
        self._conexion = conexion
        self._manejadores = {}

    def enviar(self, tipo, cuerpo=b""):
        return self._conexion.enviar(P.marco(tipo, cuerpo))

    def registrar(self, tipo, manejador):
        """Hace que `manejador(cuerpo)` se llame cada vez que llegue un mensaje de ese tipo.

        Corre en el hilo de red: si tiene trabajo pesado debe lanzarlo en otro hilo.
        """
        self._manejadores[tipo] = manejador

    def despachar(self, tipo, cuerpo):
        manejador = self._manejadores.get(tipo)
        if manejador is not None:
            manejador(cuerpo)
