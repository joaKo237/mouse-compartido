"""Pruebas del formato de mensajes, la conexión y el PIN (sobre sockets reales)."""

import socket
import threading
import unittest

from mouse_compartido.red import protocolo as P
from mouse_compartido.red.conexion import Conexion, ConexionCerrada
from mouse_compartido.comun.pantallas import IZQUIERDA
from mouse_compartido.red.seguridad import (
    FalloAutenticacion,
    autenticar_como_cliente,
    autenticar_como_servidor,
    derivar_clave,
)

CLAVE = derivar_clave("1234abcd")
OTRA_CLAVE = derivar_clave("otra-clave")


def par_de_conexiones():
    oyente = socket.socket()
    oyente.bind(("127.0.0.1", 0))
    oyente.listen(1)
    a = socket.create_connection(oyente.getsockname())
    b, _ = oyente.accept()
    oyente.close()
    return Conexion(a), Conexion(b)


class ProtocoloTest(unittest.TestCase):
    def test_movimiento_ocupa_siete_bytes(self):
        self.assertEqual(len(P.mover(5, -3)), 7)

    def test_ida_y_vuelta_de_cada_mensaje(self):
        lector = P.LectorMarcos()
        datos = (
            P.mover(-100, 200) + P.boton(P.BOTON_DERECHO, True) + P.rueda(-120, True)
            + P.tecla(0x41, 0x1E, P.TECLA_SOLTADA) + P.entrar(32768) + P.salir()
        )
        marcos = lector.alimentar(datos)
        self.assertEqual([tipo for tipo, _ in marcos], [
            P.Tipo.MOVER, P.Tipo.BOTON, P.Tipo.RUEDA, P.Tipo.TECLA, P.Tipo.ENTRAR, P.Tipo.SALIR,
        ])
        self.assertEqual(P.S_MOVER.unpack(marcos[0][1]), (-100, 200))
        self.assertEqual(P.S_BOTON.unpack(marcos[1][1]), (P.BOTON_DERECHO, 1))
        self.assertEqual(P.S_RUEDA.unpack(marcos[2][1]), (-120, 1))
        self.assertEqual(P.S_TECLA.unpack(marcos[3][1]), (0x41, 0x1E, P.TECLA_SOLTADA))
        self.assertEqual(P.S_RATIO.unpack(marcos[4][1]), (32768,))

    def test_marcos_partidos_en_pedazos(self):
        lector = P.LectorMarcos()
        datos = P.mover(1, 2) + P.mover(3, 4)
        recibidos = []
        for i in range(len(datos)):
            recibidos += lector.alimentar(datos[i:i + 1])
        self.assertEqual([P.S_MOVER.unpack(c) for _, c in recibidos], [(1, 2), (3, 4)])

    def test_movimiento_enorme_se_recorta(self):
        _, cuerpo = P.LectorMarcos().alimentar(P.mover(100000, -100000))[0]
        self.assertEqual(P.S_MOVER.unpack(cuerpo), (32767, -32768))

    def test_marco_invalido(self):
        with self.assertRaises(P.ErrorProtocolo):
            P.LectorMarcos().alimentar(b"\x00\x00\x01")

    def test_mensaje_demasiado_grande(self):
        with self.assertRaises(ValueError):
            P.marco(P.Tipo.PORTAPAPELES, b"x" * 70000)


class ConexionTest(unittest.TestCase):
    def test_nodelay_activado_y_envio(self):
        a, b = par_de_conexiones()
        self.addCleanup(a.cerrar)
        self.addCleanup(b.cerrar)
        self.assertTrue(a._sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))
        self.assertTrue(a.enviar(P.mover(1, 1)))
        self.assertEqual(b.esperar_marco(2)[0], P.Tipo.MOVER)

    def test_detecta_cierre(self):
        a, b = par_de_conexiones()
        self.addCleanup(b.cerrar)
        a.cerrar()
        with self.assertRaises(ConexionCerrada):
            for _ in range(20):
                b.recibir(0.1)

    def test_enviar_nunca_bloquea_si_el_otro_no_lee(self):
        a, b = par_de_conexiones()
        self.addCleanup(a.cerrar)
        self.addCleanup(b.cerrar)
        for _ in range(200):
            a.enviar(b"z" * 60000)  # Llena los buffers sin que nadie lea.
            if a.cerrada:
                break
        self.assertTrue(a.cerrada, "Tras superar el límite la conexión debe darse por muerta")


class PinTest(unittest.TestCase):
    def _saludar(self, clave_servidor, clave_cliente):
        a, b = par_de_conexiones()
        self.addCleanup(a.cerrar)
        self.addCleanup(b.cerrar)
        resultado = {}

        def servidor():
            try:
                autenticar_como_servidor(b, clave_servidor, IZQUIERDA, timeout=2)
                resultado["servidor"] = "ok"
            except FalloAutenticacion as error:
                resultado["servidor"] = error

        hilo = threading.Thread(target=servidor)
        hilo.start()
        try:
            resultado["cliente"] = autenticar_como_cliente(a, clave_cliente, timeout=2)
        except FalloAutenticacion as error:
            resultado["cliente"] = error
        hilo.join()
        return resultado

    def test_pin_correcto(self):
        resultado = self._saludar(CLAVE, CLAVE)
        self.assertEqual(resultado, {"servidor": "ok", "cliente": IZQUIERDA})

    def test_pin_incorrecto_se_rechaza(self):
        resultado = self._saludar(CLAVE, OTRA_CLAVE)
        self.assertIsInstance(resultado["servidor"], FalloAutenticacion)
        self.assertIsInstance(resultado["cliente"], FalloAutenticacion)

    def test_el_pin_no_viaja_por_la_red(self):
        a, b = par_de_conexiones()
        self.addCleanup(a.cerrar)
        self.addCleanup(b.cerrar)
        capturado = bytearray()
        original = a._sock.send
        hilo = threading.Thread(
            target=lambda: autenticar_como_servidor(b, CLAVE, IZQUIERDA, timeout=2)
        )

        class Espia:
            def __getattr__(self, nombre):
                return getattr(a.__dict__["_real"], nombre)

            def send(self, datos):
                capturado.extend(datos)
                return original(datos)

        a.__dict__["_real"] = a._sock
        a._sock = Espia()
        hilo.start()
        real = a.__dict__["_real"]
        a._sock.fileno = real.fileno
        try:
            autenticar_como_cliente(a, CLAVE, timeout=2)
        finally:
            hilo.join()
            a._sock = real
        self.assertGreater(len(capturado), 0)
        self.assertNotIn(b"1234abcd", bytes(capturado))
        self.assertNotIn(CLAVE, bytes(capturado))


if __name__ == "__main__":
    unittest.main()
