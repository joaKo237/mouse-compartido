"""Ejecución del mouse y el teclado en el cliente (o su simulación para pruebas)."""

import ctypes
import time

from . import protocolo as P
from . import win32 as W
from .pantallas import Monitor, Pantallas
from .registro import log

_BOTONES = {
    P.BOTON_IZQUIERDO: (W.MOUSEEVENTF_LEFTDOWN, W.MOUSEEVENTF_LEFTUP, 0),
    P.BOTON_DERECHO: (W.MOUSEEVENTF_RIGHTDOWN, W.MOUSEEVENTF_RIGHTUP, 0),
    P.BOTON_MEDIO: (W.MOUSEEVENTF_MIDDLEDOWN, W.MOUSEEVENTF_MIDDLEUP, 0),
    P.BOTON_X1: (W.MOUSEEVENTF_XDOWN, W.MOUSEEVENTF_XUP, W.XBUTTON1),
    P.BOTON_X2: (W.MOUSEEVENTF_XDOWN, W.MOUSEEVENTF_XUP, W.XBUTTON2),
}


def a_coordenada_normalizada(pixel, origen, tamanio):
    """Convierte un píxel a la escala 0..65535 que usa SendInput.

    Redondea hacia arriba para caer exactamente en el píxel pedido: Windows
    hace la cuenta inversa redondeando hacia abajo.
    """
    return ((pixel - origen) * 65536 + tamanio - 1) // tamanio


class SalidaWindows:
    """Ejecuta los eventos de verdad usando SendInput."""

    def __init__(self):
        self._pantallas = W.leer_pantallas()
        # Se reutiliza la misma estructura para no crear una por cada movimiento.
        self._entrada_mover = W.INPUT(type=W.INPUT_MOUSE)
        self._mi = self._entrada_mover.mi
        self._mi.dwFlags = (
            W.MOUSEEVENTF_MOVE | W.MOUSEEVENTF_ABSOLUTE | W.MOUSEEVENTF_VIRTUALDESK
        )
        self._puntero_mover = ctypes.byref(self._entrada_mover)

    def pantallas(self):
        self._pantallas = W.leer_pantallas()
        return self._pantallas

    def posicion_real(self):
        return W.posicion_cursor()

    def mover_a(self, x, y):
        # Posición absoluta, no relativa: a un movimiento relativo inyectado Windows
        # le volvería a aplicar la velocidad y aceleración de ESTA PC, y el mouse
        # se sentiría distinto al de la PC principal.
        p = self._pantallas
        self._mi.dx = a_coordenada_normalizada(x, p.izq, p.ancho)
        self._mi.dy = a_coordenada_normalizada(y, p.arriba, p.alto)
        W.user32.SendInput(1, self._puntero_mover, W.TAMANIO_INPUT)

    def boton(self, codigo, apretado):
        datos = _BOTONES.get(codigo)
        if datos is None:
            return
        entrada = W.INPUT(type=W.INPUT_MOUSE)
        entrada.mi.dwFlags = datos[0] if apretado else datos[1]
        entrada.mi.mouseData = datos[2]
        W.user32.SendInput(1, ctypes.byref(entrada), W.TAMANIO_INPUT)

    def rueda(self, delta, horizontal):
        entrada = W.INPUT(type=W.INPUT_MOUSE)
        entrada.mi.dwFlags = W.MOUSEEVENTF_HWHEEL if horizontal else W.MOUSEEVENTF_WHEEL
        entrada.mi.mouseData = delta & 0xFFFFFFFF
        W.user32.SendInput(1, ctypes.byref(entrada), W.TAMANIO_INPUT)

    def tecla(self, vk, escaneo, banderas):
        W.enviar_tecla(
            vk, escaneo, bool(banderas & P.TECLA_EXTENDIDA), bool(banderas & P.TECLA_SOLTADA)
        )


class SalidaSimulada:
    """No toca nada: muestra por consola lo que haría. Se usa en el modo de prueba."""

    def __init__(self, monitores=None, mostrar=True):
        self._pantallas = Pantallas(monitores or [Monitor(0, 0, 1920, 1080)])
        self._mostrar = mostrar
        self.x = 0
        self.y = 0
        self._t_aviso = 0.0

    def pantallas(self):
        return self._pantallas

    def posicion_real(self):
        return self.x, self.y

    def mover_a(self, x, y):
        self.x, self.y = x, y
        ahora = time.perf_counter()
        if self._mostrar and ahora - self._t_aviso > 0.5:
            self._t_aviso = ahora
            log(f"   [simulado] cursor en ({x}, {y})")

    def boton(self, codigo, apretado):
        if self._mostrar:
            log(f"   [simulado] botón {codigo} {'apretado' if apretado else 'soltado'}")

    def rueda(self, delta, horizontal):
        if self._mostrar:
            log(f"   [simulado] rueda {'horizontal ' if horizontal else ''}{delta}")

    def tecla(self, vk, escaneo, banderas):
        if self._mostrar:
            estado = "soltada" if banderas & P.TECLA_SOLTADA else "apretada"
            log(f"   [simulado] tecla vk={vk} escaneo={escaneo} {estado}")
