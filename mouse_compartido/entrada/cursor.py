"""Esconder la flechita del mouse en la PC que no se está usando.

El truco: una ventanita de 64x64 casi transparente (alfa 1 de 255) cuyo cursor
es un dibujo vacío. Mientras la flechita está encima de esa ventana, Windows
muestra el cursor de la ventana, o sea, nada. Es más seguro que cambiar los
cursores del sistema: si el programa se cierra de golpe, la ventana desaparece
sola y la flechita vuelve a verse.

Se usa en las dos PCs:
  * En la principal, mientras controlás la otra (el cursor queda quieto en el centro).
  * En la otra, cuando el control vuelve a la principal (el cursor queda quieto en el borde).
"""

import ctypes
import threading
from ctypes import wintypes as wt

from ..comun.registro import log
from ..sistema import win32 as W

_TAM_VENTANA = 64
_NOMBRE_CLASE = "MouseCompartidoCursorInvisible"

# La "clase" de ventana (y su cursor vacío) se registra UNA sola vez por proceso.
# Antes se registraba en cada arranque y se destruía el cursor al cerrar: al
# arrancar por segunda vez desde el mismo menú, la clase quedaba apuntando a un
# cursor ya destruido y la flechita dejaba de esconderse.
_candado_clase = threading.Lock()
_clase_lista = False


def _registrar_clase():
    global _clase_lista
    with _candado_clase:
        if _clase_lista:
            return
        instancia = W.kernel32.GetModuleHandleW(None)
        # Cursor de 32x32 con máscara AND toda en 1 y XOR toda en 0 = transparente.
        cursor = W.user32.CreateCursor(
            instancia, 0, 0, 32, 32, b"\xff" * (32 * 4), b"\x00" * (32 * 4)
        )
        clase = W.WNDCLASSW()
        clase.lpfnWndProc = ctypes.cast(W.user32.DefWindowProcW, W.WNDPROC)
        clase.hInstance = instancia
        clase.hCursor = cursor
        clase.lpszClassName = _NOMBRE_CLASE
        if not W.user32.RegisterClassW(ctypes.byref(clase)):
            raise ctypes.WinError(ctypes.get_last_error())
        # El cursor vive mientras viva el proceso: nunca se destruye.
        _clase_lista = True


class VentanaCursorInvisible:
    """La ventanita. Tiene que crearse y usarse desde un hilo que atienda mensajes."""

    def __init__(self):
        _registrar_clase()
        self._hwnd = W.user32.CreateWindowExW(
            W.WS_EX_TOPMOST | W.WS_EX_TOOLWINDOW | W.WS_EX_NOACTIVATE | W.WS_EX_LAYERED,
            _NOMBRE_CLASE,
            "",
            W.WS_POPUP,
            0, 0, _TAM_VENTANA, _TAM_VENTANA,
            None, None, W.kernel32.GetModuleHandleW(None), None,
        )
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        # Alfa 1 de 255: a la vista no existe, pero sigue recibiendo el cursor.
        W.user32.SetLayeredWindowAttributes(self._hwnd, 0, 1, W.LWA_ALPHA)

    def mostrar(self, x, y):
        """La ubica centrada en (x, y). Windows actualiza la flechita solo, sin moverla."""
        mitad = _TAM_VENTANA // 2
        W.user32.SetWindowPos(
            self._hwnd, W.HWND_TOPMOST, x - mitad, y - mitad, _TAM_VENTANA, _TAM_VENTANA,
            W.SWP_NOACTIVATE | W.SWP_SHOWWINDOW,
        )

    def ocultar(self):
        W.user32.ShowWindow(self._hwnd, W.SW_HIDE)

    def destruir(self):
        W.user32.DestroyWindow(self._hwnd)


# Mensajes internos del hilo del cursor escondido.
_ESCONDER = W.WM_APP + 1
_MOSTRAR = W.WM_APP + 2
_INTERVALO_REVISION_MS = 50
_TOLERANCIA_PX = 3


class HiloCursorEscondido(threading.Thread):
    """Esconde la flechita de la PC controlada cuando el control vuelve a la principal.

    Tiene su propio hilo porque la ventana necesita a alguien que atienda sus
    mensajes, y el hilo de red no puede quedarse esperando ventanas.

    Si alguien usa el mouse o touchpad propio de esta PC, la flechita se mueve,
    sale de la ventanita y vuelve a verse sola. En ese momento la ventanita se
    saca del medio para no tapar clicks.
    """

    def __init__(self):
        super().__init__(name="cursor-escondido", daemon=True)
        self._id_hilo = None
        self._listo = threading.Event()
        self._punto = (0, 0)
        self._ventana = None
        self._temporizador = None

    def iniciar(self):
        self.start()
        self._listo.wait(2)

    def detener(self):
        if self._id_hilo is not None:
            W.user32.PostThreadMessageW(self._id_hilo, W.WM_QUIT, 0, 0)
            self.join(timeout=2)

    def esconder(self, x, y):
        """Esconde la flechita, que está quieta en (x, y). No espera: solo deja el pedido."""
        self._punto = (x, y)
        if self._id_hilo is not None:
            W.user32.PostThreadMessageW(self._id_hilo, _ESCONDER, 0, 0)

    def mostrar(self):
        if self._id_hilo is not None:
            W.user32.PostThreadMessageW(self._id_hilo, _MOSTRAR, 0, 0)

    def run(self):
        self._id_hilo = W.kernel32.GetCurrentThreadId()
        mensaje = wt.MSG()
        puntero = ctypes.byref(mensaje)
        W.user32.PeekMessageW(puntero, None, 0, 0, W.PM_NOREMOVE)  # Crea la cola del hilo.
        try:
            self._ventana = VentanaCursorInvisible()
        except OSError as error:
            log(f"Aviso: no se podrá esconder el cursor en esta PC ({error}).")
        self._listo.set()

        while W.user32.GetMessageW(puntero, None, 0, 0) > 0:
            tipo = mensaje.message
            if tipo == _ESCONDER:
                self._al_esconder()
            elif tipo == _MOSTRAR:
                self._al_mostrar()
            elif tipo == W.WM_TIMER and not mensaje.hWnd:
                self._revisar()
            else:
                W.user32.TranslateMessage(puntero)
                W.user32.DispatchMessageW(puntero)

        self._parar_revision()
        if self._ventana:
            self._ventana.destruir()

    def _al_esconder(self):
        if not self._ventana:
            return
        x, y = self._punto
        self._ventana.mostrar(x, y)
        if not self._temporizador:
            self._temporizador = W.user32.SetTimer(None, 0, _INTERVALO_REVISION_MS, None)

    def _al_mostrar(self):
        self._parar_revision()
        if self._ventana:
            self._ventana.ocultar()

    def _revisar(self):
        """Si la flechita se movió por su cuenta (touchpad de esta PC), se deja ver."""
        x, y = W.posicion_cursor()
        px, py = self._punto
        if abs(x - px) > _TOLERANCIA_PX or abs(y - py) > _TOLERANCIA_PX:
            self._al_mostrar()

    def _parar_revision(self):
        if self._temporizador:
            W.user32.KillTimer(None, self._temporizador)
            self._temporizador = None
