"""Ventanita con el avance de los archivos que van y vienen.

Aparece sola abajo a la derecha cuando empieza un envío, sin robarte el foco
(si estás escribiendo en otra ventana, seguís escribiendo), y se esconde sola
un rato después de que termina todo. Cada envío tiene su botón Cancelar.

Lo de la carpeta sincronizada no se muestra acá (serían cientos de renglones):
su estado está en la página Compartir.
"""

import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..datos import transferencias as T
from .widgets import etiqueta

_QUEDA_TERMINADO_MS = 6000  # Cuánto queda a la vista un envío que terminó bien.
_QUEDA_FALLIDO_MS = 20000  # Y uno que falló (para que llegues a leer por qué).
_ESCONDER_MS = 1500


class FilaEnvio(QFrame):
    cancelar_pedido = Signal(str)

    def __init__(self, progreso, nombre_otra):
        super().__init__()
        self.setObjectName("FilaEnvio")
        self.clave = progreso.clave
        self._destino = ""
        columna = QVBoxLayout(self)
        columna.setContentsMargins(12, 10, 12, 10)
        columna.setSpacing(6)
        sentido = f"Mandando a {nombre_otra}" if progreso.sale else f"Llegando de {nombre_otra}"
        if progreso.motivo == T.PORTAPAPELES:
            sentido += " (copiar y pegar)"
        self.sentido = etiqueta(sentido, "Tenue")
        columna.addWidget(self.sentido)
        self.nombre = etiqueta(progreso.descripcion or "Archivos")
        self.nombre.setStyleSheet("font-weight: 600;")
        columna.addWidget(self.nombre)
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(6)
        columna.addWidget(self.barra)
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.detalle = etiqueta("", "Suave", ajustar=True)
        fila.addWidget(self.detalle, 1)
        self.boton = QPushButton("Cancelar")
        self.boton.clicked.connect(self._al_tocar)
        fila.addWidget(self.boton, 0, Qt.AlignVCenter)
        columna.addLayout(fila)
        self.actualizar(progreso)

    def actualizar(self, progreso):
        self.barra.setValue(int(progreso.fraccion * 1000))
        if progreso.estado == "en curso":
            texto = f"{T.peso(progreso.hecho)} de {T.peso(progreso.total)}"
            if progreso.velocidad > 0:
                texto += f" · {T.peso(progreso.velocidad)}/s"
            self.detalle.setText(texto)
            return
        if progreso.estado == "terminado":
            self.barra.setValue(1000)
            if progreso.sale:
                self.detalle.setText("Listo.")
            elif progreso.motivo == T.PORTAPAPELES:
                self.detalle.setText("Listo: ya podés pegarlo (Ctrl+V).")
            else:
                self.detalle.setText(f"Listo. Está en {progreso.destino}")
            if progreso.detalle:  # Terminó, pero algún archivo no se pudo.
                self.detalle.setText(self.detalle.text() + f"\nOjo: {progreso.detalle}")
        else:
            titulo = "Cancelado" if progreso.estado == "cancelado" else "No se pudo"
            self.detalle.setText(f"{titulo}: {progreso.detalle}" if progreso.detalle else titulo)
        # Ya no hay nada que cancelar: el botón pasa a abrir la carpeta (si llegó algo).
        if not progreso.sale and progreso.estado == "terminado" and progreso.destino:
            self._destino = progreso.destino
            self.boton.setText("Abrir carpeta")
        else:
            self.boton.setVisible(False)

    def _al_tocar(self):
        if self._destino:
            try:
                os.startfile(self._destino)
            except OSError:
                pass
        else:
            self.boton.setEnabled(False)
            self.cancelar_pedido.emit(self.clave)


class VentanaProgreso(QWidget):
    cancelar_pedido = Signal(str)  # Clave del envío ("sale-3", "llega-5").

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setObjectName("Fondo")
        self.setWindowTitle("Archivos · Mouse Compartido")
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # Que no te saque el foco.
        self.setFixedWidth(400)
        columna = QVBoxLayout(self)
        columna.setContentsMargins(12, 12, 12, 12)
        columna.setSpacing(8)
        self._lista = QVBoxLayout()
        self._lista.setSpacing(8)
        columna.addLayout(self._lista)
        self._filas = {}
        self._esconder = QTimer(self)
        self._esconder.setSingleShot(True)
        self._esconder.setInterval(_ESCONDER_MS)
        self._esconder.timeout.connect(self._esconder_si_vacia)

    def mostrar_progreso(self, progreso, nombre_otra):
        if progreso.motivo == T.CARPETA:
            return
        fila = self._filas.get(progreso.clave)
        if fila is None:
            if progreso.estado != "en curso" and progreso.total < T.PEDAZO:
                return  # Algo chico que terminó antes de mostrarse: no hace falta.
            fila = FilaEnvio(progreso, nombre_otra)
            fila.cancelar_pedido.connect(self.cancelar_pedido)
            self._filas[progreso.clave] = fila
            self._lista.addWidget(fila)
            self._esconder.stop()
            self._ubicar()
            if not self.isVisible():
                self.show()
        else:
            fila.actualizar(progreso)
        if progreso.estado != "en curso":
            espera = _QUEDA_TERMINADO_MS if progreso.estado == "terminado" else _QUEDA_FALLIDO_MS
            QTimer.singleShot(espera, lambda clave=progreso.clave: self._quitar(clave))

    def _quitar(self, clave):
        fila = self._filas.pop(clave, None)
        if fila is None:
            return
        self._lista.removeWidget(fila)
        fila.deleteLater()
        QTimer.singleShot(0, self._ubicar)
        if not self._filas:
            self._esconder.start()

    def _esconder_si_vacia(self):
        if not self._filas:
            self.hide()

    def _ubicar(self):
        """Abajo a la derecha de la pantalla principal, sobre la barra de tareas."""
        self.adjustSize()
        pantalla = QGuiApplication.primaryScreen()
        if pantalla is None:
            return
        area = pantalla.availableGeometry()
        self.move(area.right() - self.width() - 16, area.bottom() - self.height() - 16)

    def closeEvent(self, evento):
        # Cerrarla solo la esconde: los envíos siguen (para frenarlos está Cancelar).
        evento.ignore()
        self.hide()
