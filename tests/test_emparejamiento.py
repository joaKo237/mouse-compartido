"""Pruebas del cifrado de Windows, la búsqueda de PCs en la red y el emparejamiento."""

import threading
import time
import unittest

from mouse_compartido.red import descubrimiento as D
from mouse_compartido.red.emparejamiento import Emparejador, codigo_de
from mouse_compartido.sistema import cripto as C
from mouse_compartido.sistema import redes as R


class CriptoTest(unittest.TestCase):
    def test_aes_gcm_da_lo_mismo_que_el_estandar(self):
        # Caso de prueba oficial de AES-256-GCM: clave, nonce y texto en cero.
        sellado = C.Cifrador(bytes(32)).cifrar(bytes(16))
        self.assertEqual(sellado.hex(), "cea7403d4d606b6e074ec5d3baf39d18"
                                        "d0d1c8a799996bf0265b98b5d48ab919")

    def test_descifra_en_orden_y_rechaza_repetidos_o_alterados(self):
        envio, recepcion = C.Cifrador(bytes(range(32))), C.Cifrador(bytes(range(32)))
        primero, segundo = envio.cifrar(b"hola"), envio.cifrar(b"chau")
        self.assertEqual(recepcion.descifrar(primero), b"hola")
        with self.assertRaises(C.ErrorCripto):
            recepcion.descifrar(primero)  # Repetido: ya no corresponde a ese número de orden.
        alterado = C.Cifrador(bytes(range(32)))
        with self.assertRaises(C.ErrorCripto):
            alterado.descifrar(bytes([primero[0] ^ 1]) + primero[1:])
        self.assertNotEqual(primero[:4], segundo[:4])

    def test_mensajes_grandes(self):
        datos = bytes(range(256)) * 4000  # Más de 1 MB, más grande que la memoria reusada.
        sellado = C.Cifrador(bytes(32)).cifrar(datos)
        self.assertEqual(C.Cifrador(bytes(32)).descifrar(sellado), datos)

    def test_ecdh_las_dos_pcs_calculan_el_mismo_secreto(self):
        a, b = C.ParDeClaves(), C.ParDeClaves()
        self.assertEqual(len(a.publica), 64)
        self.assertEqual(a.acordar(b.publica), b.acordar(a.publica))
        self.assertNotEqual(a.acordar(b.publica), a.acordar(C.ParDeClaves().publica))

    def test_ecdh_rechaza_un_punto_que_no_es_de_la_curva(self):
        with self.assertRaises(C.ErrorCripto):
            C.ParDeClaves().acordar(bytes(64))

    def test_hkdf_del_estandar(self):
        # RFC 5869, caso 1.
        clave = bytes.fromhex("0b" * 22)
        sal = bytes.fromhex("000102030405060708090a0b0c")
        info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
        self.assertEqual(
            C.hkdf(clave, sal, info, 42).hex(),
            "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
            "34007208d5b887185865",
        )


class RedesTest(unittest.TestCase):
    def test_prioridad_prefiere_el_cable(self):
        placas = [R.Placa("10.0.0.2", "255.255.255.0", R.CABLE),
                  R.Placa("192.168.1.8", "255.255.255.0", R.WIFI)]
        self.assertEqual(R.prioridad("10.0.0.1", placas), R.CABLE)
        self.assertEqual(R.prioridad("192.168.1.28", placas), R.WIFI)
        self.assertEqual(R.prioridad("8.8.8.8", placas), R.SIN_RUTA)
        self.assertEqual(R.prioridad("no-es-ip", placas), R.SIN_RUTA)

    def test_cable_directo_sin_ip_fija(self):
        # Dos PCs unidas por cable sin router se ponen solas una IP 169.254.x.x.
        placas = [R.Placa("169.254.150.13", "255.255.0.0", R.CABLE)]
        self.assertEqual(R.prioridad("169.254.7.200", placas), R.CABLE)
        self.assertEqual(placas[0].difusion, "169.254.255.255")

    def test_lee_las_placas_de_esta_pc(self):
        for placa in R.placas():
            self.assertFalse(placa.ip.startswith("127."))
            self.assertIn(placa.tipo, (R.CABLE, R.WIFI, R.OTRA))


class DescubrimientoTest(unittest.TestCase):
    """Dos "PCs" en esta misma máquina, cada una en su puerto, avisándose por 127.0.0.1."""

    PUERTO_A = 25871
    PUERTO_B = 25872

    def _pc(self, puerto, destino, datos, cambios):
        descubridor = D.Descubridor(
            puerto, lambda: datos, al_cambiar=lambda: cambios.append(1),
            puerto_destino=destino, direcciones_extra=lambda: ["127.0.0.1"],
            placas=lambda: [],  # Que la prueba no mande avisos a la red de verdad.
        )
        self.assertTrue(descubridor.iniciar(), descubridor.error)
        self.addCleanup(descubridor.detener)
        return descubridor

    def _esperar(self, condicion, segundos=5.0):
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            if condicion():
                return True
            time.sleep(0.02)
        return False

    def test_se_encuentran_y_ven_los_datos_de_la_otra(self):
        datos_a = {"id": "aa" * 16, "nombre": "ESCRITORIO", "rol": "servidor", "puerto": 24850,
                   "emparejado_con": ""}
        datos_b = {"id": "bb" * 16, "nombre": "NOTEBOOK", "rol": "cliente", "puerto": 24850,
                   "emparejado_con": "aa" * 16}
        cambios_a, cambios_b = [], []
        a = self._pc(self.PUERTO_A, self.PUERTO_B, datos_a, cambios_a)
        b = self._pc(self.PUERTO_B, self.PUERTO_A, datos_b, cambios_b)
        self.assertTrue(self._esperar(lambda: a.buscar("bb" * 16) and b.buscar("aa" * 16)))
        vista = a.buscar("bb" * 16)
        self.assertEqual((vista.nombre, vista.rol, vista.emparejado_con),
                         ("NOTEBOOK", "cliente", "aa" * 16))
        self.assertEqual(vista.ip, "127.0.0.1")
        self.assertTrue(cambios_a)
        # Ninguna se anota a sí misma.
        self.assertEqual([pc.id for pc in a.pcs()], ["bb" * 16])

    def test_una_pc_que_se_va_desaparece_de_la_lista(self):
        reloj = [1000.0]
        a = D.Descubridor(self.PUERTO_A, lambda: {"id": "aa" * 16}, placas=lambda: [],
                          reloj=lambda: reloj[0])
        a._anotar("bb" * 16, "192.168.1.9", {"nombre": "OTRA", "rol": "cliente"})
        self.assertIsNotNone(a.buscar("bb" * 16))
        reloj[0] += D.VENCE_S + 1
        a._vencer(reloj[0])
        self.assertIsNone(a.buscar("bb" * 16))

    def test_destinos_con_el_cable_primero(self):
        pc = D.PcVista("bb" * 16, ips={"192.168.1.28": (R.WIFI, 0), "10.0.0.1": (R.CABLE, 0)})
        self.assertEqual(pc.destinos(), [("10.0.0.1", R.CABLE), ("192.168.1.28", R.WIFI)])
        self.assertEqual(pc.ip, "10.0.0.1")


class _Eventos:
    """Hace de interfaz: anota lo que pasa y decide automáticamente."""

    def __init__(self, decision=True, demora=0.0):
        self.decision = decision
        self.demora = demora
        self.pedidos = []
        self.codigos = []
        self.final = None
        self.listo = threading.Event()

    def pedido(self, intento):
        self.pedidos.append(intento.nombre_otra)

    def codigo(self, intento):
        self.codigos.append(intento.codigo)
        threading.Timer(self.demora, intento.decidir, args=(self.decision,)).start()

    def terminado(self, intento, resultado, motivo):
        self.final = (resultado, motivo)
        self.listo.set()


class EmparejamientoTest(unittest.TestCase):
    PUERTO_A = 25881
    PUERTO_B = 25882

    def _emparejar(self, decision_a=True, decision_b=True, demora_b=0.0):
        eventos_a, eventos_b = _Eventos(decision_a), _Eventos(decision_b, demora_b)
        a = Emparejador(self.PUERTO_A, lambda: {"id": "aa" * 16, "nombre": "ESCRITORIO",
                                                 "rol": "servidor"}, eventos_a)
        b = Emparejador(self.PUERTO_B, lambda: {"id": "bb" * 16, "nombre": "NOTEBOOK",
                                                 "rol": "cliente"}, eventos_b)
        self.assertTrue(a.iniciar(), a.error)
        self.assertTrue(b.iniciar(), b.error)
        self.addCleanup(a.detener)
        self.addCleanup(b.detener)
        self.assertTrue(a.emparejar_con("127.0.0.1", self.PUERTO_B))
        self.assertTrue(eventos_a.listo.wait(10))
        self.assertTrue(eventos_b.listo.wait(10))
        return eventos_a, eventos_b

    def test_si_las_dos_confirman_quedan_con_la_misma_clave(self):
        eventos_a, eventos_b = self._emparejar(demora_b=0.3)
        resultado_a, motivo_a = eventos_a.final
        resultado_b, motivo_b = eventos_b.final
        self.assertEqual((motivo_a, motivo_b), ("", ""))
        self.assertEqual(resultado_a.clave, resultado_b.clave)
        self.assertEqual(len(resultado_a.clave), 32)
        self.assertEqual((resultado_a.id_otra, resultado_a.nombre_otra, resultado_a.rol_otra),
                         ("bb" * 16, "NOTEBOOK", "cliente"))
        self.assertEqual(resultado_b.id_otra, "aa" * 16)
        # Las dos pantallas mostraron el mismo número de 6 cifras.
        self.assertEqual(eventos_a.codigos, eventos_b.codigos)
        self.assertRegex(eventos_a.codigos[0], r"^\d{3} \d{3}$")
        self.assertEqual(eventos_b.pedidos, ["ESCRITORIO"])

    def test_si_una_dice_que_no_coinciden_no_se_empareja(self):
        eventos_a, eventos_b = self._emparejar(decision_b=False)
        self.assertIsNone(eventos_a.final[0])
        self.assertIsNone(eventos_b.final[0])
        self.assertIn("no coinciden", eventos_a.final[1])

    def test_la_que_inicia_tambien_puede_cancelar(self):
        eventos_a, eventos_b = self._emparejar(decision_a=False, demora_b=0.5)
        self.assertIsNone(eventos_a.final[0])
        self.assertIsNone(eventos_b.final[0])

    def test_sin_programa_del_otro_lado_avisa(self):
        eventos = _Eventos()
        a = Emparejador(self.PUERTO_A, lambda: {"id": "aa" * 16, "nombre": "A", "rol": ""},
                        eventos)
        self.assertTrue(a.emparejar_con("127.0.0.1", 25899))  # Nadie escucha ahí.
        self.assertTrue(eventos.listo.wait(10))
        self.assertIsNone(eventos.final[0])
        self.assertIn("No se pudo conectar", eventos.final[1])

    def test_el_numero_depende_de_todo_lo_intercambiado(self):
        base = (bytes(64), bytes(range(64)), bytes(16), bytes(range(16)))
        codigo = codigo_de(*base)
        for i in range(4):
            cambiado = list(base)
            cambiado[i] = bytes([cambiado[i][0] ^ 1]) + cambiado[i][1:]
            self.assertNotEqual(codigo_de(*cambiado), codigo)


if __name__ == "__main__":
    unittest.main()
