"""Cómo se simulan las teclas en la otra PC, y qué pasa si un juego cambia la resolución."""

import sys
import unittest

from mouse_compartido.comun.pantallas import IZQUIERDA, Monitor, Pantallas
from mouse_compartido.entrada.logica_cliente import LogicaCliente
from mouse_compartido.sistema import win32 as W
from tests.test_logica import Reloj, SalidaFalsa

ESCANEO = W.KEYEVENTF_SCANCODE
EXTENDIDA = W.KEYEVENTF_EXTENDEDKEY
SOLTADA = W.KEYEVENTF_KEYUP


def existen_todas(_escaneo, _extendida):
    return True


class ArmarTeclaTest(unittest.TestCase):
    def test_letra_por_codigo_de_escaneo(self):
        self.assertEqual(W.armar_tecla(0x41, 0x1E, False, False, existen_todas), (0, 0x1E, ESCANEO))
        self.assertEqual(W.armar_tecla(0x41, 0x1E, False, True, existen_todas),
                         (0, 0x1E, ESCANEO | SOLTADA))

    def test_shift_derecho_sin_la_marca_falsa_de_extendida(self):
        # Así llega desde el gancho de Windows: con la marca de extendida.
        self.assertEqual(W.armar_tecla(W.VK_RSHIFT, 0x36, True, False, existen_todas),
                         (0, 0x36, ESCANEO))

    def test_las_extendidas_de_verdad_conservan_la_marca(self):
        self.assertEqual(W.armar_tecla(W.VK_RCONTROL, 0x1D, True, False, existen_todas),
                         (0, 0x1D, ESCANEO | EXTENDIDA))

    def test_si_el_teclado_no_tiene_esa_tecla_va_por_nombre(self):
        ninguna = lambda _e, _x: False
        self.assertEqual(W.armar_tecla(0x41, 0x1E, True, False, ninguna), (0x41, 0, EXTENDIDA))

    def test_teclas_especiales_por_nombre(self):
        self.assertEqual(W.armar_tecla(W.VK_NUMLOCK, 0x45, True, False, existen_todas)[:2],
                         (W.VK_NUMLOCK, 0))
        self.assertEqual(W.armar_tecla(0xAF, 0x30, True, False, existen_todas)[:2], (0xAF, 0))
        self.assertEqual(W.armar_tecla(0x41, 0, False, False, existen_todas)[:2], (0x41, 0))

    @unittest.skipUnless(sys.platform == "win32", "Solo en Windows")
    def test_con_el_teclado_real_de_esta_pc(self):
        self.assertEqual(W.armar_tecla(W.VK_RSHIFT, 0x36, True, False), (0, 0x36, ESCANEO))
        self.assertEqual(W.armar_tecla(0x26, 0x48, True, False), (0, 0x48, ESCANEO | EXTENDIDA))
        # "A" con una marca de extendida que no corresponde: no existe, va por nombre.
        self.assertEqual(W.armar_tecla(0x41, 0x1E, True, False)[:2], (0x41, 0))


class SalidaQueCambia(SalidaFalsa):
    def cambiar(self, monitores, cursor):
        self._p = Pantallas(monitores)
        self.posiciones.append(cursor)  # Windows mueve el cursor a la pantalla nueva.


class ResolucionQueCambiaTest(unittest.TestCase):
    def setUp(self):
        self.salida = SalidaQueCambia([Monitor(0, 0, 1366, 768)])
        self.enviados = []
        self.reloj = Reloj()
        self.logica = LogicaCliente(self.salida, IZQUIERDA, self.enviados.append,
                                    reloj=self.reloj)
        self.logica.entrar(32768)
        self.reloj.t += 1.0

    def test_sin_cambios_no_hace_nada(self):
        self.assertFalse(self.logica.actualizar_pantallas())

    def test_un_juego_baja_la_resolucion(self):
        self.salida.cambiar([Monitor(0, 0, 800, 600)], (400, 300))
        self.assertTrue(self.logica.actualizar_pantallas())
        self.assertEqual((self.logica.x, self.logica.y), (400, 300))
        # El cursor llega a la esquina de la pantalla nueva, no a la vieja de 1366.
        self.reloj.t += 0.01
        self.logica.mover(1000, 1000)
        self.assertEqual(self.salida.posiciones[-1], (799, 599))
        # Y el borde de regreso funciona con la medida nueva.
        self.reloj.t += 0.01
        self.logica.mover(-900, -300)
        self.assertFalse(self.logica.activo)
        self.assertEqual(len(self.enviados), 1)


if __name__ == "__main__":
    unittest.main()
