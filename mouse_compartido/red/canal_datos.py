"""Canal de datos: la segunda conexión entre las PCs, para portapapeles, archivos y carpeta.

¿Por qué una conexión aparte? TCP entrega todo en orden: si por la conexión del
mouse viajara una imagen de 5 MB, cada movimiento tendría que esperar a que
termine de pasar. Por una conexión separada, el mouse no se entera.

¿Quién la usa? La interfaz, no el motor:
  1. El motor la abre (o la acepta) y hace el saludo igual que con la del mouse.
  2. Se la pasa a la interfaz con socket.share() (Windows permite pasar una
     conexión abierta de un proceso a otro), junto con las claves de cifrado.
  3. La interfaz la usa con esta clase. Así, copiar un archivo grande ocupa al
     proceso de la ventana y jamás al del mouse.

Formato de cada mensaje (a diferencia del canal del mouse, acá un mensaje puede
medir megas, por eso el largo ocupa 4 bytes):

    [largo: 4 bytes][tipo + cuerpo, cifrados][sello de 16 bytes]

Hay dos colas para mandar: una para mensajes chicos (portapapeles, avisos) y otra
para los pedazos de archivos. La de mensajes chicos tiene prioridad, así un
archivo de 2 GB no demora que pase lo que copiaste.
"""

import collections
import socket
import struct
import threading

from ..sistema.cripto import Cifrador, ErrorCripto

CABECERA = struct.Struct("<IB")  # Sin cifrar (solo en pruebas): largo del cuerpo, tipo.
_LARGO = struct.Struct("<I")  # Cifrado: largo de lo que sigue.
LARGO_MAXIMO = 64 * 1024 * 1024  # Un mensaje más grande que esto es un error.
_MAXIMO_EN_COLA = 8  # Pedazos de archivo esperando salir (8 de 256 KB = 2 MB).


class CanalDatos:
    """Manda y recibe mensajes por el canal de datos, cada cosa en su propio hilo.

    `al_recibir(tipo, cuerpo)` y `al_cerrar()` se llaman desde esos hilos: en la
    interfaz hay que pasarlos al hilo de la ventana (con una señal de Qt).
    `al_cerrar` avisa solo los cortes; cerrar() a propósito no lo llama.
    `claves` = (clave para mandar, clave para recibir); None solo en pruebas.
    """

    def __init__(self, sock, al_recibir, al_cerrar=None, claves=None):
        sock.setblocking(True)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # Buffer grande: acá importa pasar megas rápido, no la demora de cada byte.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
        except OSError:
            pass
        self._sock = sock
        self._al_recibir = al_recibir
        self._al_cerrar = al_cerrar
        self._cifrar = self._descifrar = None
        if claves is not None:
            self._cifrar = Cifrador(claves[0]).cifrar
            self._descifrar = Cifrador(claves[1]).descifrar
        self._urgentes = collections.deque()
        self._bloques = collections.deque()
        self._hay_algo = threading.Condition()
        self._cerrado = False
        threading.Thread(target=self._leer, name="datos-lector", daemon=True).start()
        threading.Thread(target=self._escribir, name="datos-escritor", daemon=True).start()

    @property
    def cerrado(self):
        return self._cerrado

    def enviar(self, tipo, cuerpo=b""):
        """Encola un mensaje y vuelve enseguida. Devuelve False si el canal ya se cerró."""
        if len(cuerpo) > LARGO_MAXIMO:
            raise ValueError("Mensaje demasiado grande para el canal de datos")
        with self._hay_algo:
            if self._cerrado:
                return False
            self._urgentes.append((tipo, bytes(cuerpo)))
            self._hay_algo.notify_all()
        return True

    def enviar_bloque(self, tipo, cuerpo, timeout=None):
        """Para pedazos de archivos: espera si ya hay muchos en cola (no se llena la memoria).

        Devuelve False si el canal se cerró (o si pasó `timeout` sin lugar).
        """
        with self._hay_algo:
            if not self._hay_algo.wait_for(
                lambda: self._cerrado or len(self._bloques) < _MAXIMO_EN_COLA, timeout
            ) or self._cerrado:
                return False
            self._bloques.append((tipo, bytes(cuerpo)))
            self._hay_algo.notify_all()
        return True

    def cerrar(self):
        self._terminar(avisar=False)

    # ---- Internos -----------------------------------------------------------------
    def _terminar(self, avisar=True):
        with self._hay_algo:
            if self._cerrado:
                return
            self._cerrado = True
            self._hay_algo.notify_all()  # Despierta al que escribe y a los que esperan lugar.
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass
        if avisar and self._al_cerrar is not None:
            self._al_cerrar()

    def _recibir_exacto(self, cantidad):
        datos = bytearray(cantidad)
        vista = memoryview(datos)
        recibidos = 0
        while recibidos < cantidad:
            n = self._sock.recv_into(vista[recibidos:])
            if n == 0:
                raise ConnectionError("El otro lado cerró el canal de datos")
            recibidos += n
        return bytes(datos)

    def _leer(self):
        try:
            while True:
                if self._descifrar is None:
                    largo, tipo = CABECERA.unpack(self._recibir_exacto(CABECERA.size))
                    if largo > LARGO_MAXIMO:
                        raise ConnectionError("Llegó un mensaje demasiado grande")
                    cuerpo = self._recibir_exacto(largo) if largo else b""
                else:
                    largo = _LARGO.unpack(self._recibir_exacto(_LARGO.size))[0]
                    if not 17 <= largo <= LARGO_MAXIMO + 17:
                        raise ConnectionError("Llegó un mensaje de tamaño imposible")
                    plano = self._descifrar(self._recibir_exacto(largo))
                    tipo, cuerpo = plano[0], plano[1:]
                self._al_recibir(tipo, cuerpo)
        except (OSError, ValueError, ErrorCripto):  # ConnectionError es un tipo de OSError.
            pass
        self._terminar()

    def _proximo(self):
        with self._hay_algo:
            self._hay_algo.wait_for(lambda: self._cerrado or self._urgentes or self._bloques)
            if self._cerrado:
                return None
            if self._urgentes:
                return self._urgentes.popleft()
            mensaje = self._bloques.popleft()
            self._hay_algo.notify_all()  # Hay lugar para otro pedazo.
            return mensaje

    def _escribir(self):
        try:
            while True:
                mensaje = self._proximo()
                if mensaje is None:
                    return
                tipo, cuerpo = mensaje
                if self._cifrar is None:
                    self._sock.sendall(CABECERA.pack(len(cuerpo), tipo))
                    if cuerpo:
                        self._sock.sendall(cuerpo)
                else:
                    cifrado = self._cifrar(bytes([tipo]) + cuerpo)
                    self._sock.sendall(_LARGO.pack(len(cifrado)) + cifrado)
        except (OSError, ErrorCripto):
            self._terminar()
