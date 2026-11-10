"""La PC sin mouse ni teclado propios en uso: recibe los eventos y los ejecuta.

Recibir y ejecutar ocurren en un solo hilo: el camino desde que llega el paquete
hasta que se mueve el cursor no espera a ningún otro hilo.
"""

import socket
import threading
import time

from . import protocolo as P
from .conexion import Conexion, ConexionCerrada, Sesion
from .funciones import crear_funciones
from .inyeccion import SalidaWindows
from .logica_cliente import LogicaCliente
from .registro import log
from .seguridad import FalloAutenticacion, autenticar_como_cliente, derivar_clave

_TIEMPO_SIN_DATOS_S = 3.0  # El servidor manda un ping cada medio segundo.
_ESPERA_REINTENTO_S = 2.0

_MOVER = P.Tipo.MOVER
_BOTON = P.Tipo.BOTON
_RUEDA = P.Tipo.RUEDA
_TECLA = P.Tipo.TECLA
_PING = P.Tipo.PING
_ENTRAR = P.Tipo.ENTRAR
_SALIR = P.Tipo.SALIR
_mover = P.S_MOVER.unpack
_boton = P.S_BOTON.unpack
_rueda = P.S_RUEDA.unpack
_tecla = P.S_TECLA.unpack
_ratio = P.S_RATIO.unpack
_tiempo = P.S_TIEMPO.unpack


class Cliente:
    def __init__(self, config, salida=None):
        self.config = config
        self.salida = salida if salida is not None else SalidaWindows()
        self._parar = threading.Event()
        self.logica = None  # La sesión actual (visible para las pruebas).

    def detener(self):
        self._parar.set()

    def correr(self):
        """Se conecta y reconecta sola hasta que se cierre el programa."""
        clave = derivar_clave(self.config.pin)
        destino = (self.config.ip_servidor, self.config.puerto)
        ultimo_error = None
        log(f"Conectando con el servidor {destino[0]}:{destino[1]} ...")
        while not self._parar.is_set():
            try:
                sock = socket.create_connection(destino, timeout=3)
            except OSError as error:
                if str(error) != ultimo_error:
                    ultimo_error = str(error)
                    log(f"Todavía no puedo conectar ({error}). Sigo intentando...")
                self._parar.wait(_ESPERA_REINTENTO_S)
                continue

            ultimo_error = None
            conexion = Conexion(sock)
            try:
                lado_retorno = autenticar_como_cliente(conexion, clave)
            except FalloAutenticacion as error:
                # Reintentar con la misma clave no tiene sentido.
                log(f"El servidor no aceptó la conexión: {error}")
                conexion.cerrar()
                return
            except (ConexionCerrada, TimeoutError) as error:
                log(f"Falló el saludo: {error}")
                conexion.cerrar()
                self._parar.wait(_ESPERA_REINTENTO_S)
                continue

            log(f"Conectado. El cursor vuelve por el borde de la {lado_retorno}.")
            self._sesion(conexion, lado_retorno)
            conexion.cerrar()
            log("Se cortó la conexión. Reintentando...")
            self._parar.wait(_ESPERA_REINTENTO_S)

    def _sesion(self, conexion, lado_retorno):
        logica = LogicaCliente(
            self.salida, lado_retorno, conexion.enviar, self.config.enfriamiento_ms / 1000.0
        )
        self.logica = logica
        sesion = Sesion(conexion)
        funciones = crear_funciones(self.config)
        for funcion in funciones:
            funcion.al_conectar(sesion)

        ultimo_dato = time.perf_counter()
        try:
            while not self._parar.is_set():
                try:
                    marcos = conexion.recibir(0.25)
                except ConexionCerrada:
                    return
                if marcos:
                    ultimo_dato = time.perf_counter()
                elif time.perf_counter() - ultimo_dato > _TIEMPO_SIN_DATOS_S:
                    log("El servidor dejó de responder.")
                    return

                for tipo, cuerpo in marcos:
                    if tipo == _MOVER:
                        dx, dy = _mover(cuerpo)
                        logica.mover(dx, dy)
                    elif tipo == _TECLA:
                        vk, escaneo, banderas = _tecla(cuerpo)
                        logica.tecla(vk, escaneo, banderas)
                    elif tipo == _BOTON:
                        codigo, apretado = _boton(cuerpo)
                        logica.boton(codigo, bool(apretado))
                    elif tipo == _RUEDA:
                        delta, horizontal = _rueda(cuerpo)
                        logica.rueda(delta, bool(horizontal))
                    elif tipo == _PING:
                        conexion.enviar(P.pong(_tiempo(cuerpo)[0]))
                    elif tipo == _ENTRAR:
                        logica.entrar(_ratio(cuerpo)[0])
                        log("-> El cursor llegó a esta PC.")
                    elif tipo == _SALIR:
                        logica.salir()
                        log("<- El servidor recuperó el control.")
                    else:
                        sesion.despachar(tipo, cuerpo)
        finally:
            # Pase lo que pase, que no quede ninguna tecla apretada.
            logica.soltar_todo()
            for funcion in funciones:
                funcion.al_desconectar()
