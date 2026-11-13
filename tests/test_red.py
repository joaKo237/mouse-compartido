"""Pruebas del formato de mensajes, la conexión, el saludo y el cifrado (sockets reales)."""

import socket
import threading
import unittest

from mouse_compartido.red import protocolo as P
from mouse_compartido.red.conexion import Conexion, ConexionCerrada
from mouse_compartido.comun.pantallas import IZQUIERDA
from mouse_compartido.red.seguridad import (
    FalloAutenticacion,
    NoEmparejada,
    autenticar_como_cliente,
    autenticar_como_servidor,
)

from .ayuda import CLAVE, EMP_CLIENTE, EMP_INTRUSA, EMP_SERVIDOR


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


class SaludoTest(unittest.TestCase):
    def _saludar(self, emp_servidor, emp_cliente):
        a, b = par_de_conexiones()
        self.addCleanup(a.cerrar)
        self.addCleanup(b.cerrar)
        resultado = {}

        def servidor():
            try:
                resultado["servidor"] = autenticar_como_servidor(b, emp_servidor, IZQUIERDA,
                                                                 timeout=2)
            except FalloAutenticacion as error:
                resultado["servidor"] = error

        hilo = threading.Thread(target=servidor)
        hilo.start()
        try:
            resultado["cliente"] = autenticar_como_cliente(a, emp_cliente, timeout=2)
        except FalloAutenticacion as error:
            resultado["cliente"] = error
        hilo.join()
        return resultado, a, b

    def test_pcs_emparejadas_se_saludan_y_arman_claves_cruzadas(self):
        resultado, _, _ = self._saludar(EMP_SERVIDOR, EMP_CLIENTE)
        servidor, cliente = resultado["servidor"], resultado["cliente"]
        self.assertEqual(cliente.lado, IZQUIERDA)
        self.assertEqual(servidor.canal, P.CANAL_ENTRADA)
        # Lo que manda uno es lo que recibe el otro, y cada sentido tiene su clave.
        self.assertEqual(servidor.envio, cliente.recepcion)
        self.assertEqual(servidor.recepcion, cliente.envio)
        self.assertNotEqual(servidor.envio, servidor.recepcion)

    def test_cada_conexion_tiene_claves_nuevas(self):
        primera, _, _ = self._saludar(EMP_SERVIDOR, EMP_CLIENTE)
        segunda, _, _ = self._saludar(EMP_SERVIDOR, EMP_CLIENTE)
        self.assertNotEqual(primera["cliente"].envio, segunda["cliente"].envio)

    def test_una_pc_no_emparejada_se_rechaza(self):
        resultado, _, _ = self._saludar(EMP_SERVIDOR, EMP_INTRUSA)
        self.assertIsInstance(resultado["servidor"], NoEmparejada)
        self.assertIsInstance(resultado["cliente"], NoEmparejada)

    def test_con_el_id_correcto_pero_otra_clave_se_rechaza(self):
        trucha = EMP_CLIENTE.__class__(EMP_CLIENTE.id_propio, EMP_CLIENTE.id_otra, bytes(32))
        resultado, _, _ = self._saludar(EMP_SERVIDOR, trucha)
        self.assertIsInstance(resultado["servidor"], NoEmparejada)
        self.assertIsInstance(resultado["cliente"], FalloAutenticacion)

    def test_la_clave_no_viaja_por_la_red(self):
        a, b = par_de_conexiones()
        self.addCleanup(a.cerrar)
        self.addCleanup(b.cerrar)
        capturado = bytearray()
        original = a._sock.send
        hilo = threading.Thread(
            target=lambda: autenticar_como_servidor(b, EMP_SERVIDOR, IZQUIERDA, timeout=2)
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
            autenticar_como_cliente(a, EMP_CLIENTE, timeout=2)
        finally:
            hilo.join()
            a._sock = real
        self.assertGreater(len(capturado), 0)
        self.assertNotIn(bytes.fromhex(CLAVE), bytes(capturado))


class CifradoTest(unittest.TestCase):
    def _cifradas(self):
        a, b = par_de_conexiones()
        self.addCleanup(a.cerrar)
        self.addCleanup(b.cerrar)
        clave_ab, clave_ba = bytes(range(32)), bytes(range(1, 33))
        a.activar_cifrado(clave_ab, clave_ba)
        b.activar_cifrado(clave_ba, clave_ab)
        return a, b

    def _recibir(self, conexion, cantidad):
        marcos = []
        for _ in range(50):
            marcos += conexion.recibir(0.05)
            if len(marcos) >= cantidad:
                break
        return marcos

    def test_los_mensajes_llegan_cifrados_y_se_entienden(self):
        a, b = self._cifradas()
        espiado = bytearray()
        original = a._sock.send

        def espiar(datos):
            espiado.extend(datos)
            return original(datos)

        a._sock = type("S", (), {"send": staticmethod(espiar), "close": a._sock.close,
                                 "fileno": a._sock.fileno})()
        secreto = P.marco(P.Tipo.INFO, b"contrasenia-secreta")
        self.assertTrue(a.enviar(P.mover(5, -3)))
        self.assertTrue(a.enviar(P.tecla(0x41, 0x1E, 0) + secreto))  # Dos marcos juntos.
        marcos = self._recibir(b, 3)
        self.assertEqual(marcos[0], (P.Tipo.MOVER, P.S_MOVER.pack(5, -3)))
        self.assertEqual(marcos[1][0], P.Tipo.TECLA)
        self.assertEqual(marcos[2], (P.Tipo.INFO, b"contrasenia-secreta"))
        self.assertNotIn(b"contrasenia-secreta", bytes(espiado))
        # Cada marco cifrado mide lo mismo que el original más el sello de 16 bytes.
        self.assertEqual(len(espiado), 7 + 16 + 6 + 16 + len(secreto) + 16)

    def test_un_mensaje_alterado_corta_la_conexion(self):
        a, b = self._cifradas()
        a.enviar(P.mover(1, 1))
        self.assertEqual(len(self._recibir(b, 1)), 1)
        # Alguien de la red mete un marco inventado: no tiene un sello válido.
        a._sock.send(P.mover(100, 100) + bytes(16))
        with self.assertRaises(ConexionCerrada):
            for _ in range(50):
                b.recibir(0.05)


if __name__ == "__main__":
    unittest.main()
