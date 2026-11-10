"""La PC que tiene el mouse y el teclado físicos: espera al cliente y atiende la red."""

import socket
import threading
import time

from ..comun.pantallas import lado_opuesto
from ..comun.registro import es_consola, log
from ..entrada.captura import HiloCaptura
from ..funciones import crear_funciones
from ..red import protocolo as P
from ..red.conexion import Conexion, ConexionCerrada, Sesion, ips_locales
from ..red.seguridad import FalloAutenticacion, autenticar_como_servidor, derivar_clave
from . import estado as E

# Un ping chiquito 5 veces por segundo: alcanza para notar los tirones de la red
# (un ping cada medio segundo se perdía la mayoría) y no carga nada.
_INTERVALO_PING_S = 0.2
_TIEMPO_SIN_RESPUESTA_S = 2.0  # Sin noticias del cliente en este tiempo, se corta.
_ESPERA_TRAS_FALLO_S = 2.0  # Frena a quien intente adivinar el PIN.
_INTERVALO_PANTALLAS_S = 2.0
_INTERVALO_LATENCIA_S = 2.0
_ESPERA_ENTRE_AVISOS_S = 15.0  # Para no llenar la actividad con el mismo aviso.
_VENTANA_PICO_S = 30.0  # La ventana muestra el peor valor de los últimos 30 segundos.


class _MedidorLatencia:
    """Junta las mediciones de ida y vuelta, las informa cada tanto y avisa de los tirones."""

    def __init__(self, informante, mostrar_en_consola, reloj=time.perf_counter):
        self.informante = informante
        self.mostrar_en_consola = mostrar_en_consola
        self.muestras = []
        self.picos = []  # (momento, peor valor de cada informe)
        self.t_informe = reloj()
        self.t_consola = self.t_informe
        self.t_aviso = float("-inf")

    def agregar(self, milisegundos, ahora):
        self.muestras.append(milisegundos)
        if milisegundos >= E.DEMORA_ALTA_MS and ahora - self.t_aviso >= _ESPERA_ENTRE_AVISOS_S:
            self.t_aviso = ahora
            log(f"Ojo: la red tardó {milisegundos:.0f} ms en ir y volver (lo normal es menos "
                "de 10 ms). Si el mouse se trabó recién, fue la red o el Wi-Fi.")

    def informar(self, ahora):
        if ahora - self.t_informe < _INTERVALO_LATENCIA_S or not self.muestras:
            return
        promedio = sum(self.muestras) / len(self.muestras)
        self.picos = [(t, v) for t, v in self.picos if ahora - t < _VENTANA_PICO_S]
        self.picos.append((ahora, max(self.muestras)))
        self.informante.actualizar(
            latencia_ms=round(promedio, 1),
            latencia_pico_ms=round(max(v for _, v in self.picos), 1),
        )
        if self.mostrar_en_consola and ahora - self.t_consola >= 10.0:
            log(
                f"Latencia de red ida y vuelta: promedio {promedio:.1f} ms, "
                f"mínimo {min(self.muestras):.1f} ms, máximo {max(self.muestras):.1f} ms"
            )
            self.t_consola = ahora
        self.muestras.clear()
        self.t_informe = ahora


class Servidor:
    def __init__(self, config, captura=None, informante=None):
        self.config = config
        self.informante = informante or E.Informante(rol="servidor")
        self.captura = (
            captura if captura is not None else HiloCaptura(config, informante=self.informante)
        )
        self._parar = threading.Event()
        self.escuchando = threading.Event()
        self._conexion = None
        self._pausa_local = False

    def detener(self):
        self._parar.set()

    def pausar(self, activa):
        """Pausa o reanuda el paso a la otra PC sin cortar la conexión."""
        self._pausa_local = bool(activa)
        self.captura.pausar(local=self._pausa_local)
        conexion = self._conexion
        if conexion is not None:
            conexion.enviar(P.pausa(self._pausa_local))
        self.informante.actualizar(pausa_local=self._pausa_local)
        log("Pausado: el mouse se queda en esta PC." if activa else "Reanudado.")

    def correr(self):
        clave = derivar_clave(self.config.pin)
        self.informante.actualizar(lado=self.config.lado_otra_pantalla)
        self.captura.iniciar()
        oyente = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Impide que otro programa escuche en el mismo puerto.
            oyente.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            oyente.bind(("0.0.0.0", self.config.puerto))
            oyente.listen(1)
            oyente.settimeout(0.25)
            self.escuchando.set()
            ips = ips_locales()
            log(f"Servidor esperando en el puerto {self.config.puerto}. "
                f"IP de esta PC: {', '.join(ips) or 'desconocida'}")
            if es_consola():
                log("Ctrl+C en esta ventana para cerrar.")
            self._esperando(ips)
            while not self._parar.is_set():
                try:
                    sock, direccion = oyente.accept()
                except socket.timeout:
                    continue
                self._atender(sock, direccion, clave)
        finally:
            oyente.close()
            self.captura.detener()

    def _esperando(self, ips=None):
        cambios = dict(
            estado=E.ESPERANDO,
            detalle=f"Esperando a la otra PC (puerto {self.config.puerto})",
            otra_pc=None, mouse_aca=True, pausa_otra=False, latencia_ms=None,
            latencia_pico_ms=None,
        )
        if ips is not None:
            cambios["ips"] = ips
        self.informante.actualizar(**cambios)

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

        log(f"Cliente conectado desde {ip}. Llevá el cursor al borde de "
            f"{_frase_lado(self.config.lado_otra_pantalla)} para pasar.")
        # Presentación: nombre y monitores, para que la interfaz los muestre.
        conexion.enviar(P.info(self.informante.datos["nombre_pc"],
                               self.captura.logica.pantallas.como_lista()))
        if self._pausa_local:
            conexion.enviar(P.pausa(True))
        self._conexion = conexion
        self.informante.actualizar(
            estado=E.CONECTADO, detalle=f"Conectado con {ip}",
            otra_pc={"nombre": "", "ip": ip, "monitores": []},
        )
        sesion = Sesion(conexion)
        funciones = crear_funciones(self.config)
        for funcion in funciones:
            funcion.al_conectar(sesion)
        self.captura.conectar(conexion)
        try:
            self._sesion(conexion, sesion, ip)
        finally:
            self._conexion = None
            for funcion in funciones:
                funcion.al_desconectar()
            self.captura.desconectar()
            conexion.cerrar()
            log("Cliente desconectado. Esperando que se vuelva a conectar...")
            if not self._parar.is_set():
                self._esperando()

    def _sesion(self, conexion, sesion, ip):
        medidor = _MedidorLatencia(self.informante, self.config.mostrar_latencia and es_consola())
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
                    medidor.agregar((time.perf_counter_ns() - enviado) / 1e6, ahora)
                elif tipo == P.Tipo.PAUSA:
                    activa = cuerpo[:1] == b"\x01"
                    self.captura.pausar(remota=activa)
                    self.informante.actualizar(pausa_otra=activa)
                    log("La otra PC pausó el paso del mouse." if activa
                        else "La otra PC reanudó.")
                elif tipo == P.Tipo.INFO:
                    datos = P.leer_info(cuerpo)
                    if datos is not None:
                        nombre, monitores = datos
                        self.informante.actualizar(
                            otra_pc={"nombre": nombre, "ip": ip, "monitores": monitores},
                            detalle=f"Conectado con {nombre or ip}",
                        )
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


def _frase_lado(lado):
    """'la derecha', 'arriba'... para armar mensajes que se lean bien."""
    return {"izquierda": "la izquierda", "derecha": "la derecha"}.get(lado, lado)
