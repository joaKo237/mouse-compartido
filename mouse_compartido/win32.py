"""Declaraciones de la API de Windows, usada directamente con ctypes.

Declarar los tipos de cada función es obligatorio en 64 bits: sin eso, Python
puede recortar punteros y el programa falla de formas muy difíciles de rastrear.
"""

import ctypes
import gc
import sys
from ctypes import wintypes as wt

from .pantallas import Monitor, Pantallas

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HCURSOR = wt.HICON

# --- Ganchos -----------------------------------------------------------------
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0

WM_TIMER = 0x0113
WM_APP = 0x8000
WM_QUIT = 0x0012
PM_NOREMOVE = 0

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E

XBUTTON1 = 1
XBUTTON2 = 2

LLMHF_INJECTED = 0x01
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10
LLKHF_UP = 0x80

VK_PAUSE = 0x13
VK_ESCAPE = 0x1B
VK_NUMLOCK = 0x90
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

# Con AltGr, Windows inventa un Ctrl izquierdo falso marcado con este bit.
ESCANEO_CTRL_FALSO = 0x200


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wt.POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM
)

# --- SendInput ---------------------------------------------------------------
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _UNION_ENTRADA(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _UNION_ENTRADA)]


TAMANIO_INPUT = ctypes.sizeof(INPUT)

# --- Ventanas (para esconder el cursor local) ---------------------------------
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x02
HWND_TOPMOST = wt.HWND(-1)
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


# --- Firmas de las funciones ---------------------------------------------------
user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD)
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.UnhookWindowsHookEx.argtypes = (wt.HHOOK,)
user32.UnhookWindowsHookEx.restype = wt.BOOL
user32.CallNextHookEx.argtypes = (wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.CallNextHookEx.restype = LRESULT

user32.GetMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
user32.GetMessageW.restype = ctypes.c_int
user32.PeekMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
user32.PeekMessageW.restype = wt.BOOL
user32.TranslateMessage.argtypes = (ctypes.POINTER(wt.MSG),)
user32.TranslateMessage.restype = wt.BOOL
user32.DispatchMessageW.argtypes = (ctypes.POINTER(wt.MSG),)
user32.DispatchMessageW.restype = LRESULT
user32.PostThreadMessageW.argtypes = (wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.PostThreadMessageW.restype = wt.BOOL
user32.SetTimer.argtypes = (wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p)
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = (wt.HWND, ctypes.c_size_t)
user32.KillTimer.restype = wt.BOOL

user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.SetCursorPos.restype = wt.BOOL
user32.GetCursorPos.argtypes = (ctypes.POINTER(wt.POINT),)
user32.GetCursorPos.restype = wt.BOOL
user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT

user32.EnumDisplayMonitors.argtypes = (wt.HDC, ctypes.POINTER(wt.RECT), MONITORENUMPROC, wt.LPARAM)
user32.EnumDisplayMonitors.restype = wt.BOOL

user32.DefWindowProcW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
user32.RegisterClassW.restype = wt.ATOM
user32.CreateWindowExW.argtypes = (
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
)
user32.CreateWindowExW.restype = wt.HWND
user32.DestroyWindow.argtypes = (wt.HWND,)
user32.DestroyWindow.restype = wt.BOOL
user32.SetLayeredWindowAttributes.argtypes = (wt.HWND, wt.COLORREF, wt.BYTE, wt.DWORD)
user32.SetLayeredWindowAttributes.restype = wt.BOOL
user32.SetWindowPos.argtypes = (
    wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT
)
user32.SetWindowPos.restype = wt.BOOL
user32.ShowWindow.argtypes = (wt.HWND, ctypes.c_int)
user32.ShowWindow.restype = wt.BOOL
user32.CreateCursor.argtypes = (
    wt.HINSTANCE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_char_p, ctypes.c_char_p,
)
user32.CreateCursor.restype = HCURSOR
user32.DestroyCursor.argtypes = (HCURSOR,)
user32.DestroyCursor.restype = wt.BOOL

user32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
user32.SetProcessDpiAwarenessContext.restype = wt.BOOL
user32.SetProcessDPIAware.restype = wt.BOOL

kernel32.GetModuleHandleW.argtypes = (wt.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetCurrentThreadId.restype = wt.DWORD
kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.SetPriorityClass.argtypes = (wt.HANDLE, wt.DWORD)
kernel32.SetPriorityClass.restype = wt.BOOL
kernel32.GetStdHandle.argtypes = (wt.DWORD,)
kernel32.GetStdHandle.restype = wt.HANDLE
kernel32.GetConsoleMode.argtypes = (wt.HANDLE, ctypes.POINTER(wt.DWORD))
kernel32.GetConsoleMode.restype = wt.BOOL
kernel32.SetConsoleMode.argtypes = (wt.HANDLE, wt.DWORD)
kernel32.SetConsoleMode.restype = wt.BOOL
shell32.IsUserAnAdmin.restype = wt.BOOL


# --- Ayudantes -----------------------------------------------------------------
_DPI_POR_MONITOR_V2 = ctypes.c_void_p(-4)
_PRIORIDAD_ALTA = 0x00000080
_STD_INPUT = -10 & 0xFFFFFFFF
_QUICK_EDIT = 0x0040
_EXTENDED_FLAGS = 0x0080


def _desactivar_quick_edit():
    """Evita que seleccionar texto en la consola congele el programa."""
    entrada = kernel32.GetStdHandle(_STD_INPUT)
    modo = wt.DWORD()
    if kernel32.GetConsoleMode(entrada, ctypes.byref(modo)):
        kernel32.SetConsoleMode(entrada, (modo.value & ~_QUICK_EDIT) | _EXTENDED_FLAGS)


def preparar_proceso():
    """Ajustes generales. Se llama lo primero de todo, antes de tocar cualquier ventana."""
    # Trabajar en píxeles reales. Sin esto, con la escala en 125% o 150% (muy común
    # en notebooks) Windows le daría al programa coordenadas falseadas.
    if not user32.SetProcessDpiAwarenessContext(_DPI_POR_MONITOR_V2):
        user32.SetProcessDPIAware()
    # Que otros programas pesados no le quiten el turno.
    kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), _PRIORIDAD_ALTA)
    # Si otro hilo de Python está corriendo, ceder el turno cada 1 ms en lugar de 5 ms.
    sys.setswitchinterval(0.001)
    # Evitar pausas largas del recolector de basura.
    gc.collect()
    gc.freeze()
    gc.set_threshold(20000, 50, 50)
    _desactivar_quick_edit()


def es_administrador():
    return bool(shell32.IsUserAnAdmin())


def leer_pantallas():
    """Pregunta a Windows qué monitores hay y dónde está cada uno."""
    monitores = []

    def anotar(_monitor, _hdc, rect, _dato):
        r = rect.contents
        monitores.append(Monitor(r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(anotar), 0)
    return Pantallas(monitores)


def posicion_cursor():
    punto = wt.POINT()
    user32.GetCursorPos(ctypes.byref(punto))
    return punto.x, punto.y


def enviar_tecla(vk, escaneo, extendida, soltada):
    """Simula una tecla. Usa código de escaneo salvo en las teclas que no lo soportan bien."""
    entrada = INPUT(type=INPUT_KEYBOARD)
    banderas = 0
    if extendida:
        banderas |= KEYEVENTF_EXTENDEDKEY
    if soltada:
        banderas |= KEYEVENTF_KEYUP
    if escaneo == 0 or vk in (VK_PAUSE, VK_NUMLOCK) or 0xA6 <= vk <= 0xB7:
        # Pausa, Bloq Num, multimedia y navegador: se mandan por tecla virtual.
        entrada.ki.wVk = vk
    else:
        # El código de escaneo representa la tecla física, así que la distribución
        # de teclado de la PC de destino decide qué letra sale.
        entrada.ki.wScan = escaneo
        banderas |= KEYEVENTF_SCANCODE
    entrada.ki.dwFlags = banderas
    user32.SendInput(1, ctypes.byref(entrada), TAMANIO_INPUT)
