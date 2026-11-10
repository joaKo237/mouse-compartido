"""La PC que tiene el mouse y el teclado físicos: espera al cliente y atiende la red."""

import socket
import threading
import time

from . import protocolo as P
from .captura import HiloCaptura
from .conexion import Conexion, ConexionCerrada, Sesion, ips_locales
from .funciones import crear_funciones
from .pantallas import lado_opuesto
from .registro import log
from .seguridad import FalloAutenticacion, autenticar_como_servidor, derivar_clave

_INTERVALO_PING_S = 0.5
_TIEMPO_SIN_RESPUESTA_S = 2.0  # Sin noticias del cliente en este tiempo, se corta.
_ESPERA_TRAS_FALLO_S = 2.0  # Frena a quien intente adivinar el PIN.
_INTERVALO_PANTALLAS_S = 2.0


class _MedidorLatencia:
    """Junta las mediciones de ida y vuelta y las informa cada 10 segundos."""

    def __init__(self, activo):
        self.activo = activo
        self.muestras = []
        self.t_informe = time.perf_counter()

    def agregar(self, milisegundos):
        self.muestras.append(milisegundos)

    def informar(self, ahora):
        if not self.activo or ahora - self.t_informe < 10.0 or not self.muestras:
            return
        promedio = sum(self.muestras) / len(self.muestras)
        log(
            f"Latencia de red ida y vuelta: promedio {promedio:.1f} ms, "
            f"mínimo {min(self.muestras):.1f} ms, máximo {max(self.muestras):.1f} ms"
        )
        self.muestras.clear()
        self.t_informe = ahora


class Servidor:
    def __init__(self, config, captura=None):
        self.config = config
        self.captura = captura if captura is not None else HiloCaptura(config)
        self._parar = threading.Event()
        self.escuchando = threading.Event()

    def detener(self):
        self._parar.set()

    def correr(self):
        clave = derivar_clave(self.config.pin)
        self.captura.iniciar()
        oyente = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Impide que otro programa escuche en el mismo puerto.
            oyente.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            oyente.bind(("0.0.0.0", self.config.puerto))
            oyente.listen(1)
            oyente.settimeout(0.25)
            self.escuchando.set()
            ips = ", ".join(ips_locales()) or "desconocida"
            log(f"Servidor esperando en el puerto {self.config.puerto}. IP de esta PC: {ips}")
            log("Ctrl+C en esta ventana para cerrar.")
            while not self._parar.is_set():
                try:
                    sock, direccion = oyente.accept()
                except socket.timeout:
                    continue
                self._atender(sock, direccion, clave)
        finally:
            oyente.close()
            self.captura.detener()

    def _atender(self, sock, direccion, clave):
        conexion = Conexion(sock)
        ip = direccion[0]
        lado_retorno = lado_opuesto(self.config.lado_otra_pantalla)
        try:
            autenticar_como_servidor(conexion, clave, lado_retorno)
        except FalloAutenticacion as error:
            log(f"Conexión rechazada desde {ip}: {error}")
            conexion.cerrar()
            self._parar.wait(_ESPERA_TRAS_FALLO_S)
            return
        except (ConexionCerrada, TimeoutError) as error:
            log(f"Falló el saludo con {ip}: {error}")
            conexion.cerrar()
            return

        log(f"Cliente conectado desde {ip}. Llevá el cursor al borde de la "
            f"{self.config.lado_otra_pantalla} para pasar.")
        sesion = Sesion(conexion)
        funciones = crear_funciones(self.config)
        for funcion in funciones:
            funcion.al_conectar(sesion)
        self.captura.conectar(conexion)
        try:
            self._sesion(conexion, sesion)
        finally:
            for funcion in funciones:
                funcion.al_desconectar()
            self.captura.desconectar()
            conexion.cerrar()
            log("Cliente desconectado. Esperando que se vuelva a conectar...")

    def _sesion(self, conexion, sesion):
        medidor = _MedidorLatencia(self.config.mostrar_latencia)
        ahora = time.perf_counter()
        ultimo_dato = ahora
        proximo_ping = ahora
        proxima_lectura_pantallas = ahora + _INTERVALO_PANTALLAS_S

        while not self._parar.is_set():
            try:
                marcos = conexion.recibir(0.05)
            except ConexionCerrada:
                return
            ahora = time.perf_counter()
            for tipo, cuerpo in marcos:
                ultimo_dato = ahora
                if tipo == P.Tipo.VOLVER:
                    self.captura.pedir_volver(P.S_RATIO.unpack(cuerpo)[0])
                elif tipo == P.Tipo.PONG:
                    enviado = P.S_TIEMPO.unpack(cuerpo)[0]
                    medidor.agregar((time.perf_counter_ns() - enviado) / 1e6)
                else:
                    sesion.despachar(tipo, cuerpo)

            if ahora >= proximo_ping:
                proximo_ping = ahora + _INTERVALO_PING_S
                conexion.enviar(P.ping(time.perf_counter_ns()))
                medidor.informar(ahora)
            if ahora >= proxima_lectura_pantallas:
                proxima_lectura_pantallas = ahora + _INTERVALO_PANTALLAS_S
                self.captura.actualizar_pantallas()
            if ahora - ultimo_dato > _TIEMPO_SIN_RESPUESTA_S:
                # Sin esto, si se apaga la otra PC quedarías sin mouse varios segundos.
                log("El cliente dejó de responder.")
                return
