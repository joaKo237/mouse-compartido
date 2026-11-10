"""Las decisiones del servidor: qué hacer con cada evento de mouse y teclado.

Está separada de la parte de Windows (captura.py) para poder probarla con eventos
inventados. Todo corre en el hilo de los ganchos, así que no hacen falta candados.
Regla de oro: cada evento se resuelve en microsegundos y sin esperar a nadie.
"""

from time import perf_counter

from ..red import protocolo as P
from ..sistema import win32 as W

# Pedidos al bucle de mensajes: las llamadas a Windows que mueven cosas se hacen
# ahí y no dentro del gancho, para no anidar eventos.
PEDIDO_CONECTADO = 1
PEDIDO_DESCONECTADO = 2
PEDIDO_ESTACIONAR = 3
PEDIDO_VOLVER = 4
PEDIDO_RESTAURAR = 5
PEDIDO_PAUSA = 6

_CTRL = {W.VK_LCONTROL, W.VK_RCONTROL}
_ALT = {W.VK_LMENU, W.VK_RMENU}
_MODIFICADORES = _CTRL | _ALT

# Mensaje de Windows -> (código del botón, apretado).
_BOTONES = {
    W.WM_LBUTTONDOWN: (P.BOTON_IZQUIERDO, True),
    W.WM_LBUTTONUP: (P.BOTON_IZQUIERDO, False),
    W.WM_RBUTTONDOWN: (P.BOTON_DERECHO, True),
    W.WM_RBUTTONUP: (P.BOTON_DERECHO, False),
    W.WM_MBUTTONDOWN: (P.BOTON_MEDIO, True),
    W.WM_MBUTTONUP: (P.BOTON_MEDIO, False),
}

# Tras esconder el cursor pueden llegar eventos calculados desde la posición vieja.
_VENTANA_ESTACIONADO_S = 0.1


def _descifrar_boton(mensaje, dato):
    """Devuelve (código, apretado) o None si el mensaje no es de un botón."""
    resultado = _BOTONES.get(mensaje)
    if resultado is not None:
        return resultado
    if mensaje in (W.WM_XBUTTONDOWN, W.WM_XBUTTONUP):
        codigo = P.BOTON_X1 if (dato >> 16) & 0xFFFF == W.XBUTTON1 else P.BOTON_X2
        return codigo, mensaje == W.WM_XBUTTONDOWN
    return None


def _rueda_con_signo(dato):
    delta = (dato >> 16) & 0xFFFF
    return delta - 0x10000 if delta >= 0x8000 else delta


class LogicaCaptura:
    def __init__(self, config, pantallas, enviar, pedir, reloj=perf_counter):
        self.pantallas = pantallas
        self.lado = config.lado_otra_pantalla
        self.margen_esquinas = config.esquinas_muertas_px
        hz = config.max_envios_mouse_hz
        self.intervalo_envio = 1.0 / hz if hz > 0 else 0.0
        self.enfriamiento = config.enfriamiento_ms / 1000.0
        self.enviar = enviar
        self.pedir = pedir
        self.reloj = reloj

        self.conectado = False
        self.remoto = False  # True mientras se controla la otra PC.
        # Pausa: la conexión sigue, pero no se pasa a la otra PC. Puede pedirla
        # esta PC (desde la bandeja) o la otra (y llega por la red).
        self.pausa_local = False
        self.pausa_remota = False
        self.pausado = False
        self.ref_x = 0  # Punto contra el que se miden los movimientos.
        self.ref_y = 0
        self.acumulado_x = 0
        self.acumulado_y = 0
        self.t_ultimo_envio = 0.0
        self.t_estacionado = 0.0
        self.umbral_salto = 1 << 30
        self.no_cruzar_hasta = 0.0
        self.botones_locales = set()
        self.teclas_locales = {}  # vk -> (escaneo, banderas)
        self.modificadores = set()

    # ---- Mouse ----------------------------------------------------------------
    def al_mouse(self, mensaje, x, y, dato, inyectado):
        """Devuelve True si el evento debe bloquearse en esta PC."""
        if inyectado:
            return False  # No es del mouse físico.
        if self.remoto:
            return self._mouse_remoto(mensaje, x, y, dato)
        return self._mouse_local(mensaje, x, y, dato)

    def _mouse_local(self, mensaje, x, y, dato):
        if mensaje == W.WM_MOUSEMOVE:
            # No se cruza con un botón apretado: si estás arrastrando algo, la
            # soltada tiene que ocurrir en esta misma PC.
            if (
                self.conectado
                and not self.pausado
                and not self.botones_locales
                and self.pantallas.toca_borde(self.lado, x, y, self.margen_esquinas)
                and self.reloj() >= self.no_cruzar_hasta
            ):
                self._cruzar(x, y)
                return True
            return False
        boton = _descifrar_boton(mensaje, dato)
        if boton is not None:
            codigo, apretado = boton
            if apretado:
                self.botones_locales.add(codigo)
            else:
                self.botones_locales.discard(codigo)
        return False

    def _cruzar(self, x, y):
        self.remoto = True
        self.ref_x = x
        self.ref_y = y
        self.acumulado_x = self.acumulado_y = 0
        self.t_estacionado = 0.0
        self.enviar(P.entrar(self.pantallas.ratio_en_borde(self.lado, x, y)))
        # Las teclas que venías apretando (por ejemplo Ctrl) siguen apretadas allá.
        for vk, (escaneo, banderas) in self.teclas_locales.items():
            self.enviar(P.tecla(vk, escaneo, banderas))
        self.pedir(PEDIDO_ESTACIONAR)

    def _mouse_remoto(self, mensaje, x, y, dato):
        if mensaje == W.WM_MOUSEMOVE:
            if self.t_estacionado == 0.0:
                return True  # Es el instante del cruce: todavía no hay referencia fiable.
            # Como el evento se bloquea, el cursor real no se mueve: la diferencia
            # con el punto de referencia es exactamente el movimiento del mouse.
            dx = x - self.ref_x
            dy = y - self.ref_y
            if dx == 0 and dy == 0:
                return True
            ahora = self.reloj()
            if ahora - self.t_estacionado < _VENTANA_ESTACIONADO_S and (
                abs(dx) > self.umbral_salto or abs(dy) > self.umbral_salto
            ):
                return True  # Evento calculado antes de esconder el cursor.
            self.acumulado_x += dx
            self.acumulado_y += dy
            if ahora - self.t_ultimo_envio >= self.intervalo_envio:
                self.vaciar_movimiento(ahora)
            return True

        # Antes de un click se manda el movimiento pendiente: el orden importa.
        self.vaciar_movimiento()
        if mensaje == W.WM_MOUSEWHEEL or mensaje == W.WM_MOUSEHWHEEL:
            self.enviar(P.rueda(_rueda_con_signo(dato), mensaje == W.WM_MOUSEHWHEEL))
            return True
        boton = _descifrar_boton(mensaje, dato)
        if boton is not None:
            self.enviar(P.boton(boton[0], boton[1]))
        return True

    def vaciar_movimiento(self, ahora=None):
        """Manda el movimiento acumulado, si lo hay."""
        if self.acumulado_x or self.acumulado_y:
            self.enviar(P.mover(self.acumulado_x, self.acumulado_y))
            self.acumulado_x = self.acumulado_y = 0
            self.t_ultimo_envio = self.reloj() if ahora is None else ahora

    # ---- Teclado --------------------------------------------------------------
    def al_teclado(self, mensaje, vk, escaneo, banderas_windows):
        """Devuelve True si la tecla debe bloquearse en esta PC."""
        if banderas_windows & W.LLKHF_INJECTED:
            return False
        ctrl_falso = bool(escaneo & W.ESCANEO_CTRL_FALSO)
        soltada = bool(banderas_windows & W.LLKHF_UP)

        # Hay que llevar la cuenta propia de modificadores: las teclas bloqueadas
        # no le llegan al sistema, así que Windows no sabría que están apretadas.
        if vk in _MODIFICADORES and not ctrl_falso:
            if soltada:
                self.modificadores.discard(vk)
            else:
                self.modificadores.add(vk)

        banderas = (P.TECLA_SOLTADA if soltada else 0) | (
            P.TECLA_EXTENDIDA if banderas_windows & W.LLKHF_EXTENDED else 0
        )

        if not self.remoto:
            if not ctrl_falso:
                if soltada:
                    self.teclas_locales.pop(vk, None)
                else:
                    self.teclas_locales[vk] = (escaneo & 0xFF, banderas)
            return False

        # El atajo de emergencia se revisa antes que todo y no depende de la red.
        if vk == W.VK_ESCAPE and not soltada and self._atajo_emergencia():
            self.forzar_local()
            return True
        if ctrl_falso:
            return True  # El Windows de destino genera su propio Ctrl falso con AltGr.
        self.vaciar_movimiento()
        self.enviar(P.tecla(vk, escaneo & 0xFF, banderas))
        return True

    def _atajo_emergencia(self):
        return bool(self.modificadores & _CTRL) and bool(self.modificadores & _ALT)

    # ---- Cambios de estado ------------------------------------------------------
    def forzar_local(self):
        """Devuelve el control a esta PC sin esperar nada de la red."""
        if not self.remoto:
            return
        self.vaciar_movimiento()
        self.enviar(P.salir())
        self._dejar_remoto()
        self.pedir(PEDIDO_RESTAURAR)

    def _dejar_remoto(self):
        self.remoto = False
        self.acumulado_x = self.acumulado_y = 0
        self.teclas_locales.clear()
        self.no_cruzar_hasta = self.reloj() + self.enfriamiento

    def al_estacionar(self, x, y, umbral_salto):
        """El cursor local va a quedar quieto en (x, y) mientras dure el control remoto."""
        self.ref_x = x
        self.ref_y = y
        self.umbral_salto = umbral_salto
        self.t_estacionado = self.reloj()

    def tomar_teclas_locales(self):
        """Devuelve y olvida las teclas que hay que soltar en esta PC."""
        teclas = list(self.teclas_locales.items())
        self.teclas_locales.clear()
        return teclas

    def al_volver(self, ratio):
        """El cliente cruzó de vuelta. Devuelve dónde dejar el cursor local, o None."""
        if not self.remoto:
            return None
        self._dejar_remoto()
        return self.pantallas.punto_en_borde(self.lado, ratio)

    def pausar(self, local=None, remota=None):
        """Cambia la pausa. Se puede llamar desde cualquier hilo: solo anota.

        Si en ese momento se está controlando la otra PC, quien llama tiene que
        pedir al hilo de los ganchos que devuelva el control (ver captura.py).
        """
        if local is not None:
            self.pausa_local = bool(local)
        if remota is not None:
            self.pausa_remota = bool(remota)
        self.pausado = self.pausa_local or self.pausa_remota

    def al_desconectar(self):
        """Se cortó la conexión. Devuelve True si estaba controlando la otra PC."""
        estaba_remoto = self.remoto
        self.conectado = False
        if estaba_remoto:
            self._dejar_remoto()
        self.botones_locales.clear()
        self.pausar(remota=False)  # La pausa de la otra PC era de esa conexión.
        return estaba_remoto
