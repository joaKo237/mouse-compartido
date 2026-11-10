"""Conexión TCP ajustada para latencia mínima.

Puntos clave:
  * TCP_NODELAY: desactiva el algoritmo de Nagle, que junta mensajes chicos y
    los demora. Cada evento sale apenas se genera.
  * Envío NO bloqueante: el envío se hace desde el hilo del mouse, y ese hilo
    jamás puede quedarse esperando a la red (si tarda, Windows frena el mouse de
    toda la PC y termina quitando el gancho). Si el buffer de TCP se llena, los
    bytes quedan en `_pendiente` y salen en cuanto se pueda.
"""

import collections
import select
import socket
import threading
import time

from . import protocolo as P


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
        self._cola = collections.deque()

    @property
    def cerrada(self):
        return self._cerrada

    def enviar(self, datos):
        """Envía sin bloquear nunca. Devuelve False si la conexión ya no sirve."""
        with self._candado:
            if self._cerrada:
                return False
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
        if self._cola:
            marcos = list(self._cola)
            self._cola.clear()
            return marcos
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
        """Devuelve un solo marco. Lanza TimeoutError si no llega a tiempo."""
        limite = time.perf_counter() + timeout
        while not self._cola:
            restante = limite - time.perf_counter()
            if restante <= 0:
                raise TimeoutError("El otro lado no respondió a tiempo")
            self._cola.extend(self.recibir(restante))
        return self._cola.popleft()

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
