"""Las decisiones del cliente: dónde está el cursor y cuándo devolver el control.

El cliente es quien detecta el borde de regreso porque es el único que conoce con
exactitud sus pantallas. El servidor solo manda cuánto se movió el mouse.
"""

from time import perf_counter

from . import protocolo as P
from .pantallas import IZQUIERDA, MARGEN_ENTRADA

_RESINCRONIZAR_TRAS_S = 0.25


class LogicaCliente:
    def __init__(self, salida, lado_retorno, enviar, enfriamiento_s=0.2, reloj=perf_counter):
        self.salida = salida  # Quien ejecuta de verdad (Windows o el simulador).
        self.lado = lado_retorno
        self.enviar = enviar
        self.enfriamiento = enfriamiento_s
        self.reloj = reloj
        self.pantallas = salida.pantallas()
        self.activo = False
        self.x = 0
        self.y = 0
        self.t_movimiento = 0.0
        self.no_volver_hasta = 0.0
        self.botones = set()
        self.teclas = {}  # vk -> (escaneo, banderas)

    def entrar(self, ratio):
        """El cursor llega desde el servidor."""
        self.pantallas = pantallas = self.salida.pantallas()
        y = pantallas.y_desde_ratio(self.lado, ratio)
        x = (
            pantallas.izq + MARGEN_ENTRADA
            if self.lado == IZQUIERDA
            else pantallas.der - 1 - MARGEN_ENTRADA
        )
        self.x, self.y = pantallas.limitar(x, y)
        self.salida.mover_a(self.x, self.y)
        self.activo = True
        ahora = self.reloj()
        self.t_movimiento = ahora
        self.no_volver_hasta = ahora + self.enfriamiento

    def mover(self, dx, dy):
        if not self.activo:
            return
        ahora = self.reloj()
        if ahora - self.t_movimiento > _RESINCRONIZAR_TRAS_S:
            # Tras una pausa, un programa pudo haber movido el cursor por su cuenta.
            self.x, self.y = self.salida.posicion_real()
        self.t_movimiento = ahora
        nueva_x = self.x + dx
        nueva_y = self.y + dy
        if self._cruza_borde(nueva_x) and not self.botones and ahora >= self.no_volver_hasta:
            ratio = self.pantallas.ratio_en_borde(self.lado, nueva_y)
            self.soltar_todo()
            self.activo = False
            self.enviar(P.volver(ratio))
            return
        self.x, self.y = self.pantallas.limitar(nueva_x, nueva_y)
        self.salida.mover_a(self.x, self.y)

    def _cruza_borde(self, x):
        if self.lado == IZQUIERDA:
            return x < self.pantallas.izq
        return x >= self.pantallas.der

    def boton(self, codigo, apretado):
        if not self.activo:
            return
        if apretado:
            self.botones.add(codigo)
        else:
            self.botones.discard(codigo)
        self.salida.boton(codigo, apretado)

    def rueda(self, delta, horizontal):
        if self.activo:
            self.salida.rueda(delta, horizontal)

    def tecla(self, vk, escaneo, banderas):
        if not self.activo:
            return
        if banderas & P.TECLA_SOLTADA:
            self.teclas.pop(vk, None)
        else:
            self.teclas[vk] = (escaneo, banderas)
        self.salida.tecla(vk, escaneo, banderas)

    def salir(self):
        """El servidor recuperó el control."""
        self.soltar_todo()
        self.activo = False

    def soltar_todo(self):
        """Suelta todo lo apretado. Sin esto podría quedar una tecla trabada."""
        for codigo in tuple(self.botones):
            self.salida.boton(codigo, False)
        self.botones.clear()
        for vk, (escaneo, banderas) in tuple(self.teclas.items()):
            self.salida.tecla(vk, escaneo, banderas | P.TECLA_SOLTADA)
        self.teclas.clear()
