"""La PC sin mouse ni teclado propios en uso: recibe los eventos y los ejecuta.

Recibir y ejecutar ocurren en un solo hilo: el camino desde que llega el paquete
hasta que se mueve el cursor no espera a ningún otro hilo.
"""

import socket
import threading
import time

from ..comun.registro import log
from ..entrada.inyeccion import SalidaWindows
from ..entrada.logica_cliente import LogicaCliente
from ..funciones import crear_funciones
from ..red import protocolo as P
from ..red.conexion import Conexion, ConexionCerrada, Sesion, ips_locales
from ..red.seguridad import FalloAutenticacion, autenticar_como_cliente, derivar_clave
from . import estado as E

_TIEMPO_SIN_DATOS_S = 3.0  # El servidor manda un ping cada 0,2 segundos.
_ESPERA_REINTENTO_S = 2.0
# Aplicar un mensaje tarda centésimas de milisegundo. Si tarda más de 2 ms cada uno
# (y en total se nota), el atraso es de esta PC y no de la red.
_LENTO_POR_MENSAJE_S = 0.002
_LENTO_TOTAL_S = 0.05
_ESPERA_ENTRE_AVISOS_S = 15.0
_INTERVALO_PANTALLAS_S = 1.0  # Cada cuánto se fija si cambió la resolución (por un juego).

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
    def __init__(self, config, salida=None, informante=None):
        self.config = config
        self.salida = salida if salida is not None else SalidaWindows()
        self.informante = informante or E.Informante(rol="cliente")
        self._parar = threading.Event()
        self.logica = None  # La sesión actual (visible para las pruebas).
        self._conexion = None
        self._pausa_local = False
        self.error = None  # Motivo por el que se rindió (PIN incorrecto, etc.).

    def detener(self):
        self._parar.set()

    def pausar(self, activa):
        """Pide a la PC principal que no pase el mouse hacia acá (sin cortar la conexión)."""
        self._pausa_local = bool(activa)
        conexion = self._conexion
        if conexion is not None:
            conexion.enviar(P.pausa(self._pausa_local))
        self.informante.actualizar(pausa_local=self._pausa_local)
        log("Pausado: el mouse no va a pasar a esta PC." if activa else "Reanudado.")

    def correr(self):
        """Se conecta y reconecta sola hasta que se cierre el programa."""
        try:
            self._correr()
        finally:
            self.salida.cerrar()

    def _correr(self):
        clave = derivar_clave(self.config.pin)
        destino = (self.config.ip_servidor, self.config.puerto)
        ultimo_error = None
        log(f"Conectando con el servidor {destino[0]}:{destino[1]} ...")
        self.informante.actualizar(ips=ips_locales())
        while not self._parar.is_set():
            self.informante.actualizar(
                estado=E.CONECTANDO, detalle=f"Buscando a la otra PC en {destino[0]}",
                otra_pc=None, mouse_aca=False, pausa_otra=False,
            )
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
                self.error = str(error)
                self.informante.actualizar(estado=E.ERROR, detalle=str(error))
                conexion.cerrar()
                return
            except (ConexionCerrada, TimeoutError) as error:
                log(f"Falló el saludo: {error}")
                conexion.cerrar()
                self._parar.wait(_ESPERA_REINTENTO_S)
                continue

            log(f"Conectado. El cursor vuelve por el borde de {_frase(lado_retorno)}.")
            self._sesion(conexion, lado_retorno, destino[0])
            conexion.cerrar()
            if not self._parar.is_set():
                log("Se cortó la conexión. Reintentando...")
                self._parar.wait(_ESPERA_REINTENTO_S)

    def _sesion(self, conexion, lado_retorno, ip):
        logica = LogicaCliente(
            self.salida, lado_retorno, conexion.enviar, self.config.enfriamiento_ms / 1000.0
        )
        self.logica = logica
        sesion = Sesion(conexion)
        funciones = crear_funciones(self.config)
        for funcion in funciones:
            funcion.al_conectar(sesion)
        conexion.enviar(P.info(self.informante.datos["nombre_pc"], logica.pantallas.como_lista()))
        if self._pausa_local:
            conexion.enviar(P.pausa(True))
        self._conexion = conexion
        # La PC principal está del lado por donde vuelve el cursor.
        self.informante.actualizar(
            estado=E.CONECTADO, detalle=f"Conectado con {ip}", lado=lado_retorno,
            otra_pc={"nombre": "", "ip": ip, "monitores": []}, mouse_aca=False,
        )
        informante = self.informante

        ultimo_dato = time.perf_counter()
        proxima_lectura_pantallas = ultimo_dato + _INTERVALO_PANTALLAS_S
        t_aviso_lento = float("-inf")
        try:
            while not self._parar.is_set():
                try:
                    marcos = conexion.recibir(0.25)
                except ConexionCerrada:
                    return
                inicio = time.perf_counter()
                if marcos:
                    ultimo_dato = inicio
                elif inicio - ultimo_dato > _TIEMPO_SIN_DATOS_S:
                    log("El servidor dejó de responder.")
                    return
                if inicio >= proxima_lectura_pantallas:
                    proxima_lectura_pantallas = inicio + _INTERVALO_PANTALLAS_S
                    if logica.actualizar_pantallas():
                        p = logica.pantallas
                        log(f"La pantalla de esta PC cambió a {p.ancho}x{p.alto} "
                            "(un juego, por ejemplo). Ya está tenida en cuenta.")

                for tipo, cuerpo in marcos:
                    if tipo == _MOVER:
                        dx, dy = _mover(cuerpo)
                        logica.mover(dx, dy)
                        if not logica.activo:
                            # Acaba de volver por el borde.
                            informante.actualizar(mouse_aca=False)
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
                        informante.actualizar(mouse_aca=True)
                        log("-> El cursor llegó a esta PC.")
                    elif tipo == _SALIR:
                        logica.salir()
                        informante.actualizar(mouse_aca=False)
                        log("<- El servidor recuperó el control.")
                    elif tipo == P.Tipo.PAUSA:
                        activa = cuerpo[:1] == b"\x01"
                        informante.actualizar(pausa_otra=activa)
                        log("La otra PC pausó el paso del mouse." if activa
                            else "La otra PC reanudó.")
                    elif tipo == P.Tipo.INFO:
                        datos = P.leer_info(cuerpo)
                        if datos is not None:
                            nombre, monitores = datos
                            informante.actualizar(
                                otra_pc={"nombre": nombre, "ip": ip, "monitores": monitores},
                                detalle=f"Conectado con {nombre or ip}",
                            )
                    else:
                        sesion.despachar(tipo, cuerpo)

                if marcos and inicio - t_aviso_lento >= _ESPERA_ENTRE_AVISOS_S:
                    duracion = time.perf_counter() - inicio
                    if (duracion > _LENTO_TOTAL_S
                            and duracion / len(marcos) > _LENTO_POR_MENSAJE_S):
                        t_aviso_lento = inicio
                        log(f"Ojo: esta PC tardó {duracion * 1000:.0f} ms en mover el cursor. "
                            "Algún programa la tiene muy ocupada o frena el mouse.")
        finally:
            self._conexion = None
            # Pase lo que pase, que no quede ninguna tecla apretada ni el cursor escondido.
            logica.terminar()
            for funcion in funciones:
                funcion.al_desconectar()


def _frase(lado):
    return {"izquierda": "la izquierda", "derecha": "la derecha"}.get(lado, lado)
