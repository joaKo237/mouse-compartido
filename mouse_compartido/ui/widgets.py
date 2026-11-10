"""Piezas visuales reutilizables: tarjetas, interruptores, filas de opciones."""

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import estilo


def etiqueta(texto, nombre=None, ajustar=False):
    """Un QLabel con nombre de estilo (ver estilo.py) y, si hace falta, texto que se ajusta."""
    label = QLabel(texto)
    if nombre:
        label.setObjectName(nombre)
    if ajustar:
        label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse if ajustar else Qt.NoTextInteraction)
    return label


def glifo(clave, puntos=12, color=None):
    """Un ícono de la fuente de Windows, como texto.

    La fuente va en el estilo del propio widget: si se usara setFont, la hoja de
    estilo general (que pone Segoe UI en todo) la pisaría y se verían cuadraditos.
    """
    label = QLabel(estilo.GLIFOS.get(clave, ""))
    fuente = estilo.fuente_iconos(puntos)
    reglas = [f"font-size: {puntos}pt;"]
    if fuente:
        reglas.append(f'font-family: "{fuente.family()}";')
    if color:
        reglas.append(f"color: {color};")
    label.setStyleSheet(" ".join(reglas))
    label.setAlignment(Qt.AlignCenter)
    return label


def pixmap_glifo(clave, color, tam=20):
    """El mismo ícono, pero como imagen (para listas y botones)."""
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap(tam, tam)
    pixmap.fill(Qt.transparent)
    fuente = estilo.fuente_iconos(tam * 0.55)
    if fuente is None:
        return pixmap
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(fuente)
    p.setPen(QColor(color))
    p.drawText(pixmap.rect(), Qt.AlignCenter, estilo.GLIFOS.get(clave, ""))
    p.end()
    return pixmap


def separador():
    linea = QFrame()
    linea.setObjectName("Separador")
    linea.setFrameShape(QFrame.NoFrame)
    return linea


class Tarjeta(QFrame):
    """Recuadro blanco (o gris oscuro) con bordes redondeados y título opcional."""

    def __init__(self, titulo=None, descripcion=None, insignia=None):
        super().__init__()
        self.setObjectName("Tarjeta")
        self.cuerpo = QVBoxLayout(self)
        self.cuerpo.setContentsMargins(20, 18, 20, 18)
        self.cuerpo.setSpacing(12)
        if titulo:
            cabecera = QHBoxLayout()
            cabecera.setSpacing(10)
            cabecera.addWidget(etiqueta(titulo, "TituloTarjeta"))
            if insignia:
                cabecera.addWidget(Insignia(insignia))
            cabecera.addStretch()
            self.cuerpo.addLayout(cabecera)
        if descripcion:
            self.cuerpo.addWidget(etiqueta(descripcion, "Suave", ajustar=True))

    def agregar(self, widget_o_layout):
        if isinstance(widget_o_layout, QWidget):
            self.cuerpo.addWidget(widget_o_layout)
        else:
            self.cuerpo.addLayout(widget_o_layout)
        return widget_o_layout


class Insignia(QLabel):
    """Cartelito redondeado, por ejemplo "Etapa 3"."""

    def __init__(self, texto):
        super().__init__(texto)
        self.setObjectName("Insignia")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


class Tecla(QLabel):
    """Una tecla dibujada, para mostrar atajos (Ctrl, Alt, Esc...)."""

    def __init__(self, texto):
        super().__init__(texto)
        self.setObjectName("Tecla")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


class FilaOpcion(QWidget):
    """Título y explicación a la izquierda; el control (interruptor, campo...) a la derecha."""

    def __init__(self, titulo, descripcion="", control=None, insignia=None):
        super().__init__()
        fila = QHBoxLayout(self)
        fila.setContentsMargins(0, 2, 0, 2)
        fila.setSpacing(16)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        cabecera = QHBoxLayout()
        cabecera.setSpacing(8)
        self.titulo = etiqueta(titulo)
        self.titulo.setStyleSheet("font-weight: 600;")
        cabecera.addWidget(self.titulo)
        if insignia:
            cabecera.addWidget(Insignia(insignia))
        cabecera.addStretch()
        textos.addLayout(cabecera)
        if descripcion:
            self.descripcion = etiqueta(descripcion, "Suave", ajustar=True)
            textos.addWidget(self.descripcion)
        fila.addLayout(textos, 1)
        if control is not None:
            fila.addWidget(control, 0, Qt.AlignVCenter)


class Interruptor(QAbstractButton):
    """Interruptor deslizable (como los de Configuración de Windows), con animación."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._posicion = 0.0  # 0 = apagado, 1 = prendido.
        self._animacion = QPropertyAnimation(self, b"posicion", self)
        self._animacion.setDuration(140)
        self._animacion.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animar)

    def sizeHint(self):
        return QSize(44, 24)

    def _leer_posicion(self):
        return self._posicion

    def _poner_posicion(self, valor):
        self._posicion = valor
        self.update()

    posicion = Property(float, _leer_posicion, _poner_posicion)

    def _animar(self, prendido):
        self._animacion.stop()
        self._animacion.setStartValue(self._posicion)
        self._animacion.setEndValue(1.0 if prendido else 0.0)
        self._animacion.start()

    def setChecked(self, valor):
        """Cambio sin animación (por ejemplo, al cargar la configuración)."""
        super().setChecked(valor)
        self._animacion.stop()
        self._poner_posicion(1.0 if valor else 0.0)

    def paintEvent(self, _evento):
        tema = estilo.tema_actual()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pista = QRectF(1, 2, 42, 20)
        apagado = QColor(tema["borde_fuerte"])
        prendido = QColor(tema["acento"])
        t = self._posicion
        color = QColor(
            int(apagado.red() + (prendido.red() - apagado.red()) * t),
            int(apagado.green() + (prendido.green() - apagado.green()) * t),
            int(apagado.blue() + (prendido.blue() - apagado.blue()) * t),
        )
        if not self.isEnabled():
            color.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(pista, 10, 10)
        p.setBrush(QColor("#ffffff") if self.isEnabled() else QColor(tema["campo"]))
        x = 4 + t * 20
        p.drawEllipse(QRectF(x, 5, 14, 14))
        p.end()
