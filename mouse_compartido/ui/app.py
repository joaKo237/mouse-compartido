"""La aplicación con interfaz: une la ventana, la bandeja y el motor.

Flujo general:
    ventana / bandeja  --(órdenes)-->  ControlMotor  --(proceso aparte)-->  motor
    ventana / bandeja  <--(estado)---  ControlMotor  <--(JSON por línea)--  motor
"""

import getpass
import sys
from dataclasses import replace

from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from ..comun import config as modulo_config
from ..comun.config import CLIENTE
from ..sistema import autoinicio
from . import estilo, iconos
from .bandeja import Bandeja
from .control_motor import ControlMotor
from .ventana import VentanaPrincipal

_NOMBRE_INSTANCIA = f"MouseCompartido-{getpass.getuser()}"


def _avisar_a_la_otra_instancia(mostrar):
    """Si el programa ya está abierto, le pide que se muestre. Devuelve True si había otro."""
    socket = QLocalSocket()
    socket.connectToServer(_NOMBRE_INSTANCIA)
    if not socket.waitForConnected(400):
        return False
    socket.write(b"mostrar" if mostrar else b"nada")
    socket.waitForBytesWritten(400)
    socket.disconnectFromServer()
    return True


class Aplicacion(QObject):
    def __init__(self, app, ruta_config, en_bandeja):
        super().__init__()
        self.app = app
        self.ruta = ruta_config
        self._aviso_bandeja_mostrado = False
        try:
            self.config = modulo_config.cargar(ruta_config)
            error_config = ""
        except (ValueError, TypeError) as error:
            self.config = modulo_config.Config()
            error_config = f"config.json tiene un error y se usaron los valores por defecto: {error}"

        # Lo que diga Windows manda: la tarea puede haberse borrado a mano.
        activo = autoinicio.esta_activo()
        if activo != self.config.iniciar_con_windows:
            self.config = replace(self.config, iniciar_con_windows=activo)

        self.motor = ControlMotor(ruta_config, self)
        self.ventana = VentanaPrincipal(self.config)
        self.bandeja = Bandeja(self)

        self.motor.estado_cambiado.connect(self._al_cambiar_estado)
        self.motor.nuevo_registro.connect(self.ventana.agregar_registro)
        for origen in (self.ventana, self.bandeja):
            origen.iniciar_pedido.connect(self.iniciar)
            origen.pausa_pedida.connect(self.alternar_pausa)
            origen.detener_pedido.connect(self.motor.detener)
        self.bandeja.abrir_pedido.connect(self.ventana.traer_al_frente)
        self.bandeja.cerrar_pedido.connect(self.cerrar)
        self.ventana.config_guardada.connect(self._guardar_config)
        self.ventana.autoinicio_pedido.connect(self._cambiar_autoinicio)
        self.ventana.escondida.connect(self._al_esconder_ventana)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._al_cambiar_tema)

        self._servidor_instancia = QLocalServer(self)
        QLocalServer.removeServer(_NOMBRE_INSTANCIA)
        self._servidor_instancia.listen(_NOMBRE_INSTANCIA)
        self._servidor_instancia.newConnection.connect(self._al_abrir_otra_vez)

        self.bandeja.mostrar()
        self._al_cambiar_estado()
        if error_config:
            self.ventana.agregar_registro(error_config)

        primera_vez = not self.config.rol or bool(self.config.errores())
        if not en_bandeja or primera_vez:
            self.ventana.traer_al_frente()
            if primera_vez:
                self.ventana.mostrar_pagina("conexion")
        if self.config.conectar_al_abrir and not primera_vez:
            self.motor.iniciar()

    # ---- Motor --------------------------------------------------------------------------
    def iniciar(self):
        problemas = self.config.errores()
        if problemas:
            self.ventana.traer_al_frente()
            self.ventana.mostrar_pagina("conexion")
            QMessageBox.information(
                self.ventana, "Falta configurar algo",
                "Antes de iniciar, completá esto y tocá Guardar cambios:\n\n• "
                + "\n• ".join(problemas),
            )
            return
        self.motor.iniciar()

    def alternar_pausa(self):
        if self.motor.datos.get("pausa_local"):
            self.motor.reanudar()
        else:
            self.motor.pausar()

    def _al_cambiar_estado(self):
        activo, datos, error = self.motor.activo, self.motor.datos, self.motor.error
        self.ventana.mostrar_estado(activo, datos, error)
        self.bandeja.mostrar_estado(activo, datos, error)
        self._recordar_otra_pc(datos)

    def _recordar_otra_pc(self, datos):
        """Guarda nombre y monitores de la otra PC para dibujarla aunque no esté conectada."""
        otra = (datos or {}).get("otra_pc") or {}
        nombre, monitores = otra.get("nombre"), otra.get("monitores")
        if not nombre or not monitores:
            return
        cambios = {}
        if nombre != self.config.nombre_otra_pc:
            cambios["nombre_otra_pc"] = nombre
        if monitores != self.config.monitores_otra_pc:
            cambios["monitores_otra_pc"] = monitores
        lado = datos.get("lado")
        if self.config.rol == CLIENTE and lado and lado != self.config.lado_otra_pantalla:
            cambios["lado_otra_pantalla"] = lado  # En el cliente lo decide la PC principal.
        if not cambios:
            return
        self.config = replace(self.config, **cambios)
        self._guardar_campos(cambios)
        self.ventana.actualizar_otra_pc(nombre, monitores, cambios.get("lado_otra_pantalla"))

    # ---- Configuración ----------------------------------------------------------------
    def _guardar_campos(self, cambios):
        """Guarda solo algunos campos, sin pisar lo que el usuario esté editando."""
        try:
            en_disco = modulo_config.cargar(self.ruta)
        except (ValueError, TypeError):
            en_disco = self.config
        modulo_config.guardar(replace(en_disco, **cambios), self.ruta)

    def _guardar_config(self, nueva):
        era_primera_vez = bool(self.config.errores())
        try:
            modulo_config.guardar(nueva, self.ruta)
        except OSError as error:
            QMessageBox.warning(self.ventana, "No se pudo guardar", str(error))
            return
        self.config = nueva
        self.ventana.cargar_formulario(nueva)
        self.ventana.agregar_registro("Configuración guardada.")
        if self.motor.activo:
            self.ventana.agregar_registro("Reiniciando para aplicar los cambios...")
            self.motor.reiniciar()
        elif era_primera_vez and not nueva.errores() and nueva.conectar_al_abrir:
            self.motor.iniciar()

    def _cambiar_autoinicio(self, prender):
        if prender:
            ok, mensaje = autoinicio.activar()
        else:
            ok, mensaje = autoinicio.desactivar()
        quedo = autoinicio.esta_activo()
        self.ventana.poner_autoinicio(quedo)
        self.config = replace(self.config, iniciar_con_windows=quedo)
        self._guardar_campos({"iniciar_con_windows": quedo})
        self.ventana.agregar_registro(mensaje)
        if not ok:
            QMessageBox.warning(self.ventana, "Inicio con Windows", mensaje)

    # ---- Ventana y bandeja ----------------------------------------------------------------
    def _al_esconder_ventana(self):
        if not self._aviso_bandeja_mostrado:
            self._aviso_bandeja_mostrado = True
            self.bandeja.avisar(
                "Sigo funcionando acá",
                "Mouse Compartido queda en la bandeja. Para cerrarlo del todo: click derecho → Cerrar.",
            )

    def _al_abrir_otra_vez(self):
        conexion = self._servidor_instancia.nextPendingConnection()
        if conexion is None:
            return

        def leer():
            if bytes(conexion.readAll()).startswith(b"mostrar"):
                self.ventana.traer_al_frente()
            conexion.disconnectFromServer()

        conexion.readyRead.connect(leer)

    def _al_cambiar_tema(self, *_):
        estilo.aplicar(self.app)
        iconos.icono_estado.cache_clear()
        self.ventana.al_cambiar_tema()

    def cerrar(self):
        self.ventana.agregar_registro("Cerrando...")
        self.motor.cerrar_y_esperar()
        self.bandeja.esconder()
        self.app.quit()


def correr_app(ruta_config, en_bandeja=False):
    app = QApplication(sys.argv)
    app.setApplicationName("Mouse Compartido")
    app.setQuitOnLastWindowClosed(False)  # Cerrar la ventana no cierra el programa.
    if _avisar_a_la_otra_instancia(mostrar=not en_bandeja):
        return 0  # Ya estaba abierto: se mostró ese y este termina.
    estilo.aplicar(app)
    app.setWindowIcon(iconos.icono_estado("conectado"))
    aplicacion = Aplicacion(app, ruta_config, en_bandeja)
    app.aboutToQuit.connect(aplicacion.motor.cerrar_y_esperar)
    return app.exec()
