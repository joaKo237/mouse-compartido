"""Íconos dibujados por código: un mouse blanco sobre un cuadrado del color del estado.

Dibujarlos así evita depender de archivos de imagen y permite tener uno por
color sin diseñar nada aparte.
"""

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .estilo import COLOR_ESTADO


def _dibujar(tam, color, flecha):
    pixmap = QPixmap(tam, tam)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    u = tam / 64.0  # Todo se dibuja en una grilla de 64 y se escala.

    # Fondo: cuadrado redondeado con un leve degradé.
    base = QColor(color)
    fondo = QPainterPath()
    fondo.addRoundedRect(QRectF(2 * u, 2 * u, 60 * u, 60 * u), 15 * u, 15 * u)
    p.fillPath(fondo, base)
    p.fillPath(fondo, QColor(255, 255, 255, 28))  # Brillo suave.

    # Mouse: cuerpo redondeado, división de botones y rueda.
    lapiz = QPen(QColor("white"), 4.2 * u)
    lapiz.setCapStyle(Qt.RoundCap)
    p.setPen(lapiz)
    p.setBrush(Qt.NoBrush)
    cuerpo = QRectF(21 * u, 13 * u, 22 * u, 36 * u)
    p.drawRoundedRect(cuerpo, 11 * u, 11 * u)
    p.drawLine(QPointF(32 * u, 13 * u), QPointF(32 * u, 25 * u))
    p.drawLine(QPointF(21.5 * u, 26 * u), QPointF(42.5 * u, 26 * u))

    if flecha:
        # Flechita: el mouse está manejando la otra PC.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("white"))
        punta = QPainterPath()
        punta.moveTo(49 * u, 40 * u)
        punta.lineTo(60 * u, 48 * u)
        punta.lineTo(49 * u, 56 * u)
        punta.closeSubpath()
        p.drawPath(punta)
    p.end()
    return pixmap


@lru_cache(maxsize=32)
def icono_estado(clave, flecha=False):
    """Ícono para la bandeja y la ventana según el estado (ver resumen.py)."""
    color = COLOR_ESTADO.get(clave, COLOR_ESTADO["detenido"])
    icono = QIcon()
    for tam in (16, 20, 24, 32, 48, 64, 256):
        icono.addPixmap(_dibujar(tam, color, flecha))
    return icono


def pixmap_estado(clave, tam=64):
    return _dibujar(tam, COLOR_ESTADO.get(clave, COLOR_ESTADO["detenido"]), False)
