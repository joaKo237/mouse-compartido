"""La aplicación con interfaz: une la ventana, la bandeja, el motor y la red.

Flujo general:
    ventana / bandeja  --(órdenes)-->  ControlMotor  --(proceso aparte)-->  motor
    ventana / bandeja  <--(estado)---  ControlMotor  <--(JSON por línea)--  motor
    RedLocal (encontrar PCs y emparejar) --(dónde está la otra PC)--------->  motor
    EnlaceDatos (canal de datos, abierto por el motor) <-------------------->  la otra PC
        ├─ portapapeles (texto e imágenes)
        └─ archivos (copiar y pegar, mandar, carpeta sincronizada)
"""

import sys
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from ..comun import config as modulo_config
from ..comun.config import CLIENTE, ROLES, SERVIDOR
from ..sistema import autoinicio, enviar_a, firewall, redes
from . import estilo, iconos, instancia
from .archivos import GestorArchivos, limpiar_temporales
from .bandeja import Bandeja
from .control_motor import ControlMotor
from .emparejar import DialogoEmparejar, RedLocal
from .enlace import EnlaceDatos
from .portapapeles import SincroPortapapeles
from .progreso import VentanaProgreso
from .ventana import VentanaPrincipal

_NOMBRES_ROL = {SERVIDOR: "tiene el mouse (servidor)", CLIENTE: "recibe el control (cliente)"}


class Aplicacion(QObject):
    _desde_hilo = Signal(str)  # Líneas para la actividad que vienen de otros hilos.

    def __init__(self, app, ruta_config, en_bandeja):
        super().__init__()
        self.app = app
        self.ruta = Path(ruta_config)
        self._aviso_bandeja_mostrado = False
        self._dialogo = None
        self._destinos_enviados = None  # Lo último que se le dijo al motor (None = nada aún).
        self._ruta_ip = None
        self._ruta_nombre = ""
        self._aviso_pareja = ""
        try:
            self.config = modulo_config.cargar(self.ruta)
            error_config = ""
        except (ValueError, TypeError) as error:
            self.config = modulo_config.Config()
            error_config = f"config.json tiene un error y se usaron los valores por defecto: {error}"

        # La primera vez se inventa el número de identidad de esta PC (y se guarda).
        con_id = modulo_config.con_identidad(self.config)
        if con_id.id_pc != self.config.id_pc:
            self.config = con_id
            self._guardar_campos({"id_pc": con_id.id_pc})
        # Lo que diga Windows manda: la tarea puede haberse borrado a mano.
        activo = autoinicio.esta_activo()
        if activo != self.config.iniciar_con_windows:
            self.config = replace(self.config, iniciar_con_windows=activo)

        self.motor = ControlMotor(self.ruta, self)
        self.enlace = EnlaceDatos(pedir_canal=self.motor.pedir_canal_datos, parent=self)
        self.ventana = VentanaPrincipal(self.config)
        self.bandeja = Bandeja(self)
        self.progreso = VentanaProgreso()
        self.portapapeles = SincroPortapapeles(app.clipboard(), self.config, self.enlace,
                                               parent=self)
        self.archivos = GestorArchivos(self.config, self.enlace,
                                       self.ruta.with_name("carpeta-estado.json"), parent=self)
        self.red = RedLocal(self.config, self)

        # Motor y canal de datos.
        self.motor.estado_cambiado.connect(self._al_cambiar_estado)
        self.motor.nuevo_registro.connect(self.ventana.agregar_registro)
        self.motor.canal_datos.connect(self.enlace.usar_canal)
        self.enlace.estado_cambiado.connect(self._mostrar_compartir)
        # Portapapeles y archivos.
        self.portapapeles.nuevo_registro.connect(self.ventana.agregar_registro)
        self.portapapeles.estado_cambiado.connect(self._mostrar_compartir)
        self.portapapeles.copiado_local.connect(self.archivos.al_copiar_algo)
        self.portapapeles.archivos_copiados.connect(self.archivos.al_copiar_archivos)
        self.archivos.nuevo_registro.connect(self.ventana.agregar_registro)
        self.archivos.aviso.connect(self.bandeja.avisar)
        self.archivos.progreso_cambiado.connect(self._mostrar_progreso)
        self.progreso.cancelar_pedido.connect(self.archivos.cancelar)
        self.ventana.archivos_soltados.connect(self.mandar_archivos)
        # Red y emparejamiento.
        self.red.pcs_cambiaron.connect(self._al_ver_pcs)
        self.red.pedido.connect(self._al_pedir_emparejar)
        self.red.codigo.connect(self._al_mostrar_codigo)
        self.red.terminado.connect(self._al_terminar_emparejamiento)
        self.ventana.emparejar_pedido.connect(self._emparejar_con)
        self.ventana.olvidar_pedido.connect(self._olvidar)
        # Ventana y bandeja.
        for origen in (self.ventana, self.bandeja):
            origen.iniciar_pedido.connect(self.iniciar)
            origen.pausa_pedida.connect(self.alternar_pausa)
            origen.detener_pedido.connect(self.motor.detener)
        self.bandeja.abrir_pedido.connect(self.ventana.traer_al_frente)
        self.bandeja.cerrar_pedido.connect(self.cerrar)
        self.ventana.config_guardada.connect(self._guardar_config)
        self.ventana.autoinicio_pedido.connect(self._cambiar_autoinicio)
        self.ventana.escondida.connect(self._al_esconder_ventana)
        self._desde_hilo.connect(self.ventana.agregar_registro)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._al_cambiar_tema)

        self._servidor_instancia = instancia.crear_servidor(self, self._al_recibir_de_otra_instancia)

        # El estado de la carpeta sincronizada cambia en otro hilo: se mira cada 2 segundos.
        self._reloj_carpeta = QTimer(self)
        self._reloj_carpeta.setInterval(2000)
        self._reloj_carpeta.timeout.connect(self._mostrar_compartir)
        self._reloj_carpeta.start()

        self.bandeja.mostrar()
        self._al_cambiar_estado()
        if error_config:
            self.ventana.agregar_registro(error_config)
        if not self.red.iniciar():
            self.ventana.agregar_registro(
                f"{self.red.error} Sin esto no se encuentran solas: escribí la IP en Conexión.")
        self._preparar_windows()
        threading.Thread(target=limpiar_temporales, name="limpiar", daemon=True).start()

        primera_vez = bool(self.config.errores())
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
                "Antes de iniciar, completá esto en la página Conexión:\n\n• "
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
        activo, error = self.motor.activo, self.motor.error
        datos = dict(self.motor.datos or {})
        datos["ruta"] = self._ruta_de(datos)
        self.ventana.mostrar_estado(activo, datos, error)
        self.bandeja.mostrar_estado(activo, datos, error)
        self._recordar_otra_pc(datos)
        conectado = activo and datos.get("estado") == "conectado"
        self.enlace.conexion_cambiada(conectado)
        if conectado:
            self.archivos.poner_mouse_aca(bool(datos.get("mouse_aca", True)))
        if not activo:
            self._destinos_enviados = None
        elif self._destinos_enviados is None and self.motor.datos:
            self._mandar_destinos()  # El motor recién arrancó y ya escucha órdenes.
        self._mostrar_compartir()

    def _ruta_de(self, datos):
        """"cable" o "Wi-Fi": por dónde va la conexión con la otra PC."""
        ip = ((datos.get("otra_pc") or {}).get("ip")) or ""
        if ip != self._ruta_ip:
            self._ruta_ip = ip
            try:
                self._ruta_nombre = redes.NOMBRES_RUTA.get(redes.prioridad(ip), "") if ip else ""
            except OSError:
                self._ruta_nombre = ""
        return self._ruta_nombre

    def _mandar_destinos(self):
        """En el cliente: le dice al motor en qué IPs se ve a la PC emparejada (cable primero)."""
        if not (self.motor.activo and self.config.rol == CLIENTE and self.config.emparejada):
            return
        pareja = self.red.pareja()
        destinos = pareja.destinos() if pareja is not None else []
        if destinos != self._destinos_enviados:
            self._destinos_enviados = destinos
            self.motor.poner_destinos(destinos)

    def _mostrar_compartir(self):
        conectado = self.motor.activo and self.motor.datos.get("estado") == "conectado"
        self.ventana.mostrar_portapapeles(
            self.portapapeles.activo, self.portapapeles.listo, conectado
        )
        self.ventana.mostrar_carpeta(self.archivos.texto_carpeta())

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
        ip = otra.get("ip")
        if ip and ip != self.config.ultima_ip_otra_pc:
            cambios["ultima_ip_otra_pc"] = ip
        lado = datos.get("lado")
        if self.config.rol == CLIENTE and lado and lado != self.config.lado_otra_pantalla:
            cambios["lado_otra_pantalla"] = lado  # En el cliente lo decide la PC principal.
        if not cambios:
            return
        self.config = replace(self.config, **cambios)
        self._guardar_campos(cambios)
        self.red.poner_config(self.config)
        self.ventana.actualizar_otra_pc(nombre, monitores, cambios.get("lado_otra_pantalla"))

    # ---- Red: encontrar a la otra PC -----------------------------------------------------
    def _al_ver_pcs(self):
        pareja = self.red.pareja()
        aviso = ""
        if pareja is not None:
            nombre = self.config.emparejado_nombre or pareja.nombre
            if pareja.emparejado_con and pareja.emparejado_con != self.config.id_pc:
                aviso = (f"{nombre} ahora está emparejada con otra PC, así que no se van a "
                         "conectar. Volvé a emparejarlas tocando Emparejar en la lista.")
            elif pareja.rol and pareja.rol == self.config.rol:
                aviso = (f"{nombre} también está como «{_NOMBRES_ROL.get(pareja.rol)}». Una PC "
                         "tiene que tener el mouse y la otra recibir el control: cambiá una de "
                         "las dos arriba y tocá Guardar cambios.")
        if aviso and aviso != self._aviso_pareja:
            self.ventana.agregar_registro(aviso)
        self._aviso_pareja = aviso
        self.ventana.mostrar_red(self.red.pcs(), pareja, aviso)
        self._mandar_destinos()

    # ---- Emparejar -----------------------------------------------------------------------
    def _emparejar_con(self, ip):
        if not self.red.emparejar_con(ip):
            QMessageBox.information(
                self.ventana, "Emparejar",
                "Ya hay un emparejamiento en curso. Terminalo o cancelalo primero."
                if self.red.intento is not None else
                f"No se puede emparejar: {self.red.error or 'el buscador de PCs no arrancó'}")
            return
        self._abrir_dialogo(self.red.intento)

    def _al_pedir_emparejar(self, intento):
        nombre = intento.nombre_otra or intento.ip
        self.ventana.traer_al_frente()
        self.bandeja.avisar("Emparejar", f"{nombre} quiere emparejarse con esta PC.")
        self._abrir_dialogo(intento)

    def _abrir_dialogo(self, intento):
        if intento is None:
            return
        if self._dialogo is not None:
            self._dialogo.close()
        self._dialogo = DialogoEmparejar(intento, self.ventana)
        self._dialogo.show()
        self._dialogo.raise_()
        self._dialogo.activateWindow()

    def _al_mostrar_codigo(self, intento):
        if self._dialogo is not None and self._dialogo.intento is intento:
            self._dialogo.mostrar_codigo()

    def _al_terminar_emparejamiento(self, intento, resultado, motivo):
        if self._dialogo is not None and self._dialogo.intento is intento:
            self._dialogo.terminar(resultado is not None, motivo)
        if resultado is None:
            self.ventana.agregar_registro(f"No se emparejó: {motivo}")
            return
        cambios = {
            "emparejado_id": resultado.id_otra,
            "emparejado_nombre": resultado.nombre_otra,
            "emparejado_clave": resultado.clave.hex(),
            "ultima_ip_otra_pc": resultado.ip_otra,
            "nombre_otra_pc": resultado.nombre_otra,
        }
        if resultado.id_otra != self.config.emparejado_id:
            cambios["monitores_otra_pc"] = []  # Los monitores eran de la PC anterior.
        if not self.config.rol and resultado.rol_otra in ROLES:
            # Si esta PC todavía no tenía función, se elige la que falta.
            cambios["rol"] = CLIENTE if resultado.rol_otra == SERVIDOR else SERVIDOR
        self._aplicar_campos(cambios)
        self.ventana.agregar_registro(f"Emparejada con {resultado.nombre_otra}. Desde ahora se "
                                      "conectan solas.")
        if self.motor.activo:
            self.motor.reiniciar()
        elif not self.config.errores() and self.config.conectar_al_abrir:
            self.motor.iniciar()

    def _olvidar(self):
        nombre = self.config.emparejado_nombre or "la otra PC"
        respuesta = QMessageBox.question(
            self.ventana, "Olvidar PC",
            f"¿Olvidar {nombre}? Dejan de conectarse hasta que las vuelvas a emparejar.")
        if respuesta != QMessageBox.Yes:
            return
        self.motor.detener()
        self.enlace.soltar()
        self._aplicar_campos({"emparejado_id": "", "emparejado_nombre": "",
                              "emparejado_clave": ""})
        self.ventana.agregar_registro(f"Se olvidó {nombre}.")

    def _aplicar_campos(self, cambios):
        """Cambia algunos campos de la configuración (fuera del botón Guardar)."""
        self.config = replace(self.config, **cambios)
        self._guardar_campos(cambios)
        self.ventana.aplicar_campos(cambios)
        self._repartir_config()
        self._al_ver_pcs()

    # ---- Archivos ------------------------------------------------------------------------
    def mandar_archivos(self, rutas):
        problema = self.archivos.mandar(rutas)
        if problema:
            self.ventana.agregar_registro(f"No se mandó nada: {problema}")
            self.bandeja.avisar("No se mandaron los archivos", problema, error=True)

    def _mostrar_progreso(self, progreso):
        nombre = self.config.emparejado_nombre or "la otra PC"
        self.progreso.mostrar_progreso(progreso, nombre)

    # ---- Configuración ----------------------------------------------------------------
    def _guardar_campos(self, cambios):
        """Guarda solo algunos campos, sin pisar lo que el usuario esté editando."""
        try:
            en_disco = modulo_config.cargar(self.ruta)
        except (ValueError, TypeError):
            en_disco = self.config
        try:
            modulo_config.guardar(replace(en_disco, **cambios), self.ruta)
        except OSError as error:
            ventana = getattr(self, "ventana", None)  # Al arrancar todavía no existe.
            if ventana is not None:
                ventana.agregar_registro(f"No se pudo guardar la configuración: {error}")

    def _guardar_config(self, nueva):
        anterior = self.config
        era_primera_vez = bool(anterior.errores())
        try:
            modulo_config.guardar(nueva, self.ruta)
        except OSError as error:
            QMessageBox.warning(self.ventana, "No se pudo guardar", str(error))
            return
        self.config = nueva
        self._repartir_config()
        self.ventana.cargar_formulario(nueva)
        self.ventana.agregar_registro("Configuración guardada.")
        self._al_ver_pcs()
        if nueva.puerto != anterior.puerto or nueva.compartir_archivos != anterior.compartir_archivos:
            self._preparar_windows()
        if self.motor.activo:
            self.ventana.agregar_registro("Reiniciando para aplicar los cambios...")
            self.motor.reiniciar()
        elif era_primera_vez and not nueva.errores() and nueva.conectar_al_abrir:
            self.motor.iniciar()

    def _repartir_config(self):
        """Le pasa la configuración nueva a cada parte que la usa."""
        self.portapapeles.poner_config(self.config)
        self.archivos.poner_config(self.config)
        self.red.poner_config(self.config)
        self._mostrar_compartir()

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

    # ---- Windows: firewall y "Enviar a" ---------------------------------------------------
    def _preparar_windows(self):
        """En otro hilo (tarda un par de segundos): abre el firewall y crea o borra el
        acceso de "Enviar a"."""
        puerto, con_archivos = self.config.puerto, self.config.compartir_archivos

        def preparar():
            cambio, error = firewall.asegurar(puerto)
            if error == "sin permisos":
                self._desde_hilo.emit(
                    "Sin permisos de Administrador no se pudo revisar el firewall de Windows. "
                    "Si la otra PC no aparece en Conexión, abrí el programa como Administrador "
                    "una vez.")
            elif error:
                self._desde_hilo.emit(f"No se pudo abrir el firewall de Windows: {error}")
            elif cambio:
                self._desde_hilo.emit(
                    f"Firewall de Windows: se abrieron los puertos {puerto} y {puerto + 1} para "
                    "la red local, así la otra PC puede encontrar a esta.")
            if con_archivos:
                if not enviar_a.existe():
                    problema = enviar_a.crear()
                    if problema:
                        self._desde_hilo.emit(f"No se pudo crear el acceso de «Enviar a»: "
                                              f"{problema}")
            else:
                enviar_a.quitar()

        threading.Thread(target=preparar, name="preparar-windows", daemon=True).start()

    # ---- Ventana y bandeja ----------------------------------------------------------------
    def _al_esconder_ventana(self):
        if not self._aviso_bandeja_mostrado:
            self._aviso_bandeja_mostrado = True
            self.bandeja.avisar(
                "Sigo funcionando acá",
                "Mouse Compartido queda en la bandeja. Para cerrarlo del todo: click derecho → Cerrar.",
            )

    def _al_recibir_de_otra_instancia(self, datos):
        accion, rutas = instancia.leer_mensaje(datos)
        if accion == "mostrar":
            self.ventana.traer_al_frente()
        elif accion == "enviar" and rutas:
            self.mandar_archivos(rutas)

    def _al_cambiar_tema(self, *_):
        estilo.aplicar(self.app)
        iconos.icono_estado.cache_clear()
        self.ventana.al_cambiar_tema()

    def cerrar(self):
        self.ventana.agregar_registro("Cerrando...")
        self.red.detener()
        self.archivos.detener()
        self.enlace.soltar()
        self.motor.cerrar_y_esperar()
        self.bandeja.esconder()
        self.app.quit()


def correr_app(ruta_config, en_bandeja=False):
    app = QApplication(sys.argv)
    app.setApplicationName("Mouse Compartido")
    app.setQuitOnLastWindowClosed(False)  # Cerrar la ventana no cierra el programa.
    if instancia.mandar(instancia.NADA if en_bandeja else instancia.MOSTRAR, espera_ms=400):
        return 0  # Ya estaba abierto: se mostró ese y este termina.
    estilo.aplicar(app)
    app.setWindowIcon(iconos.icono_estado("conectado"))
    aplicacion = Aplicacion(app, ruta_config, en_bandeja)
    app.aboutToQuit.connect(aplicacion.motor.cerrar_y_esperar)
    return app.exec()
