"""Las decisiones del cliente: dónde está el cursor y cuándo devolver el control.

El cliente es quien detecta el borde de regreso porque es el único que conoce con
exactitud sus pantallas. El servidor solo manda cuánto se movió el mouse.
"""

from time import perf_counter

from ..red import protocolo as P

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
        # Primero se saca la ventanita que esconde el cursor: si no, los clicks
        # que lleguen caerían sobre ella.
        self.salida.mostrar_cursor()
        self.x, self.y = pantallas.punto_en_borde(self.lado, ratio)
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
        pantallas = self.pantallas
        if (
            pantallas.sale_por(self.lado, nueva_x, nueva_y)
            and not self.botones
            and ahora >= self.no_volver_hasta
        ):
            ratio = pantallas.ratio_en_borde(self.lado, nueva_x, nueva_y)
            self.soltar_todo()
            self.activo = False
            self.enviar(P.volver(ratio))
            # El cursor queda quieto en el borde: se esconde, como en la PC principal.
            self.salida.esconder_cursor(self.x, self.y)
            return
        self.x, self.y = pantallas.limitar(nueva_x, nueva_y)
        self.salida.mover_a(self.x, self.y)

    def actualizar_pantallas(self):
        """Vuelve a leer los monitores. Devuelve True si cambiaron.

        Un juego en pantalla completa puede cambiar la resolución. Con las medidas
        viejas, el cursor no llegaría a todos lados ni encontraría el borde de regreso.
        """
        nuevas = self.salida.pantallas()
        if nuevas.como_lista() == self.pantallas.como_lista():
            return False
        self.pantallas = nuevas
        if self.activo:
            # Windows ya acomodó el cursor en la pantalla nueva: se parte de ahí.
            self.x, self.y = nuevas.limitar(*self.salida.posicion_real())
        return True

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
        """El servidor recuperó el control (atajo de emergencia o pausa)."""
        estaba_activo = self.activo
        self.soltar_todo()
        self.activo = False
        if estaba_activo:
            self.salida.esconder_cursor(self.x, self.y)

    def terminar(self):
        """Se cortó la conexión: se suelta todo y el cursor vuelve a verse."""
        self.soltar_todo()
        self.activo = False
        self.salida.mostrar_cursor()

    def soltar_todo(self):
        """Suelta todo lo apretado. Sin esto podría quedar una tecla trabada."""
        for codigo in tuple(self.botones):
            self.salida.boton(codigo, False)
        self.botones.clear()
        for vk, (escaneo, banderas) in tuple(self.teclas.items()):
            self.salida.tecla(vk, escaneo, banderas | P.TECLA_SOLTADA)
        self.teclas.clear()
