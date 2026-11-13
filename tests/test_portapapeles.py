"""Portapapeles compartido: el formato, el canal de datos, el saludo y la parte de Qt.

Ninguna prueba toca el portapapeles real de Windows: se usa uno falso.
"""

import os
import socket
import threading
import time
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QMimeData, QObject, Signal
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    HAY_QT = True
except ImportError:  # pragma: no cover
    HAY_QT = False

from mouse_compartido.comun.config import Config
from mouse_compartido.comun.pantallas import IZQUIERDA
from mouse_compartido.datos import portapapeles as PP
from mouse_compartido.motor import cliente as modulo_cliente
from mouse_compartido.motor.cliente import Cliente
from mouse_compartido.motor.servidor import Servidor
from mouse_compartido.red import protocolo as P
from mouse_compartido.red.canal_datos import CABECERA, CanalDatos
from mouse_compartido.red.conexion import Conexion, ConexionCerrada
from mouse_compartido.red.seguridad import (
    CanalNoDisponible,
    autenticar_como_cliente,
    autenticar_como_servidor,
)
from tests.ayuda import EMP_CLIENTE, EMP_SERVIDOR, emparejada
from tests.test_integracion import CapturaFalsa, SalidaEspia

PNG_CHICO = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (640).to_bytes(4, "big")
             + (480).to_bytes(4, "big") + b"resto")


def par_de_sockets():
    oyente = socket.socket()
    oyente.bind(("127.0.0.1", 0))
    oyente.listen(1)
    a = socket.create_connection(oyente.getsockname())
    b, _ = oyente.accept()
    oyente.close()
    return a, b


def esperar(condicion, segundos=5.0, app=None):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if app is not None:
            app.processEvents()
        if condicion():
            return True
        time.sleep(0.005)
    return False


class FormatoTest(unittest.TestCase):
    def test_ida_y_vuelta(self):
        contenido = {PP.TEXTO: "hola ñandú".encode(), PP.HTML: b"<b>hola</b>", PP.RTF: b"",
                     PP.PNG: PNG_CHICO}
        self.assertEqual(PP.decodificar(PP.codificar(contenido)), contenido)

    def test_formato_desconocido_se_ignora(self):
        datos = PP.codificar({"futuro": b"x", PP.TEXTO: b"a"})
        self.assertEqual(PP.decodificar(datos), {PP.TEXTO: b"a"})

    def test_datos_danados(self):
        bien = PP.codificar({PP.TEXTO: b"abcdef"})
        for malo in (b"", bien[:-1], bien + b"x", b"\x01\x05tex"):
            with self.assertRaises(ValueError, msg=repr(malo)):
                PP.decodificar(malo)

    def test_describir(self):
        self.assertEqual(PP.describir({PP.TEXTO: "ñandú".encode()}), "texto (5 caracteres)")
        self.assertEqual(PP.describir({PP.TEXTO: b"a", PP.HTML: b"<b>a</b>"}),
                         "texto con formato (1 carácter)")
        self.assertEqual(PP.describir({PP.PNG: PNG_CHICO}), "una imagen de 640×480 (29 bytes)")
        self.assertEqual(PP.texto_peso(int(2.1 * 1024 * 1024)), "2,1 MB")

    def _partes_html(self, datos):
        """Lee la cabecera de "HTML Format" y devuelve (documento, fragmento)."""
        cabecera = dict(
            linea.split(":", 1) for linea in datos.split(b"<", 1)[0].decode().split("\r\n") if linea
        )
        numeros = {clave: int(valor) for clave, valor in cabecera.items() if clave != "Version"}
        documento = datos[numeros["StartHTML"]:numeros["EndHTML"]]
        fragmento = datos[numeros["StartFragment"]:numeros["EndFragment"]]
        self.assertEqual(numeros["EndHTML"], len(datos))
        return documento, fragmento

    def test_html_para_windows(self):
        documento, fragmento = self._partes_html(PP.html_para_windows("<b>¡hola!</b>".encode()))
        self.assertEqual(fragmento, "<b>¡hola!</b>".encode())
        self.assertTrue(documento.startswith(b"<html>"))

        _, fragmento = self._partes_html(
            PP.html_para_windows(b"<html><BODY class='x'><p>uno</p></body></html>"))
        self.assertEqual(fragmento, b"<p>uno</p>")

        con_marcas = b"<html><body>antes<!--StartFragment--><i>dos</i><!--EndFragment--></body></html>"
        documento, fragmento = self._partes_html(PP.html_para_windows(con_marcas))
        self.assertEqual((documento, fragmento), (con_marcas, b"<i>dos</i>"))

    def test_privacidad(self):
        leer = {"x;value=\"CanUploadToCloudClipboard\"": b"\0\0\0\0"}.get
        self.assertTrue(PP.pide_privacidad(['x;value="CanUploadToCloudClipboard"'], leer))
        self.assertTrue(PP.pide_privacidad(
            ['a;value="ExcludeClipboardContentFromMonitorProcessing"'], lambda f: b""))
        si_nube = {"x;value=\"CanUploadToCloudClipboard\"": b"\1\0\0\0"}.get
        self.assertFalse(PP.pide_privacidad(['x;value="CanUploadToCloudClipboard"'], si_nube))
        self.assertFalse(PP.pide_privacidad(["text/plain"], lambda f: b""))


class CanalDatosTest(unittest.TestCase):
    def _par(self):
        a, b = par_de_sockets()
        self.recibidos_a, self.recibidos_b = [], []
        self.cortes = []
        canal_a = CanalDatos(a, lambda t, c: self.recibidos_a.append((t, c)),
                             lambda: self.cortes.append("a"))
        canal_b = CanalDatos(b, lambda t, c: self.recibidos_b.append((t, c)),
                             lambda: self.cortes.append("b"))
        self.addCleanup(canal_a.cerrar)
        self.addCleanup(canal_b.cerrar)
        return canal_a, canal_b

    def test_mensajes_chicos_y_grandes_en_orden(self):
        canal_a, canal_b = self._par()
        grande = os.urandom(8 * 1024 * 1024)
        canal_a.enviar(P.Tipo.PORTAPAPELES, b"uno")
        canal_a.enviar(P.Tipo.PORTAPAPELES, grande)
        canal_a.enviar(P.Tipo.PORTAPAPELES, b"")
        canal_b.enviar(7, b"al reves")
        self.assertTrue(esperar(lambda: len(self.recibidos_b) == 3, 10))
        self.assertEqual(self.recibidos_b, [(P.Tipo.PORTAPAPELES, b"uno"),
                                            (P.Tipo.PORTAPAPELES, grande),
                                            (P.Tipo.PORTAPAPELES, b"")])
        self.assertTrue(esperar(lambda: self.recibidos_a == [(7, b"al reves")]))

    def test_corte_del_otro_lado_avisa_y_cerrar_a_proposito_no(self):
        canal_a, canal_b = self._par()
        canal_a.cerrar()
        self.assertTrue(esperar(lambda: self.cortes == ["b"]))
        self.assertTrue(canal_b.cerrado)
        self.assertFalse(canal_b.enviar(1, b"x"))
        time.sleep(0.05)
        self.assertEqual(self.cortes, ["b"])

    def test_mensaje_que_dice_medir_demasiado_corta(self):
        a, b = par_de_sockets()
        cortes = []
        canal = CanalDatos(b, lambda t, c: None, lambda: cortes.append(1))
        self.addCleanup(canal.cerrar)
        a.sendall(CABECERA.pack(200 * 1024 * 1024, 1))
        self.assertTrue(esperar(lambda: cortes == [1]))
        a.close()


class SaludoDatosTest(unittest.TestCase):
    def _saludo(self, canales, canal_cliente):
        a, b = par_de_sockets()
        servidor, cliente = Conexion(a), Conexion(b)
        self.addCleanup(servidor.cerrar)
        self.addCleanup(cliente.cerrar)
        resultado = {}

        def lado_servidor():
            try:
                resultado["canal"] = autenticar_como_servidor(
                    servidor, EMP_SERVIDOR, IZQUIERDA, timeout=2, canales=canales).canal
            except Exception as error:  # noqa: BLE001 - la prueba quiere ver cuál fue
                resultado["error"] = error
                servidor.cerrar()

        hilo = threading.Thread(target=lado_servidor)
        hilo.start()
        try:
            autenticar_como_cliente(cliente, EMP_CLIENTE, timeout=2, canal=canal_cliente)
        except Exception as error:  # noqa: BLE001
            resultado["error_cliente"] = error
        hilo.join(5)
        return resultado, cliente

    def test_canal_de_datos_aceptado(self):
        resultado, cliente = self._saludo((P.CANAL_DATOS,), P.CANAL_DATOS)
        self.assertEqual(resultado.get("canal"), P.CANAL_DATOS)
        sock = cliente.entregar_socket()
        self.assertTrue(cliente.cerrada)
        self.assertIsNone(sock.gettimeout())  # Bloqueante, listo para el canal de datos.
        sock.close()

    def test_canal_de_datos_cuando_no_corresponde_se_corta_sin_responder(self):
        resultado, _ = self._saludo((P.CANAL_ENTRADA,), P.CANAL_DATOS)
        self.assertIsInstance(resultado["error"], CanalNoDisponible)
        self.assertIsInstance(resultado["error_cliente"], (ConexionCerrada, TimeoutError))
        self.assertNotIsInstance(resultado["error_cliente"], CanalNoDisponible)

    def test_canal_desconocido_avisa_que_falta_actualizar(self):
        resultado, _ = self._saludo((P.CANAL_ENTRADA, P.CANAL_DATOS), 9)
        self.assertIsInstance(resultado["error"], CanalNoDisponible)
        self.assertIsInstance(resultado["error_cliente"], CanalNoDisponible)
        self.assertIn("actualizala", str(resultado["error_cliente"]))

    def test_no_se_entrega_un_socket_con_datos_a_medias(self):
        a, b = par_de_sockets()
        conexion = Conexion(b)
        a.sendall(b"\x05\x00")  # Mitad de un marco.
        self.assertEqual(conexion.recibir(1), [])
        with self.assertRaises(ConexionCerrada):
            conexion.entregar_socket()
        a.close()


class MotorConCanalDatosTest(unittest.TestCase):
    """Servidor y cliente reales (sin mouse): los dos lados reciben el canal de datos."""

    PUERTO = 24993

    def setUp(self):
        comunes = dict(puerto=self.PUERTO, ip_servidor="127.0.0.1", max_envios_mouse_hz=0,
                       esquinas_muertas_px=0, enfriamiento_ms=0, mostrar_latencia=False)
        self.config_servidor = Config(**emparejada("servidor", **comunes))
        self.config = Config(**emparejada("cliente", **comunes))

    def _arrancar(self, entregar_servidor, entregar_cliente):
        captura = CapturaFalsa(self.config_servidor)
        servidor = Servidor(self.config_servidor, captura=captura,
                            entregar_canal=entregar_servidor)
        hilo_s = threading.Thread(target=servidor.correr, daemon=True)
        hilo_s.start()
        self.assertTrue(servidor.escuchando.wait(5))
        cliente = Cliente(self.config, salida=SalidaEspia(), entregar_canal=entregar_cliente)
        hilo_c = threading.Thread(target=cliente.correr, daemon=True)
        hilo_c.start()

        def parar():
            cliente.detener()
            servidor.detener()
            hilo_c.join(5)
            hilo_s.join(5)

        self.addCleanup(parar)
        self.assertTrue(captura.conectado.wait(5))
        return servidor, cliente

    def test_los_dos_lados_reciben_el_canal_y_se_hablan(self):
        del_servidor, del_cliente = [], []
        _, cliente = self._arrancar(lambda s, c: del_servidor.append((s, c)),
                                    lambda s, c: del_cliente.append((s, c)))
        self.assertTrue(esperar(lambda: del_servidor and del_cliente))
        # Cada lado recibe sus claves de cifrado: lo que uno manda, el otro lo descifra.
        (sock_s, claves_s), (sock_c, claves_c) = del_servidor[0], del_cliente[0]
        self.assertEqual(claves_s.envio, claves_c.recepcion)
        recibidos = []
        canal_s = CanalDatos(sock_s, lambda t, c: recibidos.append(("s", t, c)),
                             claves=(claves_s.envio, claves_s.recepcion))
        canal_c = CanalDatos(sock_c, lambda t, c: recibidos.append(("c", t, c)),
                             claves=(claves_c.envio, claves_c.recepcion))
        self.addCleanup(canal_s.cerrar)
        self.addCleanup(canal_c.cerrar)
        canal_c.enviar(P.Tipo.PORTAPAPELES, b"desde el cliente")
        canal_s.enviar(P.Tipo.PORTAPAPELES, b"desde el servidor")
        self.assertTrue(esperar(lambda: len(recibidos) == 2))
        self.assertIn(("s", P.Tipo.PORTAPAPELES, b"desde el cliente"), recibidos)
        self.assertIn(("c", P.Tipo.PORTAPAPELES, b"desde el servidor"), recibidos)

        # Si la interfaz pide otro (porque se cortó), llega uno nuevo a cada lado.
        cliente.pedir_canal_datos()
        self.assertTrue(esperar(lambda: len(del_servidor) == 2 and len(del_cliente) == 2))
        for sock, _ in del_servidor[1:] + del_cliente[1:]:
            sock.close()

    def test_sin_interfaz_en_el_servidor_el_cliente_se_rinde_sin_romper_el_mouse(self):
        espera_original = modulo_cliente._ESPERA_REINTENTO_S
        modulo_cliente._ESPERA_REINTENTO_S = 0.05
        self.addCleanup(setattr, modulo_cliente, "_ESPERA_REINTENTO_S", espera_original)
        del_cliente = []
        _, cliente = self._arrancar(None, lambda s, c: del_cliente.append((s, c)))
        self.assertTrue(esperar(lambda: cliente._conexion is not None))
        self.assertTrue(esperar(lambda: not cliente._abriendo_canal.locked(), 8))
        time.sleep(0.2)
        self.assertEqual(del_cliente, [])
        self.assertIsNotNone(cliente._conexion, "La sesión del mouse tiene que seguir")


@unittest.skipUnless(HAY_QT, "PySide6 no está instalado")
class QtPortapapelesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_leer_y_armar_ida_y_vuelta(self):
        from mouse_compartido.ui.portapapeles import MARCA, _RTF, armar_mime, leer_mime

        imagen = QImage(32, 16, QImage.Format_ARGB32)
        imagen.fill(QColor(10, 200, 30))
        mime = QMimeData()
        mime.setText("hola ñandú")
        mime.setHtml("<b>hola</b>")
        mime.setData(_RTF, b"{\\rtf1 hola}")
        mime.setImageData(imagen)
        contenido, motivo = leer_mime(mime)
        self.assertEqual(motivo, "")
        self.assertEqual(contenido[PP.TEXTO], "hola ñandú".encode())
        self.assertIn(b"<b>hola</b>", contenido[PP.HTML])
        self.assertEqual(contenido[PP.RTF], b"{\\rtf1 hola}")
        self.assertEqual(PP.medidas_png(contenido[PP.PNG]), (32, 16))

        armado = armar_mime(contenido)
        self.assertIn(MARCA, armado.formats())
        self.assertEqual(armado.text(), "hola ñandú")
        self.assertEqual(armado.imageData().size().toTuple(), (32, 16))
        self.assertEqual(leer_mime(armado), (None, ""), "Lo que llegó no se reenvía")

    def test_imagen_al_formato_clasico_de_windows(self):
        from PySide6.QtCore import QBuffer, QIODevice

        from mouse_compartido.ui.portapapeles import dib_de_png

        imagen = QImage(2, 2, QImage.Format_ARGB32)
        imagen.setPixelColor(0, 0, QColor(255, 0, 0))  # Arriba: rojo y verde.
        imagen.setPixelColor(1, 0, QColor(0, 255, 0))
        imagen.setPixelColor(0, 1, QColor(0, 0, 255))  # Abajo: azul y blanco.
        imagen.setPixelColor(1, 1, QColor(255, 255, 255))
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        imagen.save(buffer, "PNG")
        dib = dib_de_png(bytes(buffer.data()))
        self.assertEqual(len(dib), 40 + 2 * 2 * 4)
        tamanio, ancho, alto, planos, bits = __import__("struct").unpack_from("<IiiHH", dib)
        self.assertEqual((tamanio, ancho, alto, planos, bits), (40, 2, 2, 1, 32))
        # Primero la fila de abajo. Cada píxel: azul, verde, rojo, libre.
        self.assertEqual(dib[40:], bytes([255, 0, 0, 255, 255, 255, 255, 255,
                                          0, 0, 255, 255, 0, 255, 0, 255]))
        self.assertEqual(dib_de_png(b"no es un png"), b"")

    def test_lo_que_no_se_manda(self):
        from mouse_compartido.ui.portapapeles import MOTIVO_ARCHIVOS, MOTIVO_PRIVADO, leer_mime

        privado = QMimeData()
        privado.setText("mi-clave")
        privado.setData(
            'application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"',
            b"\0")
        self.assertEqual(leer_mime(privado), (None, MOTIVO_PRIVADO))

        from PySide6.QtCore import QUrl

        archivos = QMimeData()
        archivos.setUrls([QUrl.fromLocalFile("C:/x.txt")])
        archivos.removeFormat("text/plain")
        self.assertEqual(leer_mime(archivos), (None, MOTIVO_ARCHIVOS))
        self.assertEqual(leer_mime(QMimeData()), (None, ""))


if HAY_QT:

    class PortapapelesFalso(QObject):
        """Hace de QClipboard: avisa cada cambio, igual que el de Windows."""

        dataChanged = Signal()

        def __init__(self):
            super().__init__()
            self._mime = QMimeData()

        def mimeData(self):
            return self._mime

        def setMimeData(self, mime):
            self._mime = mime
            self.dataChanged.emit()

        def copiar_texto(self, texto):
            mime = QMimeData()
            mime.setText(texto)
            self.setMimeData(mime)


@unittest.skipUnless(HAY_QT, "PySide6 no está instalado")
class SincroPortapapelesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from mouse_compartido.ui.enlace import EnlaceDatos
        from mouse_compartido.ui.portapapeles import SincroPortapapeles, armar_mime

        self.portapapeles = PortapapelesFalso()
        self.pedidos = []
        self.enlace = EnlaceDatos(pedir_canal=lambda: self.pedidos.append("canal"))
        self.sincro = SincroPortapapeles(
            self.portapapeles, Config(), self.enlace,
            poner=lambda contenido: self.portapapeles.setMimeData(armar_mime(contenido)),
        )
        self.registro = []
        self.sincro.nuevo_registro.connect(self.registro.append)
        self.archivos_copiados = []
        self.sincro.archivos_copiados.connect(self.archivos_copiados.append)
        self.copias_locales = []
        self.sincro.copiado_local.connect(lambda: self.copias_locales.append(1))
        nuestro, otra_pc = par_de_sockets()
        self.otra_pc_recibio = []
        self.otra_pc = CanalDatos(otra_pc, lambda t, c: self.otra_pc_recibio.append((t, c)))
        self.addCleanup(self.otra_pc.cerrar)
        self.enlace.conexion_cambiada(True)
        self.enlace.usar_canal(nuestro)
        self.addCleanup(self.enlace.soltar)

    def _esperar(self, condicion, segundos=3.0):
        return esperar(condicion, segundos, self.app)

    def test_lo_copiado_aca_llega_a_la_otra_pc(self):
        self.portapapeles.copiar_texto("primero")
        self.portapapeles.copiar_texto("segundo")  # Dos cambios seguidos: se manda uno solo.
        self.assertTrue(self._esperar(lambda: self.otra_pc_recibio))
        self._esperar(lambda: False, 0.3)
        self.assertEqual(len(self.otra_pc_recibio), 1)
        tipo, cuerpo = self.otra_pc_recibio[0]
        self.assertEqual(tipo, P.Tipo.PORTAPAPELES)
        self.assertEqual(PP.decodificar(cuerpo), {PP.TEXTO: b"segundo"})
        self.assertIn("Pasó a la otra PC: texto (7 caracteres).", self.registro[-1])

    def test_lo_que_llega_se_pega_aca_y_no_rebota(self):
        self.otra_pc.enviar(P.Tipo.PORTAPAPELES, PP.codificar({PP.TEXTO: "de allá".encode()}))
        self.assertTrue(self._esperar(lambda: self.portapapeles.mimeData().text() == "de allá"))
        self._esperar(lambda: False, 0.4)  # Más que la espera antes de mandar.
        self.assertEqual(self.otra_pc_recibio, [], "No se tiene que devolver a la otra PC")
        self.assertIn("Ya podés pegarlo", self.registro[-1])

    def test_apagado_no_manda_ni_pega(self):
        self.sincro.poner_config(replace(Config(), compartir_portapapeles=False))
        self.portapapeles.copiar_texto("no")
        self.otra_pc.enviar(P.Tipo.PORTAPAPELES, PP.codificar({PP.TEXTO: b"tampoco"}))
        self.assertTrue(self._esperar(lambda: any("apagado" in r for r in self.registro)))
        self.assertEqual(self.portapapeles.mimeData().text(), "no")
        self.assertEqual(self.otra_pc_recibio, [])

    def test_lo_que_pesa_demasiado_no_se_manda(self):
        self.sincro.poner_config(replace(Config(), portapapeles_max_mb=1))
        self.portapapeles.copiar_texto("x" * (2 * 1024 * 1024))
        self.assertTrue(self._esperar(lambda: any("tope" in r for r in self.registro)))
        self.assertEqual(self.otra_pc_recibio, [])

    def test_si_se_corta_el_canal_pide_otro_y_al_desconectar_lo_suelta(self):
        self.enlace._reintento.setInterval(20)
        self.otra_pc.cerrar()
        self.assertTrue(self._esperar(lambda: not self.sincro.listo))
        self.assertTrue(self._esperar(lambda: self.pedidos == ["canal"]))
        self.enlace.conexion_cambiada(False)
        self.assertFalse(self.sincro.listo)

    def test_archivos_copiados_se_avisan_y_no_viajan_como_texto(self):
        from PySide6.QtCore import QUrl

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile("C:/carpeta/foto.jpg")])
        self.portapapeles.setMimeData(mime)
        self.assertTrue(self._esperar(lambda: self.archivos_copiados))
        self.assertEqual([r.replace("\\", "/") for r in self.archivos_copiados[0]],
                         ["C:/carpeta/foto.jpg"])
        self.assertEqual(self.copias_locales, [1])
        self._esperar(lambda: False, 0.3)
        self.assertEqual(self.otra_pc_recibio, [], "Los archivos van por ui/archivos.py")

    def test_lo_que_pone_el_programa_no_cuenta_como_copia_local(self):
        self.otra_pc.enviar(P.Tipo.PORTAPAPELES, PP.codificar({PP.TEXTO: b"llego"}))
        self.assertTrue(self._esperar(lambda: self.portapapeles.mimeData().text() == "llego"))
        self._esperar(lambda: False, 0.3)
        self.assertEqual(self.copias_locales, [])


class FormatoArchivosTest(unittest.TestCase):
    def test_cf_hdrop_como_el_explorador(self):
        import struct

        from mouse_compartido.sistema import portapapeles as PW
        from mouse_compartido.ui.portapapeles import formatos_de_archivos

        formatos = dict(formatos_de_archivos(["C:\\a\\uno.txt", "C:\\b\\dos"]))
        hdrop = formatos[PW.CF_HDROP]
        desplazamiento, x, y, no_cliente, anchos = struct.unpack_from("<IiiII", hdrop)
        self.assertEqual((desplazamiento, anchos), (20, 1))  # Rutas en UTF-16.
        rutas = hdrop[20:].decode("utf-16-le")
        self.assertEqual(rutas, "C:\\a\\uno.txt\0C:\\b\\dos\0\0")


if __name__ == "__main__":
    unittest.main()
