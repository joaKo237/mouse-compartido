"""Captura del mouse y teclado físicos con ganchos de bajo nivel de Windows.

Un gancho (WH_MOUSE_LL / WH_KEYBOARD_LL) le da al programa cada evento ANTES de
que llegue al resto del sistema. Si el gancho devuelve 1, el evento desaparece:
así se bloquea la entrada local mientras se controla la otra PC.

Los ganchos corren dentro del bucle de mensajes de este hilo, y por eso todas las
decisiones sobre el cursor ocurren en un solo lugar y sin carreras entre hilos.
"""

import ctypes
import threading
import time
from ctypes import wintypes as wt

from . import protocolo as P
from . import win32 as W
from .logica_captura import (
    LogicaCaptura,
    PEDIDO_CONECTADO,
    PEDIDO_DESCONECTADO,
    PEDIDO_ESTACIONAR,
    PEDIDO_RESTAURAR,
    PEDIDO_VOLVER,
)
from .registro import log

_TAM_VENTANA = 64
_INTERVALO_TIC_MS = 10
_TICS_POR_VIGILANCIA = 50  # 50 tics de 10 ms = medio segundo.
_TOLERANCIA_CURSOR_PX = 3


class VentanaCursorInvisible:
    """Ventanita casi transparente con cursor vacío, para esconder la flechita local.

    Es más segura que cambiar los cursores del sistema: si el programa se cierra
    de golpe, la ventana desaparece sola y el cursor vuelve a verse.
    """

    def __init__(self):
        instancia = W.kernel32.GetModuleHandleW(None)
        self._cursor = W.user32.CreateCursor(
            instancia, 0, 0, 32, 32, b"\xff" * (32 * 4), b"\x00" * (32 * 4)
        )
        clase = W.WNDCLASSW()
        clase.lpfnWndProc = ctypes.cast(W.user32.DefWindowProcW, W.WNDPROC)
        clase.hInstance = instancia
        clase.hCursor = self._cursor
        clase.lpszClassName = "MouseCompartidoCursorInvisible"
        W.user32.RegisterClassW(ctypes.byref(clase))
        self._hwnd = W.user32.CreateWindowExW(
            W.WS_EX_TOPMOST | W.WS_EX_TOOLWINDOW | W.WS_EX_NOACTIVATE | W.WS_EX_LAYERED,
            clase.lpszClassName,
            "",
            W.WS_POPUP,
            0, 0, _TAM_VENTANA, _TAM_VENTANA,
            None, None, instancia, None,
        )
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        # Alfa 1 de 255: a la vista no existe, pero sigue recibiendo el cursor.
        W.user32.SetLayeredWindowAttributes(self._hwnd, 0, 1, W.LWA_ALPHA)

    def mostrar(self, x, y):
        mitad = _TAM_VENTANA // 2
        W.user32.SetWindowPos(
            self._hwnd, W.HWND_TOPMOST, x - mitad, y - mitad, _TAM_VENTANA, _TAM_VENTANA,
            W.SWP_NOACTIVATE | W.SWP_SHOWWINDOW,
        )

    def ocultar(self):
        W.user32.ShowWindow(self._hwnd, W.SW_HIDE)

    def destruir(self):
        W.user32.DestroyWindow(self._hwnd)
        W.user32.DestroyCursor(self._cursor)


class HiloCaptura(threading.Thread):
    def __init__(self, config, limite_remoto_s=None):
        super().__init__(name="captura", daemon=True)
        self.logica = LogicaCaptura(config, W.leer_pantallas(), self._enviar, self._pedir)
        self._limite_remoto_s = limite_remoto_s  # Solo se usa en el modo de prueba.
        self._conexion = None
        self._conexion_nueva = None
        self._id_hilo = None
        self._listo = threading.Event()
        self._gancho_mouse = None
        self._gancho_teclado = None
        # Hay que conservar estas referencias o Python las borraría y Windows
        # llamaría a memoria inválida.
        self._proc_mouse = W.HOOKPROC(self._al_evento_mouse)
        self._proc_teclado = W.HOOKPROC(self._al_evento_teclado)
        self._ventana = None
        self._temporizador = None
        self._tics = 0
        self._t_remoto = 0.0

    # ---- Lo que usa el hilo de red ------------------------------------------------
    def iniciar(self):
        self.start()
        self._listo.wait()

    def detener(self):
        if self._id_hilo is not None:
            W.user32.PostThreadMessageW(self._id_hilo, W.WM_QUIT, 0, 0)
            self.join(timeout=2)

    def conectar(self, conexion):
        # Se aplica dentro del bucle, para respetar el orden con una desconexión previa.
        self._conexion_nueva = conexion
        self._pedir(PEDIDO_CONECTADO)

    def desconectar(self):
        self._pedir(PEDIDO_DESCONECTADO)

    def pedir_volver(self, ratio):
        self._pedir(PEDIDO_VOLVER, ratio)

    def actualizar_pantallas(self):
        """Vuelve a leer los monitores, por si conectaste o sacaste alguno."""
        self.logica.pantallas = W.leer_pantallas()

    # ---- Comunicación interna -----------------------------------------------------
    def _enviar(self, datos):
        conexion = self._conexion
        if conexion is not None:
            conexion.enviar(datos)

    def _pedir(self, codigo, valor=0):
        W.user32.PostThreadMessageW(self._id_hilo, W.WM_APP + codigo, valor, 0)

    # ---- Ganchos ------------------------------------------------------------------
    def _al_evento_mouse(self, codigo, wparam, lparam):
        if codigo == W.HC_ACTION:
            try:
                evento = W.MSLLHOOKSTRUCT.from_address(lparam)
                if self.logica.al_mouse(
                    wparam, evento.pt.x, evento.pt.y, evento.mouseData,
                    evento.flags & W.LLMHF_INJECTED,
                ):
                    return 1
            except Exception as error:  # Un error acá nunca debe trabar el mouse.
                log(f"Error procesando el mouse: {error!r}")
        return W.user32.CallNextHookEx(None, codigo, wparam, lparam)

    def _al_evento_teclado(self, codigo, wparam, lparam):
        if codigo == W.HC_ACTION:
            try:
                evento = W.KBDLLHOOKSTRUCT.from_address(lparam)
                if self.logica.al_teclado(wparam, evento.vkCode, evento.scanCode, evento.flags):
                    return 1
            except Exception as error:
                log(f"Error procesando el teclado: {error!r}")
        return W.user32.CallNextHookEx(None, codigo, wparam, lparam)

    def _poner_ganchos(self):
        instancia = W.kernel32.GetModuleHandleW(None)
        self._gancho_mouse = W.user32.SetWindowsHookExW(W.WH_MOUSE_LL, self._proc_mouse, instancia, 0)
        self._gancho_teclado = W.user32.SetWindowsHookExW(
            W.WH_KEYBOARD_LL, self._proc_teclado, instancia, 0
        )
        if not self._gancho_mouse or not self._gancho_teclado:
            log(f"ERROR: no se pudieron instalar los ganchos ({ctypes.get_last_error()})")

    def _quitar_ganchos(self):
        for gancho in (self._gancho_mouse, self._gancho_teclado):
            if gancho:
                W.user32.UnhookWindowsHookEx(gancho)
        self._gancho_mouse = self._gancho_teclado = None

    # ---- Bucle de mensajes --------------------------------------------------------
    def run(self):
        self._id_hilo = W.kernel32.GetCurrentThreadId()
        mensaje = wt.MSG()
        puntero = ctypes.byref(mensaje)
        W.user32.PeekMessageW(puntero, None, 0, 0, W.PM_NOREMOVE)  # Crea la cola del hilo.
        try:
            self._ventana = VentanaCursorInvisible()
        except OSError as error:
            log(f"Aviso: no se podrá esconder el cursor local ({error}).")
        self._listo.set()

        while W.user32.GetMessageW(puntero, None, 0, 0) > 0:
            tipo = mensaje.message
            if tipo == W.WM_TIMER and not mensaje.hWnd:
                self._tic()
            elif W.WM_APP < tipo < W.WM_APP + 16:
                self._atender_pedido(tipo - W.WM_APP, mensaje.wParam)
            else:
                W.user32.TranslateMessage(puntero)
                W.user32.DispatchMessageW(puntero)

        self._parar_temporizador()
        self._quitar_ganchos()
        if self._ventana:
            self._ventana.destruir()

    def _atender_pedido(self, codigo, valor):
        logica = self.logica
        if codigo == PEDIDO_CONECTADO:
            self._conexion = self._conexion_nueva
            logica.conectado = True
            self._poner_ganchos()
        elif codigo == PEDIDO_DESCONECTADO:
            if logica.al_desconectar():
                self._liberar_cursor(None)
                log("Se cortó la conexión: el control volvió a esta PC.")
            self._quitar_ganchos()
            self._conexion = None
        elif codigo == PEDIDO_ESTACIONAR:
            self._estacionar_cursor()
        elif codigo == PEDIDO_VOLVER:
            destino = logica.al_volver(valor)
            if destino is not None:
                self._liberar_cursor(destino)
                log("<- Control en esta PC.")
        elif codigo == PEDIDO_RESTAURAR:
            self._liberar_cursor(None)
            log("<- Control devuelto a esta PC.")

    def _estacionar_cursor(self):
        """Deja el cursor local escondido y quieto en el centro del monitor."""
        logica = self.logica
        if not logica.remoto:
            return
        monitor = logica.pantallas.monitor_de(logica.ref_x, logica.ref_y)
        x, y = monitor.centro
        if self._ventana:
            self._ventana.mostrar(x, y)
        # La referencia se actualiza antes de mover: un evento que llegue en medio
        # queda descartado por el filtro de saltos de la lógica.
        logica.al_estacionar(x, y, min(monitor.ancho, monitor.alto) // 4)
        W.user32.SetCursorPos(x, y)
        # Lo que estaba apretado acá se suelta acá (y sigue apretado en la otra PC).
        for vk, (escaneo, banderas) in logica.tomar_teclas_locales():
            W.enviar_tecla(vk, escaneo, bool(banderas & P.TECLA_EXTENDIDA), True)
        self._temporizador = W.user32.SetTimer(None, 0, _INTERVALO_TIC_MS, None)
        self._tics = 0
        self._t_remoto = time.perf_counter()
        log("-> Control en la otra PC. Emergencia: Ctrl+Alt+Esc")

    def _liberar_cursor(self, destino):
        self._parar_temporizador()
        if destino is not None:
            W.user32.SetCursorPos(*destino)
        if self._ventana:
            self._ventana.ocultar()

    def _parar_temporizador(self):
        if self._temporizador:
            W.user32.KillTimer(None, self._temporizador)
            self._temporizador = None

    def _tic(self):
        """Corre cada 10 ms mientras se controla la otra PC."""
        logica = self.logica
        logica.vaciar_movimiento()  # El último tramo de un movimiento no queda colgado.
        conexion = self._conexion
        if conexion is not None:
            conexion.vaciar()
        self._tics += 1
        if self._tics < _TICS_POR_VIGILANCIA:
            return
        self._tics = 0
        self._vigilar_gancho()
        if (
            self._limite_remoto_s is not None
            and logica.remoto
            and time.perf_counter() - self._t_remoto > self._limite_remoto_s
        ):
            log("Modo prueba: se acabó el tiempo, devolviendo el control.")
            logica.forzar_local()

    def _vigilar_gancho(self):
        """Si el cursor se movió estando estacionado, Windows nos quitó el gancho.

        Windows lo hace en silencio si el programa tardó demasiado en responder
        (por ejemplo, al volver de una suspensión). Lo reinstalamos y seguimos.
        """
        logica = self.logica
        if not logica.remoto:
            return
        x, y = W.posicion_cursor()
        if (
            abs(x - logica.ref_x) > _TOLERANCIA_CURSOR_PX
            or abs(y - logica.ref_y) > _TOLERANCIA_CURSOR_PX
        ):
            log("Aviso: Windows quitó el gancho; reinstalándolo.")
            self._quitar_ganchos()
            self._poner_ganchos()
            W.user32.SetCursorPos(logica.ref_x, logica.ref_y)
