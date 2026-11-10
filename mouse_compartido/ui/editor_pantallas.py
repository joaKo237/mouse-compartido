"""Editor visual de pantallas, como el de Configuración → Pantalla de Windows.

Muestra los monitores de esta PC (fijos, en azul) y los de la otra PC (en
violeta). Arrastrás la otra PC y, al soltarla, se pega al lado más cercano:
izquierda, derecha, arriba o abajo. Ese es el borde por el que va a pasar el cursor.
"""

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView

from ..comun.pantallas import DERECHA, Monitor, Pantallas
from . import estilo
from .geometria import escala_para, lado_mas_cercano, posicion_pegada

_MARGEN = 18  # Píxeles libres alrededor del dibujo.
_SEPARACION = 6  # Espacio entre las dos PCs ya pegadas.
_MONITOR_GENERICO = [Monitor(0, 0, 1920, 1080)]  # Si todavía no se sabe cómo es la otra.


class BloquePC(QGraphicsObject):
    """Los monitores de una PC dibujados juntos, como un solo bloque."""

    agarrado = Signal()
    soltado = Signal()
    movido = Signal()

    def __init__(self, pantallas, escala, nombre, color, movible):
        super().__init__()
        self.nombre = nombre
        self.color = QColor(color)
        self._rects = [
            QRectF((m.izq - pantallas.izq) * escala, (m.arriba - pantallas.arriba) * escala,
                   m.ancho * escala, m.alto * escala)
            for m in pantallas.monitores
        ]
        self._resoluciones = [f"{m.ancho} × {m.alto}" for m in pantallas.monitores]
        self.ancho = pantallas.ancho * escala
        self.alto = pantallas.alto * escala
        self._movible = movible
        if movible:
            self.setFlag(QGraphicsItem.ItemIsMovable)
            self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
            self.setCursor(Qt.OpenHandCursor)
            self.setZValue(2)

    def boundingRect(self):
        return QRectF(-2, -2, self.ancho + 4, self.alto + 4)

    def paint(self, p, _opcion, _widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        principal = max(range(len(self._rects)), key=lambda i: self._rects[i].width())
        for i, rect in enumerate(self._rects):
            interior = rect.adjusted(1.5, 1.5, -1.5, -1.5)
            camino = QPainterPath()
            camino.addRoundedRect(interior, 7, 7)
            relleno = QColor(self.color)
            relleno.setAlpha(235)
            p.fillPath(camino, relleno)
            p.setPen(QPen(self.color.lighter(135), 1.5))
            p.drawPath(camino)

            p.setPen(QColor("white"))
            if i == principal:
                fuente = QFont(estilo.familia_texto())
                fuente.setPointSizeF(10 if interior.width() > 110 else 8.5)
                fuente.setWeight(QFont.DemiBold)
                p.setFont(fuente)
                arriba = interior.adjusted(6, 0, -6, -interior.height() / 2 + 2)
                p.drawText(arriba, Qt.AlignHCenter | Qt.AlignBottom, _recortar(self.nombre, 22))
                fuente.setWeight(QFont.Normal)
                fuente.setPointSizeF(8)
                p.setFont(fuente)
                abajo = interior.adjusted(6, interior.height() / 2 + 2, -6, 0)
                p.drawText(abajo, Qt.AlignHCenter | Qt.AlignTop, self._resoluciones[i])
            elif interior.width() > 50:
                fuente = QFont(estilo.familia_texto())
                fuente.setPointSizeF(8)
                p.setFont(fuente)
                p.drawText(interior, Qt.AlignCenter, self._resoluciones[i])

    def itemChange(self, cambio, valor):
        if cambio == QGraphicsItem.ItemPositionHasChanged:
            self.movido.emit()
        return super().itemChange(cambio, valor)

    def mousePressEvent(self, evento):
        if self._movible:
            self.setCursor(Qt.ClosedHandCursor)
            self.agarrado.emit()
        super().mousePressEvent(evento)

    def mouseReleaseEvent(self, evento):
        super().mouseReleaseEvent(evento)
        if self._movible:
            self.setCursor(Qt.OpenHandCursor)
            self.soltado.emit()


def _recortar(texto, largo):
    return texto if len(texto) <= largo else texto[: largo - 1] + "…"


class EditorPantallas(QGraphicsView):
    lado_cambiado = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setMinimumHeight(220)
        self.setStyleSheet("background: transparent;")
        self._esta = Pantallas(_MONITOR_GENERICO)
        self._otra = Pantallas(_MONITOR_GENERICO)
        self._nombre_esta = "Esta PC"
        self._nombre_otra = "Otra PC"
        self.lado = DERECHA
        self.editable = True
        self._bloque_esta = None
        self._bloque_otra = None
        self._fantasma = None
        self._animacion = None
        self._arrastrando = False

    # ---- Lo que usa la ventana ------------------------------------------------------
    def configurar(self, esta, otra, nombre_esta, nombre_otra, lado, editable):
        """`esta` y `otra` son objetos Pantallas (`otra` puede ser None si no se conoce)."""
        self._esta = esta
        self._otra = otra or Pantallas(_MONITOR_GENERICO)
        self._nombre_esta = nombre_esta
        self._nombre_otra = nombre_otra or "Otra PC"
        self.lado = lado or DERECHA
        self.editable = editable
        self._redibujar()

    def poner_lado(self, lado, animar=True):
        self.lado = lado
        if self._bloque_otra is not None:
            self._pegar(animar)

    # ---- Dibujo ---------------------------------------------------------------------
    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self._redibujar()

    def _redibujar(self):
        escena = self.scene()
        escena.clear()
        self._bloque_esta = self._bloque_otra = self._fantasma = None
        ancho, alto = max(1, self.viewport().width()), max(1, self.viewport().height())
        escena.setSceneRect(0, 0, ancho, alto)
        escala = escala_para(
            (ancho, alto), (self._esta.ancho, self._esta.alto),
            (self._otra.ancho, self._otra.alto), _MARGEN + _SEPARACION,
        )
        tema = estilo.tema_actual()

        self._bloque_esta = BloquePC(self._esta, escala, self._nombre_esta, tema["acento"], False)
        self._bloque_esta.setPos((ancho - self._bloque_esta.ancho) / 2,
                                 (alto - self._bloque_esta.alto) / 2)
        escena.addItem(self._bloque_esta)

        self._bloque_otra = BloquePC(
            self._otra, escala, self._nombre_otra, tema["otra_pc"], self.editable
        )
        self._bloque_otra.agarrado.connect(self._al_agarrar)
        self._bloque_otra.soltado.connect(self._al_soltar)
        self._bloque_otra.movido.connect(self._al_mover)
        escena.addItem(self._bloque_otra)

        # Contorno punteado: muestra dónde va a quedar al soltar.
        self._fantasma = escena.addRect(
            QRectF(0, 0, self._bloque_otra.ancho, self._bloque_otra.alto),
            QPen(QColor(tema["otra_pc"]), 1.5, Qt.DashLine),
        )
        self._fantasma.setVisible(False)
        self._fantasma.setZValue(1)
        self._pegar(animar=False)

    def _caja_esta(self):
        b = self._bloque_esta
        return (b.x(), b.y(), b.ancho, b.alto)

    def _destino(self, lado):
        b = self._bloque_otra
        return QPointF(*posicion_pegada(self._caja_esta(), (b.ancho, b.alto), lado, _SEPARACION))

    def _pegar(self, animar):
        destino = self._destino(self.lado)
        if not animar:
            self._bloque_otra.setPos(destino)
            return
        self._animacion = QPropertyAnimation(self._bloque_otra, b"pos", self)
        self._animacion.setDuration(180)
        self._animacion.setEasingCurve(QEasingCurve.OutCubic)
        self._animacion.setEndValue(destino)
        self._animacion.start()

    def _lado_actual_del_bloque(self):
        b = self._bloque_otra
        centro = (b.x() + b.ancho / 2, b.y() + b.alto / 2)
        return lado_mas_cercano(self._caja_esta(), centro, (b.ancho, b.alto))

    def _al_agarrar(self):
        self._arrastrando = True
        if self._animacion is not None:
            self._animacion.stop()

    def _al_mover(self):
        if self._fantasma is None or not self._arrastrando:
            return
        self._fantasma.setPos(self._destino(self._lado_actual_del_bloque()))
        self._fantasma.setVisible(True)

    def _al_soltar(self):
        self._arrastrando = False
        self._fantasma.setVisible(False)
        lado = self._lado_actual_del_bloque()
        cambio = lado != self.lado
        self.lado = lado
        self._pegar(animar=True)
        if cambio:
            self.lado_cambiado.emit(lado)
