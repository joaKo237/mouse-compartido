"""Los avisos que dicen de quién es la culpa cuando el mouse se pone lento."""

import sys
import threading
import time
import unittest
from dataclasses import replace
from unittest import mock

from mouse_compartido.comun.config import Config
from mouse_compartido.motor import cliente as modulo_cliente
from mouse_compartido.motor import servidor as modulo_servidor
from mouse_compartido.motor.cliente import Cliente
from mouse_compartido.motor.servidor import Servidor, _MedidorLatencia
from mouse_compartido.sistema import win32 as W
from mouse_compartido.ui.resumen import texto_latencia
from tests.test_integracion import CapturaFalsa, SalidaEspia, esperar


class InformanteFalso:
    def __init__(self):
        self.datos = {}

    def actualizar(self, **cambios):
        self.datos.update(cambios)


class MedidorLatenciaTest(unittest.TestCase):
    def setUp(self):
        parche = mock.patch.object(modulo_servidor, "log")
        self.log = parche.start()
        self.addCleanup(parche.stop)
        self.informante = InformanteFalso()
        self.medidor = _MedidorLatencia(self.informante, False, reloj=lambda: 0.0)

    def test_red_normal_no_avisa(self):
        for i in range(20):
            self.medidor.agregar(3.0, i * 0.2)
        self.log.assert_not_called()
        self.medidor.informar(4.0)
        self.assertEqual(self.informante.datos["latencia_ms"], 3.0)
        self.assertEqual(self.informante.datos["latencia_pico_ms"], 3.0)

    def test_un_tiron_avisa_una_vez_cada_15_segundos(self):
        self.medidor.agregar(180.0, 1.0)
        self.medidor.agregar(200.0, 5.0)  # Muy pronto: no repite el aviso.
        self.assertEqual(self.log.call_count, 1)
        self.assertIn("180 ms", self.log.call_args[0][0])
        self.medidor.agregar(90.0, 17.0)
        self.assertEqual(self.log.call_count, 2)

    def test_el_tiron_se_ve_en_la_ventana_durante_30_segundos(self):
        self.medidor.agregar(3.0, 0.5)
        self.medidor.agregar(150.0, 1.0)
        self.medidor.informar(2.0)
        self.assertEqual(self.informante.datos["latencia_pico_ms"], 150.0)
        for t in range(4, 31, 2):  # Después, todo normal.
            self.medidor.agregar(3.0, t - 0.5)
            self.medidor.informar(float(t))
        self.assertEqual(self.informante.datos["latencia_pico_ms"], 150.0)
        self.medidor.agregar(3.0, 32.5)
        self.medidor.informar(33.0)
        self.assertEqual(self.informante.datos["latencia_pico_ms"], 3.0)


class TextoLatenciaTest(unittest.TestCase):
    def test_textos(self):
        self.assertEqual(texto_latencia({}), "—")
        self.assertEqual(texto_latencia({"latencia_ms": 2.43, "latencia_pico_ms": 9.0}), "2.4 ms")
        self.assertEqual(texto_latencia({"latencia_ms": 2.4, "latencia_pico_ms": 180.0}),
                         "2.4 ms · tirón de 180 ms")


@unittest.skipUnless(sys.platform == "win32", "Solo en Windows")
class AtrasoDelMouseTest(unittest.TestCase):
    def test_avisa_si_el_mouse_se_atrasa_dentro_de_la_pc(self):
        from mouse_compartido.entrada import captura as modulo_captura

        hilo = modulo_captura.HiloCaptura(Config(rol="servidor", pin="abcd1234"))
        with mock.patch.object(modulo_captura, "log") as log:
            hilo._atraso_max = 20  # Normal: no avisa.
            hilo._revisar_atraso()
            log.assert_not_called()
            hilo._atraso_max = 140
            hilo._revisar_atraso()
            self.assertEqual(log.call_count, 1)
            self.assertIn("140 ms", log.call_args[0][0])
            self.assertEqual(hilo._atraso_max, 0, "Cada revisión empieza de cero")
            hilo._atraso_max = 300
            hilo._revisar_atraso()  # Recién avisó: no repite.
            self.assertEqual(log.call_count, 1)

    def test_windows_acepta_no_frenar_el_programa(self):
        self.assertTrue(W.desactivar_modo_eficiencia())


class SalidaLenta(SalidaEspia):
    """Una PC tan ocupada que mover el cursor tarda 5 ms cada vez."""

    def mover_a(self, x, y):
        time.sleep(0.005)
        super().mover_a(x, y)


class ClienteLentoTest(unittest.TestCase):
    def test_el_cliente_avisa_si_tarda_en_mover_el_cursor(self):
        config = Config(puerto=24998, pin="prueba-lento", ip_servidor="127.0.0.1",
                        max_envios_mouse_hz=0, esquinas_muertas_px=0, enfriamiento_ms=0,
                        mostrar_latencia=False)
        captura = CapturaFalsa(config)
        salida = SalidaLenta()
        servidor = Servidor(replace(config, rol="servidor"), captura=captura)
        cliente = Cliente(replace(config, rol="cliente"), salida=salida)
        hilos = [threading.Thread(target=servidor.correr, daemon=True),
                 threading.Thread(target=cliente.correr, daemon=True)]
        with mock.patch.object(modulo_cliente, "log") as log:
            hilos[0].start()
            self.assertTrue(servidor.escuchando.wait(5))
            hilos[1].start()
            try:
                self.assertTrue(captura.conectado.wait(5))
                logica = captura.logica
                self.assertTrue(logica.al_mouse(W.WM_MOUSEMOVE, 1919, 540, 0, 0))  # Cruza.
                self.assertTrue(salida.movida.wait(2))
                time.sleep(0.15)  # Pasa la ventana del filtro de saltos.
                for i in range(40):
                    logica.al_mouse(W.WM_MOUSEMOVE, 961 + i % 2, 540, 0, 0)
                avisos = lambda: [c for c in log.call_args_list if "tardó" in c[0][0]]
                self.assertTrue(esperar(lambda: avisos(), 3), log.call_args_list)
            finally:
                cliente.detener()
                servidor.detener()
                for hilo in hilos:
                    hilo.join(5)


if __name__ == "__main__":
    unittest.main()
