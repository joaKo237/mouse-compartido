"""Servidor y cliente completos hablando por red real (127.0.0.1), sin tocar el mouse."""

import statistics
import threading
import time
import unittest
from dataclasses import replace

from mouse_compartido import win32 as W
from mouse_compartido.cliente import Cliente
from mouse_compartido.config import Config
from mouse_compartido.inyeccion import SalidaSimulada
from mouse_compartido.logica_captura import PEDIDO_ESTACIONAR, LogicaCaptura
from mouse_compartido.pantallas import Monitor, Pantallas
from mouse_compartido.servidor import Servidor

PUERTO = 24999
CONFIG = Config(
    puerto=PUERTO, pin="prueba-1234", ip_servidor="127.0.0.1", max_envios_mouse_hz=0,
    esquinas_muertas_px=0, enfriamiento_ms=0, mostrar_latencia=False,
)


class CapturaFalsa:
    """Reemplaza a los ganchos de Windows: los eventos los inventa la prueba."""

    def __init__(self, config):
        self.logica = LogicaCaptura(
            config, Pantallas([Monitor(0, 0, 1920, 1080)]), self._enviar, self._pedir
        )
        self._conexion = None
        self.conectado = threading.Event()
        self.desconectado = threading.Event()
        self.volvio = threading.Event()

    def _enviar(self, datos):
        if self._conexion is not None:
            self._conexion.enviar(datos)

    def _pedir(self, codigo, valor=0):
        if codigo == PEDIDO_ESTACIONAR:
            self.logica.al_estacionar(960, 540, 270)

    def iniciar(self):
        pass

    def detener(self):
        pass

    def conectar(self, conexion):
        self._conexion = conexion
        self.logica.conectado = True
        self.conectado.set()

    def desconectar(self):
        self.logica.al_desconectar()
        self.desconectado.set()

    def pedir_volver(self, ratio):
        self.logica.al_volver(ratio)
        self.volvio.set()

    def actualizar_pantallas(self):
        pass


class SalidaEspia(SalidaSimulada):
    def __init__(self):
        super().__init__(monitores=[Monitor(0, 0, 1366, 768)], mostrar=False)
        self.movida = threading.Event()
        self.eventos = []
        self.marcas = []

    def mover_a(self, x, y):
        super().mover_a(x, y)
        self.marcas.append(time.perf_counter())
        self.movida.set()

    def boton(self, codigo, apretado):
        self.eventos.append(("boton", codigo, apretado))

    def tecla(self, vk, escaneo, banderas):
        self.eventos.append(("tecla", vk, banderas))

    def rueda(self, delta, horizontal):
        self.eventos.append(("rueda", delta, horizontal))


def esperar(condicion, segundos=3.0):
    limite = time.perf_counter() + segundos
    while time.perf_counter() < limite:
        if condicion():
            return True
        time.sleep(0.001)
    return False


class IntegracionTest(unittest.TestCase):
    def arrancar(self, config_cliente=None):
        self.captura = CapturaFalsa(CONFIG)
        self.salida = SalidaEspia()
        self.servidor = Servidor(CONFIG, captura=self.captura)
        self.cliente = Cliente(config_cliente or CONFIG, salida=self.salida)
        self.addCleanup(self.cerrar)
        self.hilo_servidor = threading.Thread(target=self.servidor.correr, daemon=True)
        self.hilo_servidor.start()
        self.assertTrue(self.servidor.escuchando.wait(5))
        self.hilo_cliente = threading.Thread(target=self.cliente.correr, daemon=True)
        self.hilo_cliente.start()

    def cerrar(self):
        self.cliente.detener()
        self.servidor.detener()
        self.hilo_cliente.join(5)
        self.hilo_servidor.join(5)

    def test_recorrido_completo_y_latencia(self):
        self.arrancar()
        self.assertTrue(self.captura.conectado.wait(5))
        logica = self.captura.logica

        # Cruza: el cursor aparece en el borde izquierdo de la otra pantalla,
        # a la misma altura relativa aunque la resolución sea distinta.
        self.assertTrue(logica.al_mouse(W.WM_MOUSEMOVE, 1919, 540, 0, 0))
        self.assertTrue(self.salida.movida.wait(2))
        self.assertEqual(self.salida.x, 2)
        self.assertAlmostEqual(self.salida.y, 384, delta=1)

        # Movimiento: 2000 eventos midiendo el tiempo de punta a punta.
        latencias = []
        self.salida.marcas.clear()
        x = 960
        for i in range(2000):
            x = 961 if i % 2 == 0 else 962
            cantidad = len(self.salida.marcas)
            inicio = time.perf_counter()
            logica.al_mouse(W.WM_MOUSEMOVE, x, 540, 0, 0)
            self.assertTrue(esperar(lambda: len(self.salida.marcas) > cantidad))
            latencias.append((self.salida.marcas[-1] - inicio) * 1e6)
        latencias.sort()
        print(
            f"\nLatencia de punta a punta sin red física (mediana / p99): "
            f"{statistics.median(latencias):.0f} us / {latencias[int(len(latencias) * .99)]:.0f} us"
        )

        # Click y teclas llegan en orden.
        logica.al_mouse(W.WM_LBUTTONDOWN, 960, 540, 0, 0)
        logica.al_mouse(W.WM_LBUTTONUP, 960, 540, 0, 0)
        logica.al_teclado(W.WM_KEYDOWN, 0x41, 0x1E, 0)
        logica.al_teclado(W.WM_KEYUP, 0x41, 0x1E, W.LLKHF_UP)
        self.assertTrue(esperar(lambda: len(self.salida.eventos) >= 4))
        self.assertEqual(self.salida.eventos[:2], [("boton", 1, True), ("boton", 1, False)])
        self.assertEqual(self.salida.eventos[2:4], [("tecla", 0x41, 0), ("tecla", 0x41, 1)])

        # Vuelve por el borde izquierdo de la otra PC.
        self.salida.movida.clear()
        logica.al_mouse(W.WM_MOUSEMOVE, 960 - 3000, 540, 0, 0)
        self.assertTrue(self.captura.volvio.wait(2))
        self.assertFalse(logica.remoto)

    def test_cliente_con_pin_equivocado_no_entra(self):
        self.arrancar(config_cliente=replace(CONFIG, pin="otro-pin"))
        self.hilo_cliente.join(10)
        self.assertFalse(self.hilo_cliente.is_alive(), "El cliente debe desistir")
        self.assertFalse(self.captura.conectado.is_set())

    def test_si_se_cae_el_cliente_vuelve_el_control(self):
        self.arrancar()
        self.assertTrue(self.captura.conectado.wait(5))
        logica = self.captura.logica
        logica.al_mouse(W.WM_MOUSEMOVE, 1919, 540, 0, 0)
        self.assertTrue(self.salida.movida.wait(2))
        self.cliente.detener()
        self.assertTrue(self.captura.desconectado.wait(5))
        self.assertFalse(logica.remoto)

    def test_ping_responde(self):
        self.arrancar()
        self.assertTrue(self.captura.conectado.wait(5))
        time.sleep(2.6)  # Más que el tiempo sin respuesta: la sesión debe seguir viva.
        self.assertFalse(self.captura.desconectado.is_set())


if __name__ == "__main__":
    unittest.main()
