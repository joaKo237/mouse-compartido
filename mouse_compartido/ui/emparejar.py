"""Encontrar a la otra PC en la red y emparejarse, del lado de la interfaz.

RedLocal junta dos piezas que corren en sus propios hilos:
  * el Descubridor (red/descubrimiento.py): avisa "acá estoy" y escucha a las
    demás PCs, por cable y por Wi-Fi a la vez;
  * el Emparejador (red/emparejamiento.py): el emparejamiento de una sola vez,
    con el número de 6 cifras.
y convierte sus avisos en señales de Qt (que llegan en el hilo de la ventana).

DialogoEmparejar es la ventanita que muestra el número y los botones
"Coinciden" / "No coinciden".

Esto corre en la interfaz y no en el motor: así las PCs se encuentran y se
pueden emparejar aunque el mouse no se esté compartiendo todavía.
"""

import socket

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..red.descubrimiento import Descubridor
from ..red.emparejamiento import Emparejador
from .widgets import etiqueta


class _Eventos:
    """El Emparejador llama a estos métodos desde su hilo; acá se pasan a señales."""

    def __init__(self, red):
        self._red = red

    def pedido(self, intento):
        self._red.pedido.emit(intento)

    def codigo(self, intento):
        self._red.codigo.emit(intento)

    def terminado(self, intento, resultado, motivo):
        self._red.terminado.emit(intento, resultado, motivo)


class RedLocal(QObject):
    pcs_cambiaron = Signal()  # Apareció, cambió o desapareció una PC.
    pedido = Signal(object)  # Otra PC quiere emparejarse (Intento).
    codigo = Signal(object)  # Ya está el número para comparar (Intento).
    terminado = Signal(object, object, str)  # (Intento, Emparejada o None, motivo).

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._descubridor = None
        self._emparejador = None
        self.error = ""

    @property
    def puerto(self):
        return self.config.puerto + 1

    def iniciar(self):
        """Devuelve False (y deja el motivo en .error) si algún puerto está ocupado."""
        errores = []
        descubridor = Descubridor(self.puerto, self._datos_propios,
                                  al_cambiar=self.pcs_cambiaron.emit,
                                  direcciones_extra=self._direcciones_conocidas)
        if descubridor.iniciar():
            self._descubridor = descubridor
        else:
            errores.append(descubridor.error)
        emparejador = Emparejador(self.puerto, self._datos_propios, _Eventos(self))
        if emparejador.iniciar():
            self._emparejador = emparejador
        else:
            errores.append(emparejador.error)
        self.error = " ".join(errores)
        return not errores

    def detener(self):
        for pieza in (self._descubridor, self._emparejador):
            if pieza is not None:
                pieza.detener()
        self._descubridor = self._emparejador = None

    def poner_config(self, config):
        cambio_puerto = config.puerto != self.config.puerto
        self.config = config
        if cambio_puerto:
            self.detener()
            self.iniciar()
        elif self._descubridor is not None:
            self._descubridor.anunciar_ya()  # Que las demás se enteren del cambio ya.

    def pcs(self):
        """Las otras PCs con el programa abierto en la red."""
        if self._descubridor is None:
            return []
        return [pc for pc in self._descubridor.pcs() if pc.id != self.config.id_pc]

    def pareja(self):
        """La PC emparejada, si se la está viendo en la red (PcVista) o None."""
        if self._descubridor is None or not self.config.emparejada:
            return None
        return self._descubridor.buscar(self.config.emparejado_id)

    @property
    def intento(self):
        return self._emparejador.intento if self._emparejador is not None else None

    def emparejar_con(self, ip):
        """Empieza a emparejar. False si no se puede (otro en curso o sin puerto)."""
        return self._emparejador is not None and self._emparejador.emparejar_con(ip)

    # ---- Para los hilos ----------------------------------------------------------------
    def _datos_propios(self):
        config = self.config
        return {"id": config.id_pc, "nombre": socket.gethostname(), "rol": config.rol,
                "puerto": config.puerto, "emparejado_con": config.emparejado_id}

    def _direcciones_conocidas(self):
        config = self.config
        return [ip for ip in (config.ultima_ip_otra_pc, config.ip_servidor) if ip]


class DialogoEmparejar(QDialog):
    """Muestra el número de 6 cifras de un emparejamiento y pregunta si coincide."""

    def __init__(self, intento, parent=None):
        super().__init__(parent)
        self.intento = intento
        self._termino = False
        self.setWindowTitle("Emparejar con otra PC")
        self.setMinimumWidth(440)
        columna = QVBoxLayout(self)
        columna.setContentsMargins(26, 24, 26, 22)
        columna.setSpacing(12)
        self.titulo = etiqueta("", "TituloEstado", ajustar=True)
        columna.addWidget(self.titulo)
        self.texto = etiqueta("", "Suave", ajustar=True)
        columna.addWidget(self.texto)
        self.codigo = QLabel("")
        self.codigo.setObjectName("Codigo")
        self.codigo.setAlignment(Qt.AlignCenter)
        self.codigo.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.codigo.setVisible(False)
        columna.addWidget(self.codigo)
        botones = QHBoxLayout()
        botones.addStretch()
        self.boton_no = QPushButton("No coinciden")
        self.boton_no.clicked.connect(self._no_coinciden)
        self.boton_si = QPushButton("Coinciden")
        self.boton_si.setObjectName("Primario")
        self.boton_si.clicked.connect(self._coinciden)
        self.boton_cerrar = QPushButton("Cancelar")
        self.boton_cerrar.clicked.connect(self.reject)
        for boton in (self.boton_no, self.boton_si):
            boton.setVisible(False)
        botones.addWidget(self.boton_cerrar)
        botones.addWidget(self.boton_no)
        botones.addWidget(self.boton_si)
        columna.addLayout(botones)

        nombre = self._nombre()
        if intento.inicia:
            self.titulo.setText(f"Conectando con {nombre}…")
            self.texto.setText("En un momento aparece un número de 6 cifras en las dos PCs.")
        else:
            self.titulo.setText(f"{nombre} quiere emparejarse con esta PC")
            self.texto.setText("En un momento aparece un número de 6 cifras en las dos PCs. "
                               "Si no fuiste vos, tocá Cancelar.")

    def _nombre(self):
        return self.intento.nombre_otra or self.intento.ip or "la otra PC"

    def mostrar_codigo(self):
        nombre = self._nombre()
        self.titulo.setText("¿Ves el mismo número en las dos PCs?")
        self.texto.setText(
            f"Fijate que en {nombre} aparezca exactamente este número. Si es igual, tocá "
            "Coinciden acá y allá. Si es distinto, tocá No coinciden: alguien podría estar "
            "metiéndose en el medio.")
        self.codigo.setText(self.intento.codigo)
        self.codigo.setVisible(True)
        self.boton_cerrar.setVisible(False)
        self.boton_no.setVisible(True)
        self.boton_si.setVisible(True)
        self.boton_si.setFocus()

    def terminar(self, ok, motivo):
        self._termino = True
        for boton in (self.boton_no, self.boton_si):
            boton.setVisible(False)
        self.boton_cerrar.setText("Cerrar")
        self.boton_cerrar.setVisible(True)
        if ok:
            self.titulo.setText("¡Listo! Quedaron emparejadas")
            self.texto.setText(
                f"Desde ahora {self._nombre()} y esta PC se encuentran y se conectan solas, "
                "por cable o por Wi-Fi. No hace falta volver a hacer esto.")
            QTimer.singleShot(3000, self.accept)
        else:
            self.codigo.setVisible(False)
            self.titulo.setText("No se emparejaron")
            self.texto.setText(motivo or "Se canceló.")

    def _coinciden(self):
        self.intento.decidir(True)
        self.boton_si.setEnabled(False)
        self.boton_no.setEnabled(False)
        self.texto.setText(f"Listo acá. Falta que toques Coinciden en {self._nombre()}.")

    def _no_coinciden(self):
        self.intento.decidir(False)

    def reject(self):
        if not self._termino:
            self.intento.decidir(False)  # Cerrar con la X o Esc = cancelar.
        super().reject()
