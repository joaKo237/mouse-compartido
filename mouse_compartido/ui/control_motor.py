"""La interfaz manejando al motor, que corre en otro proceso (ver motor/proceso.py).

QProcess avisa con señales cuando el motor escribe algo o termina, así la
ventana nunca se queda esperando y sigue respondiendo.
"""

import json
from collections import deque

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from ..sistema import rutas

_ESPERA_CIERRE_MS = 4000  # Si el motor no cierra solo en este tiempo, se lo cierra a la fuerza.


class ControlMotor(QObject):
    estado_cambiado = Signal()  # Llegó una foto nueva del motor, o arrancó/terminó.
    nuevo_registro = Signal(str)  # Una línea para la lista de actividad.

    def __init__(self, ruta_config, parent=None):
        super().__init__(parent)
        self._ruta_config = str(ruta_config)
        self._proceso = None
        self._pendiente = b""
        self._pidio_salir = False
        self._reiniciar_al_terminar = False
        self._errores = deque(maxlen=15)  # Últimas líneas de error, por si se cae.
        self.datos = {}  # Última foto del estado que mandó el motor.
        self.error = ""  # Por qué terminó mal la última vez (vacío si terminó bien).

    @property
    def activo(self):
        return self._proceso is not None

    # ---- Órdenes ------------------------------------------------------------------
    def iniciar(self):
        if self.activo:
            return
        self.error = ""
        self.datos = {}
        self._pendiente = b""
        self._pidio_salir = False
        self._errores.clear()
        programa, argumentos = rutas.comando("motor", "--config", self._ruta_config)
        proceso = QProcess(self)
        proceso.setProgram(str(programa))
        proceso.setArguments(argumentos)
        proceso.setWorkingDirectory(str(rutas.RAIZ))
        proceso.readyReadStandardOutput.connect(self._leer_salida)
        proceso.readyReadStandardError.connect(self._leer_errores)
        proceso.finished.connect(self._al_terminar)
        proceso.errorOccurred.connect(self._al_fallar_arranque)
        self._proceso = proceso
        self.nuevo_registro.emit("Iniciando...")
        proceso.start()
        self.estado_cambiado.emit()

    def pausar(self):
        self._ordenar("pausar")

    def reanudar(self):
        self._ordenar("reanudar")

    def detener(self):
        """Le pide al motor que cierre (suelta todo y devuelve el mouse) sin esperar."""
        if not self.activo:
            return
        self._pidio_salir = True
        self._ordenar("salir")
        proceso = self._proceso
        QTimer.singleShot(_ESPERA_CIERRE_MS, lambda: self._forzar(proceso))

    def reiniciar(self):
        """Para aplicar una configuración nueva: cierra y vuelve a arrancar."""
        if self.activo:
            self._reiniciar_al_terminar = True
            self.detener()
        else:
            self.iniciar()

    def cerrar_y_esperar(self):
        """Al salir del programa: acá sí se espera (un instante) a que el motor cierre."""
        proceso = self._proceso
        if proceso is None:
            return
        self._pidio_salir = True
        self._reiniciar_al_terminar = False
        self._ordenar("salir")
        if not proceso.waitForFinished(_ESPERA_CIERRE_MS):
            proceso.kill()
            proceso.waitForFinished(1000)

    # ---- Internos -----------------------------------------------------------------
    def _ordenar(self, orden):
        if self._proceso is not None:
            self._proceso.write((json.dumps({"orden": orden}) + "\n").encode("ascii"))

    def _forzar(self, proceso):
        if proceso is not None and proceso is self._proceso:
            self.nuevo_registro.emit("El motor no respondió: se cerró a la fuerza.")
            proceso.kill()

    def _leer_salida(self):
        if self._proceso is None:
            return
        self._pendiente += bytes(self._proceso.readAllStandardOutput())
        *lineas, self._pendiente = self._pendiente.split(b"\n")
        hubo_estado = False
        for linea in lineas:
            linea = linea.strip()
            if not linea:
                continue
            try:
                evento = json.loads(linea)
            except ValueError:
                self.nuevo_registro.emit(linea.decode("utf-8", "replace"))
                continue
            if evento.get("evento") == "estado":
                evento.pop("evento", None)
                self.datos = evento
                if evento.get("estado") == "error":
                    self.error = evento.get("detalle", "")
                hubo_estado = True
            elif evento.get("evento") == "log":
                self.nuevo_registro.emit(evento.get("texto", ""))
        if hubo_estado:
            self.estado_cambiado.emit()

    def _leer_errores(self):
        if self._proceso is None:
            return
        texto = bytes(self._proceso.readAllStandardError()).decode("utf-8", "replace")
        for linea in texto.splitlines():
            if linea.strip():
                self._errores.append(linea)
                self.nuevo_registro.emit(linea)

    def _al_fallar_arranque(self, error):
        if error == QProcess.FailedToStart:
            self.error = "No se pudo arrancar el motor (¿está bien instalado Python?)."
            self._terminado()

    def _al_terminar(self, codigo, estado_salida):
        self._leer_salida()
        self._leer_errores()
        inesperado = estado_salida == QProcess.CrashExit or codigo != 0
        if inesperado and not self.error and not self._pidio_salir:
            ultima = self._errores[-1] if self._errores else ""
            self.error = f"El motor se cerró de golpe (código {codigo}). {ultima}".strip()
        self.nuevo_registro.emit("Detenido." if not self.error else f"Detenido: {self.error}")
        self._terminado()

    def _terminado(self):
        if self._proceso is None:
            return
        self._proceso.deleteLater()
        self._proceso = None
        self.datos = {}
        self.estado_cambiado.emit()
        if self._reiniciar_al_terminar:
            self._reiniciar_al_terminar = False
            self.iniciar()
