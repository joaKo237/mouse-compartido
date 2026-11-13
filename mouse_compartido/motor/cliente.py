"""La PC sin mouse ni teclado propios en uso: recibe los eventos y los ejecuta.

Recibir y ejecutar ocurren en un solo hilo: el camino desde que llega el paquete
hasta que se mueve el cursor no espera a ningún otro hilo.

¿Cómo sabe dónde está la otra PC? La interfaz la encuentra en la red (ver
red/descubrimiento.py) y le pasa las direcciones con poner_destinos(), la del
cable primero. También prueba la última IP donde la encontró y, si la pusiste,
la IP fija de la página Conexión.
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
from ..red.seguridad import (
    CanalNoDisponible,
    Emparejamiento,
    FalloAutenticacion,
    NoEmparejada,
    autenticar_como_cliente,
)
from . import estado as E

_TIEMPO_SIN_DATOS_S = 3.0  # El servidor manda un ping cada 0,2 segundos.
_ESPERA_REINTENTO_S = 2.0
_ESPERA_NO_EMPAREJADA_S = 10.0  # Si la otra PC no nos reconoce, se insiste más despacio.
_ESPERA_CONECTAR_S = 1.5  # Por dirección: en la red local, conectar tarda milisegundos.
# Si aparece un camino mejor (el cable) mientras se usa otro (Wi-Fi), se cambia,
# pero solo cuando el cursor no está en esta PC (así no se nota).
_INTERVALO_MEJOR_RUTA_S = 3.0
# Aplicar un mensaje tarda centésimas de milisegundo. Si tarda más de 2 ms cada uno
# (y en total se nota), el atraso es de esta PC y no de la red.
_LENTO_POR_MENSAJE_S = 0.002
_LENTO_TOTAL_S = 0.05
_ESPERA_ENTRE_AVISOS_S = 15.0
_INTERVALO_PANTALLAS_S = 1.0  # Cada cuánto se fija si cambió la resolución (por un juego).
_INTENTOS_CANAL_DATOS = 3
_PRIORIDAD_SIN_VER = 9  # Direcciones que no salen de la red (la última, la fija).

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
    def __init__(self, config, salida=None, informante=None, entregar_canal=None):
        """`entregar_canal(sock, claves)` recibe el canal de datos ya verificado, con sus
        claves de cifrado (None = no se usa)."""
        self.config = config
        self._entregar_canal = entregar_canal
        self.salida = salida if salida is not None else SalidaWindows()
        self.informante = informante or E.Informante(rol="cliente")
        self._parar = threading.Event()
        self.logica = None  # La sesión actual (visible para las pruebas).
        self._conexion = None
        self._pausa_local = False
        self.error = None  # Motivo por el que se rindió.
        self._emparejamiento = None
        self._destino = None
        self._abriendo_canal = threading.Lock()
        # Dónde buscar a la otra PC: [(ip, prioridad)], la mejor primero (0 = cable).
        self._destinos = []
        self._candado_destinos = threading.Lock()
        self._hay_destinos = threading.Event()
        self._prioridad_actual = None

    def detener(self):
        self._parar.set()
        self._hay_destinos.set()

    def pausar(self, activa):
        """Pide a la PC principal que no pase el mouse hacia acá (sin cortar la conexión)."""
        self._pausa_local = bool(activa)
        conexion = self._conexion
        if conexion is not None:
            conexion.enviar(P.pausa(self._pausa_local))
        self.informante.actualizar(pausa_local=self._pausa_local)
        log("Pausado: el mouse no va a pasar a esta PC." if activa else "Reanudado.")

    # ---- Dónde está la otra PC -----------------------------------------------------------
    def poner_destinos(self, destinos):
        """Recibe las direcciones donde se vio a la otra PC: [(ip, prioridad)], 0 = cable."""
        limpios = []
        for destino in destinos:
            try:
                ip, prioridad = str(destino[0]), int(destino[1])
            except (TypeError, ValueError, IndexError):
                continue
            if ip and all(ip != otro for otro, _ in limpios):
                limpios.append((ip, prioridad))
        limpios.sort(key=lambda d: d[1])
        with self._candado_destinos:
            self._destinos = limpios
        if limpios:
            self._hay_destinos.set()

    def _candidatos(self):
        """Direcciones a probar, en orden: las vistas en la red, la última y la fija."""
        with self._candado_destinos:
            candidatos = list(self._destinos)
        for ip in (self.config.ultima_ip_otra_pc, self.config.ip_servidor):
            if ip and all(ip != otro for otro, _ in candidatos):
                candidatos.append((ip, _PRIORIDAD_SIN_VER))
        return candidatos

    def _mejor_prioridad_vista(self):
        with self._candado_destinos:
            return self._destinos[0][1] if self._destinos else None

    # ---- Bucle principal -----------------------------------------------------------------
    def correr(self):
        """Se conecta y reconecta sola hasta que se cierre el programa."""
        try:
            self._correr()
        finally:
            self.salida.cerrar()

    def _correr(self):
        self._emparejamiento = Emparejamiento.desde_config(self.config)
        nombre = self.config.emparejado_nombre or "la otra PC"
        log(f"Buscando a {nombre} en la red...")
        self.informante.actualizar(ips=ips_locales())
        ultimo_error = None
        while not self._parar.is_set():
            self.informante.actualizar(
                estado=E.CONECTANDO, detalle=f"Buscando a {nombre} en la red",
                otra_pc=None, mouse_aca=False, pausa_otra=False,
            )
            candidatos = self._candidatos()
            if not candidatos:
                # Todavía no se la vio: se espera a que la interfaz avise que apareció.
                self._hay_destinos.wait(0.5)
                self._hay_destinos.clear()
                continue
            espera = _ESPERA_REINTENTO_S
            for ip, prioridad in candidatos:
                if self._parar.is_set():
                    return
                resultado = self._probar(ip, prioridad)
                if resultado == "sesion":
                    ultimo_error = None
                    espera = 0.3  # Se cortó una sesión: se reintenta enseguida.
                    break
                if isinstance(resultado, NoEmparejada):
                    espera = _ESPERA_NO_EMPAREJADA_S
                    if str(resultado) != ultimo_error:
                        ultimo_error = str(resultado)
                        log(f"La otra PC respondió pero no aceptó la conexión: {resultado}")
                    self.informante.actualizar(estado=E.CONECTANDO, detalle=str(resultado))
                    break
                if isinstance(resultado, FalloAutenticacion):
                    # Versión distinta, por ejemplo: reintentar no lo arregla.
                    log(f"El servidor no aceptó la conexión: {resultado}")
                    self.error = str(resultado)
                    self.informante.actualizar(estado=E.ERROR, detalle=str(resultado))
                    return
            else:
                motivo = "no responde en " + ", ".join(ip for ip, _ in candidatos)
                if motivo != ultimo_error:
                    ultimo_error = motivo
                    log(f"Todavía no puedo conectar ({motivo}). Sigo intentando...")
            self._parar.wait(espera)

    def _probar(self, ip, prioridad):
        """Intenta conectar con esa dirección. Devuelve "sesion", None o la excepción."""
        destino = (ip, self.config.puerto)
        try:
            sock = socket.create_connection(destino, timeout=_ESPERA_CONECTAR_S)
        except OSError:
            return None
        conexion = Conexion(sock)
        try:
            claves = autenticar_como_cliente(conexion, self._emparejamiento)
            conexion.activar_cifrado(claves.envio, claves.recepcion)
        except FalloAutenticacion as error:
            conexion.cerrar()
            return error
        except (ConexionCerrada, TimeoutError, OSError) as error:
            log(f"Falló el saludo con {ip}: {error}")
            conexion.cerrar()
            return None
        self._destino = destino
        self._prioridad_actual = prioridad
        log(f"Conectado con {ip} (conexión cifrada). El cursor vuelve por el borde de "
            f"{_frase(claves.lado)}.")
        self._sesion(conexion, claves.lado, ip)
        conexion.cerrar()
        if not self._parar.is_set():
            log("Se cortó la conexión. Reintentando...")
        return "sesion"

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
        self.pedir_canal_datos()
        informante = self.informante

        ultimo_dato = time.perf_counter()
        proxima_lectura_pantallas = ultimo_dato + _INTERVALO_PANTALLAS_S
        proxima_revision_ruta = ultimo_dato + _INTERVALO_MEJOR_RUTA_S
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
                if inicio >= proxima_revision_ruta:
                    proxima_revision_ruta = inicio + _INTERVALO_MEJOR_RUTA_S
                    if self._conviene_cambiar_de_ruta(logica):
                        log("Apareció un camino mejor hasta la otra PC (el cable): me paso a ese.")
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

    def _conviene_cambiar_de_ruta(self, logica):
        """¿Apareció un camino mejor (cable) y el cursor no está acá? Entonces se reconecta."""
        mejor = self._mejor_prioridad_vista()
        actual = self._prioridad_actual
        return (mejor is not None and actual is not None and mejor < actual
                and not logica.activo)

    # ---- Canal de datos (portapapeles, archivos y carpeta) ------------------------------
    def pedir_canal_datos(self):
        """Abre el canal de datos en otro hilo (al conectar, o si la interfaz lo pide)."""
        conexion = self._conexion
        if self._entregar_canal is None or conexion is None:
            return
        if not self._abriendo_canal.acquire(blocking=False):
            return  # Ya se está abriendo.
        threading.Thread(
            target=self._abrir_canal_datos, args=(conexion,), name="canal-datos", daemon=True
        ).start()

    def _abrir_canal_datos(self, conexion_mouse):
        """Se conecta al mismo puerto pidiendo el canal de datos y se lo pasa a la interfaz."""
        try:
            for intento in range(_INTENTOS_CANAL_DATOS):
                if intento:
                    self._parar.wait(_ESPERA_REINTENTO_S)
                if self._parar.is_set() or self._conexion is not conexion_mouse:
                    return  # La sesión del mouse terminó: ya no hace falta.
                try:
                    sock = socket.create_connection(self._destino, timeout=3)
                except OSError:
                    continue
                conexion = Conexion(sock)
                try:
                    claves = autenticar_como_cliente(
                        conexion, self._emparejamiento, canal=P.CANAL_DATOS)
                    if self._conexion is not conexion_mouse:
                        conexion.cerrar()
                        return
                    self._entregar_canal(conexion.entregar_socket(), claves)
                    return
                except CanalNoDisponible as error:
                    # La otra PC contestó que no conoce este canal: reintentar no sirve.
                    conexion.cerrar()
                    log(f"Portapapeles y archivos: {error}.")
                    return
                except (FalloAutenticacion, ConexionCerrada, TimeoutError, OSError):
                    conexion.cerrar()
            log("No se pudo abrir el canal del portapapeles y los archivos. "
                "Se vuelve a probar al reconectar.")
        finally:
            self._abriendo_canal.release()


def _frase(lado):
    return {"izquierda": "la izquierda", "derecha": "la derecha"}.get(lado, lado)
