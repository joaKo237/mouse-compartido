"""Pruebas de lo que toca Windows: inicio automático, cursor invisible y firewall.

El firewall nunca se toca de verdad: se reemplaza netsh por una función que anota.
"""

import ctypes
import sys
import unittest
import xml.etree.ElementTree as ET
from ctypes import wintypes as wt

from mouse_compartido.sistema.autoinicio import xml_tarea

_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class TareaInicioTest(unittest.TestCase):
    def _armar(self, **cambios):
        datos = dict(programa=r"C:\Python\pythonw.exe",
                     argumentos=[r"C:\Mis cosas\mouse & teclado\main.py", "--bandeja"],
                     carpeta=r"C:\Mis cosas\mouse & teclado", usuario="PC\\Joa")
        datos.update(cambios)
        texto = xml_tarea(**datos)
        # La primera línea declara UTF-16 (así lo guarda el programa); acá se lee como texto.
        return ET.fromstring(texto.split("\n", 1)[1])

    def _valor(self, raiz, ruta):
        return raiz.find(ruta, _NS).text

    def test_no_la_frena_la_bateria_ni_el_tiempo(self):
        raiz = self._armar()
        self.assertEqual(self._valor(raiz, "t:Settings/t:DisallowStartIfOnBatteries"), "false")
        self.assertEqual(self._valor(raiz, "t:Settings/t:StopIfGoingOnBatteries"), "false")
        self.assertEqual(self._valor(raiz, "t:Settings/t:ExecutionTimeLimit"), "PT0S")
        self.assertEqual(self._valor(raiz, "t:Settings/t:Priority"), "4")

    def test_arranca_al_iniciar_sesion_del_usuario(self):
        raiz = self._armar()
        self.assertEqual(self._valor(raiz, "t:Triggers/t:LogonTrigger/t:UserId"), "PC\\Joa")
        self.assertEqual(self._valor(raiz, "t:Principals/t:Principal/t:RunLevel"), "HighestAvailable")
        sin_admin = self._armar(elevada=False)
        self.assertEqual(self._valor(sin_admin, "t:Principals/t:Principal/t:RunLevel"),
                         "LeastPrivilege")

    def test_rutas_con_espacios_y_simbolos(self):
        raiz = self._armar()
        self.assertEqual(self._valor(raiz, "t:Actions/t:Exec/t:Arguments"),
                         '"C:\\Mis cosas\\mouse & teclado\\main.py" --bandeja')
        self.assertEqual(self._valor(raiz, "t:Actions/t:Exec/t:WorkingDirectory"),
                         r"C:\Mis cosas\mouse & teclado")


@unittest.skipUnless(sys.platform == "win32", "Solo en Windows")
class FirewallTest(unittest.TestCase):
    """Sin tocar el firewall real: `_correr` se reemplaza por uno que anota los comandos."""

    def setUp(self):
        from mouse_compartido.sistema import firewall

        self.firewall = firewall
        self.comandos = []
        self.salida_show = ""
        self.addCleanup(setattr, firewall, "_correr", firewall._correr)
        self.addCleanup(setattr, firewall.W, "es_administrador", firewall.W.es_administrador)

        def correr_falso(argumentos, timeout=30):
            self.comandos.append(argumentos)
            if "show" in argumentos:
                return (0, self.salida_show) if self.salida_show else (1, "Ninguna regla")
            return 0, "Aceptar."

        firewall._correr = correr_falso

    def test_sin_permisos_no_hace_nada(self):
        self.firewall.W.es_administrador = lambda: False
        self.assertEqual(self.firewall.asegurar(24850), (False, "sin permisos"))
        self.assertEqual(self.comandos, [])

    def test_crea_las_reglas_solo_para_la_red_local(self):
        self.firewall.W.es_administrador = lambda: True
        self.assertEqual(self.firewall.asegurar(24850), (True, ""))
        agregadas = [c for c in self.comandos if "add" in c]
        self.assertEqual(len(agregadas), 2)
        tcp, udp = agregadas
        self.assertIn("localport=24850-24851", tcp)
        self.assertIn("protocol=TCP", tcp)
        self.assertIn("localport=24851", udp)
        self.assertIn("protocol=UDP", udp)
        for regla in agregadas:
            self.assertIn("remoteip=localsubnet", regla)
            self.assertIn("action=allow", regla)

    def test_si_ya_estan_no_las_toca(self):
        self.firewall.W.es_administrador = lambda: True
        # La salida de netsh viene en el idioma de Windows: solo importa el puerto.
        self.salida_show = "\n".join(["Nombre de regla:  Mouse Compartido",
                                      "PuertoLocal:   24850-24851", "PuertoLocal:   24851"])
        self.assertEqual(self.firewall.asegurar(24850), (False, ""))
        self.assertFalse(any("add" in c or "delete" in c for c in self.comandos))


class CursorInvisibleTest(unittest.TestCase):
    """El error viejo: al arrancar por segunda vez, la flechita ya no se escondía."""

    def test_el_cursor_vacio_sobrevive_a_varios_arranques(self):
        from mouse_compartido.entrada.cursor import HiloCursorEscondido, VentanaCursorInvisible

        for _ in range(3):  # Arrancar y parar varias veces, como desde el menú.
            hilo = HiloCursorEscondido()
            hilo.iniciar()
            self.assertIsNotNone(hilo._ventana)
            hilo.detener()
            self.assertFalse(hilo.is_alive())

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32")
        user32.GetClassLongPtrW.restype = ctypes.c_void_p
        user32.GetClassLongPtrW.argtypes = [wt.HWND, ctypes.c_int]

        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                        ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]

        user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(ICONINFO)]
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]

        ventana = VentanaCursorInvisible()
        try:
            cursor = user32.GetClassLongPtrW(ventana._hwnd, -12)  # GCLP_HCURSOR
            self.assertTrue(cursor, "La clase quedó sin cursor")
            info = ICONINFO()
            self.assertTrue(user32.GetIconInfo(cursor, ctypes.byref(info)),
                            "El cursor de la clase ya no es válido (lo destruyeron)")
            for mapa in (info.hbmMask, info.hbmColor):
                if mapa:
                    gdi32.DeleteObject(mapa)
        finally:
            ventana.destruir()


if __name__ == "__main__":
    unittest.main()
