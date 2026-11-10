"""Pruebas de las decisiones de servidor y cliente, con eventos inventados."""

import unittest

from mouse_compartido import protocolo as P
from mouse_compartido import win32 as W
from mouse_compartido.config import Config
from mouse_compartido.inyeccion import a_coordenada_normalizada
from mouse_compartido.logica_captura import (
    LogicaCaptura,
    PEDIDO_ESTACIONAR,
    PEDIDO_RESTAURAR,
)
from mouse_compartido.logica_cliente import LogicaCliente
from mouse_compartido.pantallas import DERECHA, IZQUIERDA, Monitor, Pantallas

FHD = Pantallas([Monitor(0, 0, 1920, 1080)])
MOVER = W.WM_MOUSEMOVE
VK_LSHIFT = 0xA0
BAJA = 0
SUBE = W.LLKHF_UP


class Reloj:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class PantallasTest(unittest.TestCase):
    def test_altura_se_conserva_entre_resoluciones(self):
        chica = Pantallas([Monitor(0, 0, 1366, 768)])
        ratio = FHD.ratio_en_borde(DERECHA, 540)
        self.assertAlmostEqual(chica.y_desde_ratio(IZQUIERDA, ratio), 384, delta=1)

    def test_extremos(self):
        self.assertEqual(FHD.y_desde_ratio(DERECHA, 0), 0)
        self.assertEqual(FHD.y_desde_ratio(DERECHA, 65535), 1079)
        self.assertEqual(FHD.ratio_en_borde(DERECHA, 1079), 65535)

    def test_varios_monitores_con_coordenadas_negativas(self):
        p = Pantallas([Monitor(-1920, 0, 0, 1080), Monitor(0, 0, 2560, 1440)])
        self.assertEqual((p.izq, p.der, p.ancho, p.alto), (-1920, 2560, 4480, 1440))
        self.assertEqual(p.rango_borde(IZQUIERDA), (0, 1080))
        self.assertEqual(p.rango_borde(DERECHA), (0, 1440))

    def test_limitar_saca_al_cursor_de_zonas_sin_monitor(self):
        p = Pantallas([Monitor(-1920, 0, 0, 1080), Monitor(0, 0, 2560, 1440)])
        self.assertEqual(p.limitar(-500, 1300), (-500, 1079))
        self.assertEqual(p.limitar(100, 1300), (100, 1300))


class CoordenadasTest(unittest.TestCase):
    def test_cada_pixel_se_recupera_exacto(self):
        for tamanio in (1366, 1920, 2560, 3840, 4480, 7680):
            for x in range(0, tamanio, 7):
                n = a_coordenada_normalizada(x, 0, tamanio)
                self.assertLessEqual(n, 65535)
                self.assertEqual(n * tamanio // 65536, x)

    def test_con_origen_negativo(self):
        self.assertEqual(a_coordenada_normalizada(-1920, -1920, 4480), 0)


class CapturaBase(unittest.TestCase):
    lado = DERECHA

    def setUp(self):
        self.enviados = []
        self.pedidos = []
        self.reloj = Reloj()
        cfg = Config(lado_otra_pantalla=self.lado, max_envios_mouse_hz=0, esquinas_muertas_px=20)
        self.logica = LogicaCaptura(
            cfg, FHD, self.enviados.append,
            lambda codigo, valor=0: self.pedidos.append(codigo), self.reloj,
        )
        self.logica.conectado = True

    def recibidos(self):
        lector = P.LectorMarcos()
        marcos = lector.alimentar(b"".join(self.enviados))
        self.enviados.clear()
        return marcos

    def cruzar(self):
        self.assertTrue(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))
        self.assertTrue(self.logica.remoto)
        self.logica.al_estacionar(960, 540, 270)
        self.reloj.t += 1.0
        self.recibidos()


class CapturaTest(CapturaBase):
    def test_lejos_del_borde_no_hace_nada(self):
        self.assertFalse(self.logica.al_mouse(MOVER, 1000, 540, 0, 0))
        self.assertFalse(self.logica.remoto)
        self.assertEqual(self.enviados, [])

    def test_cruza_y_avisa(self):
        self.assertTrue(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))
        self.assertTrue(self.logica.remoto)
        self.assertEqual(self.recibidos()[0][0], P.Tipo.ENTRAR)
        self.assertEqual(self.pedidos, [PEDIDO_ESTACIONAR])

    def test_tambien_si_windows_informa_fuera_de_pantalla(self):
        self.assertTrue(self.logica.al_mouse(MOVER, 1925, 540, 0, 0))

    def test_sin_cliente_no_cruza(self):
        self.logica.conectado = False
        self.assertFalse(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))

    def test_esquinas_muertas(self):
        self.assertFalse(self.logica.al_mouse(MOVER, 1919, 5, 0, 0))
        self.assertFalse(self.logica.al_mouse(MOVER, 1919, 1075, 0, 0))
        self.assertTrue(self.logica.al_mouse(MOVER, 1919, 20, 0, 0))

    def test_no_cruza_arrastrando(self):
        self.logica.al_mouse(W.WM_LBUTTONDOWN, 1900, 540, 0, 0)
        self.assertFalse(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))
        self.logica.al_mouse(W.WM_LBUTTONUP, 1919, 540, 0, 0)
        self.assertTrue(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))

    def test_ignora_eventos_inyectados(self):
        self.assertFalse(self.logica.al_mouse(MOVER, 1919, 540, 0, W.LLMHF_INJECTED))
        self.assertFalse(self.logica.remoto)

    def test_mueve_relativo_y_bloquea(self):
        self.cruzar()
        self.assertTrue(self.logica.al_mouse(MOVER, 965, 538, 0, 0))
        marcos = self.recibidos()
        self.assertEqual(P.S_MOVER.unpack(marcos[0][1]), (5, -2))

    def test_antes_de_estacionar_no_manda_movimientos_falsos(self):
        self.logica.al_mouse(MOVER, 1925, 540, 0, 0)
        self.recibidos()
        self.assertTrue(self.logica.al_mouse(MOVER, 1800, 540, 0, 0))
        self.assertEqual(self.recibidos(), [])

    def test_descarta_evento_viejo_tras_estacionar(self):
        self.logica.al_mouse(MOVER, 1919, 540, 0, 0)
        self.logica.al_estacionar(960, 540, 270)
        self.recibidos()
        self.assertTrue(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))
        self.assertEqual(self.recibidos(), [])

    def test_tope_de_envios_acumula_y_no_pierde_nada(self):
        self.logica.intervalo_envio = 0.002
        self.cruzar()
        self.logica.t_ultimo_envio = self.reloj.t
        self.logica.al_mouse(MOVER, 963, 540, 0, 0)
        self.logica.al_mouse(MOVER, 964, 541, 0, 0)
        self.assertEqual(self.enviados, [])
        self.logica.vaciar_movimiento()
        self.assertEqual(P.S_MOVER.unpack(self.recibidos()[0][1]), (7, 1))

    def test_click_manda_antes_el_movimiento_pendiente(self):
        self.logica.intervalo_envio = 10.0
        self.cruzar()
        self.logica.t_ultimo_envio = self.reloj.t
        self.logica.al_mouse(MOVER, 963, 540, 0, 0)
        self.assertTrue(self.logica.al_mouse(W.WM_LBUTTONDOWN, 960, 540, 0, 0))
        self.assertEqual([t for t, _ in self.recibidos()], [P.Tipo.MOVER, P.Tipo.BOTON])

    def test_rueda_negativa(self):
        self.cruzar()
        dato = (0x10000 - 120) << 16
        self.logica.al_mouse(W.WM_MOUSEWHEEL, 960, 540, dato, 0)
        self.assertEqual(P.S_RUEDA.unpack(self.recibidos()[0][1]), (-120, 0))

    def test_boton_x(self):
        self.cruzar()
        self.logica.al_mouse(W.WM_XBUTTONDOWN, 960, 540, W.XBUTTON2 << 16, 0)
        self.assertEqual(P.S_BOTON.unpack(self.recibidos()[0][1]), (P.BOTON_X2, 1))

    def test_tecla_local_pasa_y_remota_se_bloquea(self):
        self.assertFalse(self.logica.al_teclado(W.WM_KEYDOWN, 0x41, 0x1E, BAJA))
        self.assertEqual(self.enviados, [])
        self.logica.al_teclado(W.WM_KEYUP, 0x41, 0x1E, SUBE)
        self.cruzar()
        self.assertTrue(self.logica.al_teclado(W.WM_KEYDOWN, 0x41, 0x1E, BAJA))
        self.assertEqual(P.S_TECLA.unpack(self.recibidos()[0][1]), (0x41, 0x1E, 0))

    def test_combinacion_ctrl_c_llega_en_orden(self):
        self.cruzar()
        for mensaje, vk, escaneo, banderas in [
            (W.WM_KEYDOWN, W.VK_LCONTROL, 0x1D, BAJA),
            (W.WM_KEYDOWN, 0x43, 0x2E, BAJA),
            (W.WM_KEYUP, 0x43, 0x2E, SUBE),
            (W.WM_KEYUP, W.VK_LCONTROL, 0x1D, SUBE),
        ]:
            self.assertTrue(self.logica.al_teclado(mensaje, vk, escaneo, banderas))
        recibidas = [P.S_TECLA.unpack(c) for _, c in self.recibidos()]
        self.assertEqual([r[0] for r in recibidas], [W.VK_LCONTROL, 0x43, 0x43, W.VK_LCONTROL])
        self.assertEqual([r[2] & P.TECLA_SOLTADA for r in recibidas], [0, 0, 1, 1])

    def test_altgr_no_manda_el_ctrl_falso(self):
        self.cruzar()
        self.assertTrue(self.logica.al_teclado(W.WM_KEYDOWN, W.VK_LCONTROL, 0x21D, BAJA))
        self.assertEqual(self.recibidos(), [])
        self.logica.al_teclado(W.WM_SYSKEYDOWN, W.VK_RMENU, 0x38, W.LLKHF_EXTENDED)
        self.assertEqual(P.S_TECLA.unpack(self.recibidos()[0][1])[0], W.VK_RMENU)

    def test_altgr_mas_esc_no_es_emergencia(self):
        self.cruzar()
        self.logica.al_teclado(W.WM_KEYDOWN, W.VK_LCONTROL, 0x21D, BAJA)
        self.logica.al_teclado(W.WM_SYSKEYDOWN, W.VK_RMENU, 0x38, W.LLKHF_EXTENDED)
        self.logica.al_teclado(W.WM_KEYDOWN, W.VK_ESCAPE, 0x01, BAJA)
        self.assertTrue(self.logica.remoto)

    def test_emergencia(self):
        self.cruzar()
        self.logica.al_teclado(W.WM_KEYDOWN, W.VK_LCONTROL, 0x1D, BAJA)
        self.logica.al_teclado(W.WM_SYSKEYDOWN, W.VK_LMENU, 0x38, BAJA)
        self.recibidos()
        self.assertTrue(self.logica.al_teclado(W.WM_SYSKEYDOWN, W.VK_ESCAPE, 0x01, BAJA))
        self.assertFalse(self.logica.remoto)
        self.assertEqual([t for t, _ in self.recibidos()], [P.Tipo.SALIR])
        self.assertIn(PEDIDO_RESTAURAR, self.pedidos)
        self.assertFalse(self.logica.al_mouse(MOVER, 900, 500, 0, 0))

    def test_emergencia_funciona_sin_red(self):
        self.cruzar()

        def red_caida(_datos):
            return False

        self.logica.enviar = red_caida
        self.logica.al_teclado(W.WM_KEYDOWN, W.VK_RCONTROL, 0x1D, W.LLKHF_EXTENDED)
        self.logica.al_teclado(W.WM_SYSKEYDOWN, W.VK_RMENU, 0x38, W.LLKHF_EXTENDED)
        self.logica.al_teclado(W.WM_SYSKEYDOWN, W.VK_ESCAPE, 0x01, BAJA)
        self.assertFalse(self.logica.remoto)

    def test_tecla_apretada_al_cruzar_se_traspasa(self):
        self.logica.al_teclado(W.WM_KEYDOWN, VK_LSHIFT, 0x2A, BAJA)
        self.logica.al_mouse(MOVER, 1919, 540, 0, 0)
        marcos = self.recibidos()
        self.assertEqual([t for t, _ in marcos], [P.Tipo.ENTRAR, P.Tipo.TECLA])
        self.assertEqual([vk for vk, _ in self.logica.tomar_teclas_locales()], [VK_LSHIFT])

    def test_volver_deja_cursor_adentro_y_con_enfriamiento(self):
        self.cruzar()
        destino = self.logica.al_volver(32768)
        self.assertEqual(destino[0], 1917)
        self.assertAlmostEqual(destino[1], 540, delta=1)
        self.assertFalse(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))
        self.reloj.t += 0.3
        self.assertTrue(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))

    def test_desconexion_libera(self):
        self.cruzar()
        self.assertTrue(self.logica.al_desconectar())
        self.assertFalse(self.logica.remoto)
        self.assertFalse(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))


class CapturaIzquierdaTest(CapturaBase):
    lado = IZQUIERDA

    def test_cruza_por_la_izquierda(self):
        self.assertFalse(self.logica.al_mouse(MOVER, 1919, 540, 0, 0))
        self.assertTrue(self.logica.al_mouse(MOVER, 0, 540, 0, 0))

    def test_vuelve_a_la_izquierda(self):
        self.logica.al_mouse(MOVER, 0, 540, 0, 0)
        self.assertEqual(self.logica.al_volver(0), (2, 0))


class SalidaFalsa:
    def __init__(self, monitores=None):
        self._p = Pantallas(monitores or [Monitor(0, 0, 1920, 1080)])
        self.posiciones = []
        self.botones = []
        self.teclas = []
        self.ruedas = []

    def pantallas(self):
        return self._p

    def posicion_real(self):
        return self.posiciones[-1]

    def mover_a(self, x, y):
        self.posiciones.append((x, y))

    def boton(self, codigo, apretado):
        self.botones.append((codigo, apretado))

    def rueda(self, delta, horizontal):
        self.ruedas.append((delta, horizontal))

    def tecla(self, vk, escaneo, banderas):
        self.teclas.append((vk, escaneo, banderas))


class ClienteTest(unittest.TestCase):
    def setUp(self):
        self.salida = SalidaFalsa()
        self.enviados = []
        self.reloj = Reloj()
        self.logica = LogicaCliente(
            self.salida, IZQUIERDA, self.enviados.append, reloj=self.reloj
        )

    def entrar(self):
        self.logica.entrar(32768)
        self.reloj.t += 1.0

    def seguir(self):
        self.reloj.t += 0.01

    def test_entrar_lo_deja_adentro_del_borde(self):
        self.logica.entrar(32768)
        self.assertEqual(self.salida.posiciones[-1][0], 2)
        self.assertAlmostEqual(self.salida.posiciones[-1][1], 540, delta=1)

    def test_movimientos_se_acumulan(self):
        self.logica.entrar(0)
        self.seguir()
        self.logica.mover(10, 5)
        self.seguir()
        self.logica.mover(-3, 1)
        self.assertEqual(self.salida.posiciones[-1], (9, 6))

    def test_vuelve_por_el_borde(self):
        self.entrar()
        self.logica.y = 540
        self.logica.x = 0
        self.logica.t_movimiento = self.reloj.t
        self.logica.mover(-1, 0)
        self.assertFalse(self.logica.activo)
        self.assertEqual(P.LectorMarcos().alimentar(self.enviados[0])[0][0], P.Tipo.VOLVER)

    def test_no_rebota_al_llegar(self):
        self.logica.entrar(32768)
        self.seguir()
        self.logica.mover(-50, 0)
        self.assertTrue(self.logica.activo)
        self.assertEqual(self.salida.posiciones[-1][0], 0)

    def test_no_vuelve_arrastrando(self):
        self.entrar()
        self.logica.boton(P.BOTON_IZQUIERDO, True)
        self.logica.t_movimiento = self.reloj.t
        self.logica.mover(-50, 0)
        self.assertTrue(self.logica.activo)
        self.assertEqual(self.salida.posiciones[-1][0], 0)

    def test_no_se_sale_por_los_otros_bordes(self):
        self.logica.entrar(32768)
        self.seguir()
        self.logica.mover(5000, 5000)
        self.assertEqual(self.salida.posiciones[-1], (1919, 1079))
        self.assertTrue(self.logica.activo)

    def test_al_volver_suelta_todo(self):
        self.entrar()
        self.logica.tecla(0x41, 0x1E, 0)
        self.logica.t_movimiento = self.reloj.t
        self.logica.mover(-50, 0)
        self.assertEqual(self.salida.teclas[-1], (0x41, 0x1E, P.TECLA_SOLTADA))

    def test_salir_suelta_botones_y_teclas(self):
        self.entrar()
        self.logica.boton(P.BOTON_DERECHO, True)
        self.logica.tecla(W.VK_LCONTROL, 0x1D, 0)
        self.logica.salir()
        self.assertEqual(self.salida.botones[-1], (P.BOTON_DERECHO, False))
        self.assertEqual(self.salida.teclas[-1][2] & P.TECLA_SOLTADA, P.TECLA_SOLTADA)
        self.assertFalse(self.logica.activo)

    def test_inactivo_ignora_todo(self):
        self.logica.mover(10, 10)
        self.logica.tecla(0x41, 0x1E, 0)
        self.assertEqual(self.salida.posiciones, [])
        self.assertEqual(self.salida.teclas, [])

    def test_tras_una_pausa_relee_la_posicion_real(self):
        self.logica.entrar(0)
        self.salida.posiciones.append((700, 700))
        self.reloj.t += 1.0
        self.logica.mover(1, 1)
        self.assertEqual(self.salida.posiciones[-1], (701, 701))

    def test_borde_derecho(self):
        salida = SalidaFalsa()
        enviados = []
        logica = LogicaCliente(salida, DERECHA, enviados.append, reloj=self.reloj)
        logica.entrar(32768)
        self.assertEqual(salida.posiciones[-1][0], 1917)
        self.reloj.t += 0.3
        logica.t_movimiento = self.reloj.t
        logica.mover(50, 0)
        self.assertFalse(logica.activo)


if __name__ == "__main__":
    unittest.main()
