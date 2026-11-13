"""Que el programa se abra una sola vez, y hablarle al que ya está abierto.

Si abrís Mouse Compartido dos veces, el segundo le pide al primero que se
muestre y se cierra. Lo mismo hace el clic derecho → Enviar a → Mouse
Compartido: arranca un proceso cortito que le pasa las rutas al programa
abierto y termina.

Se usa un "socket local" de Qt (en Windows, una tubería con nombre).
"""

import getpass
import json

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket

NOMBRE = f"MouseCompartido-{getpass.getuser()}"
MOSTRAR = b"mostrar"
NADA = b"nada"
_ENVIAR = b"enviar\n"


def mensaje_enviar(rutas):
    return _ENVIAR + json.dumps([str(r) for r in rutas]).encode("utf-8")


def leer_mensaje(datos):
    """Devuelve ("mostrar" | "nada" | "enviar", rutas)."""
    datos = bytes(datos)
    if datos.startswith(_ENVIAR):
        try:
            rutas = json.loads(datos[len(_ENVIAR):].decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            rutas = []
        return "enviar", [str(r) for r in rutas if isinstance(r, str)]
    if datos.startswith(MOSTRAR):
        return "mostrar", []
    return "nada", []


_FIN = b"\0"  # Marca el final de un mensaje (no aparece ni en el texto ni en el JSON).
_OK = b"ok"


def mandar(datos, espera_ms=1500):
    """Le manda `datos` al programa abierto. Devuelve False si no hay ninguno abierto.

    Espera el "ok" del otro antes de cortar: si se cortara enseguida, a veces el
    programa abierto no llegaba a leer el mensaje.
    """
    if QCoreApplication.instance() is None:
        _app = QCoreApplication([])  # QLocalSocket necesita una aplicación de Qt creada.
    socket = QLocalSocket()
    socket.connectToServer(NOMBRE)
    if not socket.waitForConnected(espera_ms):
        return False
    socket.write(datos + _FIN)
    socket.waitForBytesWritten(espera_ms)
    socket.waitForReadyRead(espera_ms)  # El "ok" (una versión vieja no lo manda: no importa).
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.UnconnectedState:
        socket.waitForDisconnected(espera_ms)
    return True


def crear_servidor(parent, al_recibir):
    """Empieza a escuchar. `al_recibir(datos)` se llama con cada mensaje completo."""
    servidor = QLocalServer(parent)
    # Sin esto, si el programa corre como Administrador, el "Enviar a" (que corre
    # sin permisos elevados) no tendría permiso para hablarle.
    servidor.setSocketOptions(QLocalServer.UserAccessOption)
    QLocalServer.removeServer(NOMBRE)
    servidor.listen(NOMBRE)

    def al_conectarse():
        conexion = servidor.nextPendingConnection()
        if conexion is None:
            return
        recibido = bytearray()
        listo = []

        def entregar(datos):
            if not listo:
                listo.append(True)
                al_recibir(datos)

        def leer():
            recibido.extend(bytes(conexion.readAll()))
            if _FIN in recibido:
                conexion.write(_OK)
                conexion.flush()
                entregar(bytes(recibido[:recibido.index(_FIN)]))

        def al_cortarse():
            leer()
            if recibido:
                entregar(bytes(recibido))  # Una versión vieja, que no manda el final.
            conexion.deleteLater()

        conexion.readyRead.connect(leer)
        conexion.disconnected.connect(al_cortarse)

    servidor.newConnection.connect(al_conectarse)
    return servidor
