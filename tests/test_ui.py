"""Pruebas de la interfaz. Corren sin mostrar ventanas (plataforma "offscreen" de Qt).

Si PySide6 no está instalado, se saltean.
"""

import json
import os
import tempfile
import threading
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    HAY_QT = True
except ImportError:  # pragma: no cover
    HAY_QT = False

from mouse_compartido.comun.config import Config
from mouse_compartido.comun.pantallas import ABAJO, ARRIBA, DERECHA, IZQUIERDA, Monitor, Pantallas
from mouse_compartido.ui import resumen as R
from mouse_compartido.ui.geometria import escala_para, lado_mas_cercano, posicion_pegada


class ResumenTest(unittest.TestCase):
    def test_detenido_y_error(self):
        self.assertEqual(R.resumir(False, {}).clave, R.DETENIDO)
        error = R.resumir(False, {}, "PIN incorrecto")
        self.assertEqual((error.clave, error.detalle), (R.ERROR, "PIN incorrecto"))
        self.assertEqual(R.resumir(True, {"estado": "error", "detalle": "x"}).clave, R.ERROR)

    def test_conectado_muestra_nombre_e_ip(self):
        datos = {"estado": "conectado", "otra_pc": {"nombre": "NOTEBOOK", "ip": "192.168.1.8"}}
        r = R.resumir(True, datos)
        self.assertEqual(r.clave, R.CONECTADO)
        self.assertIn("NOTEBOOK (192.168.1.8)", r.detalle)

    def test_pausas(self):
        base = {"estado": "conectado", "otra_pc": {"nombre": "N"}}
        self.assertEqual(R.resumir(True, {**base, "pausa_local": True}).clave, R.PAUSADO)
        self.assertIn("otra PC", R.resumir(True, {**base, "pausa_otra": True}).titulo)

    def test_esperando_y_buscando(self):
        self.assertEqual(R.resumir(True, {"estado": "esperando"}).clave, R.ESPERANDO)
        self.assertEqual(R.resumir(True, {"estado": "conectando"}).titulo, "Buscando a la otra PC")
        self.assertEqual(R.resumir(True, {}).clave, R.ESPERANDO)

    def test_donde_esta_el_mouse(self):
        datos = {"estado": "conectado", "mouse_aca": False, "otra_pc": {"nombre": "N"}}
        self.assertEqual(R.donde_esta_el_mouse(datos), "En N")
        self.assertEqual(R.donde_esta_el_mouse({**datos, "mouse_aca": True}), "En esta PC")


class GeometriaTest(unittest.TestCase):
    CAJA = (100, 100, 200, 100)  # Esta PC: de (100,100) a (300,200).

    def test_lado_por_el_centro(self):
        tam = (100, 60)
        self.assertEqual(lado_mas_cercano(self.CAJA, (400, 150), tam), DERECHA)
        self.assertEqual(lado_mas_cercano(self.CAJA, (20, 160), tam), IZQUIERDA)
        self.assertEqual(lado_mas_cercano(self.CAJA, (200, 10), tam), ARRIBA)
        self.assertEqual(lado_mas_cercano(self.CAJA, (220, 260), tam), ABAJO)

    def test_diagonal_gana_el_eje_mas_alejado(self):
        self.assertEqual(lado_mas_cercano(self.CAJA, (330, 300), (100, 60)), ABAJO)

    def test_pegada_y_centrada(self):
        self.assertEqual(posicion_pegada(self.CAJA, (100, 60), DERECHA, 5), (305, 120))
        self.assertEqual(posicion_pegada(self.CAJA, (100, 60), IZQUIERDA, 5), (-5, 120))
        self.assertEqual(posicion_pegada(self.CAJA, (100, 60), ARRIBA, 5), (150, 35))
        self.assertEqual(posicion_pegada(self.CAJA, (100, 60), ABAJO, 5), (150, 205))

    def test_la_escala_deja_lugar_en_los_cuatro_lados(self):
        escala = escala_para((600, 300), (1920, 1080), (1366, 768), 10)
        self.assertLessEqual((1920 + 2 * 1366) * escala, 580 + 1e-6)
        self.assertLessEqual((1080 + 2 * 768) * escala, 280 + 1e-6)


@unittest.skipUnless(HAY_QT, "PySide6 no está instalado")
class InterfazTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from mouse_compartido.ui import estilo

        estilo.aplicar(cls.app)

    def _arrastrar(self, vista, desde, hasta):
        """Simula agarrar con el mouse, mover y soltar dentro del editor."""
        destino = vista.viewport()
        for tipo, punto, botones in (
            (QEvent.MouseButtonPress, desde, Qt.LeftButton),
            (QEvent.MouseMove, (desde + hasta) / 2, Qt.LeftButton),
            (QEvent.MouseMove, hasta, Qt.LeftButton),
            (QEvent.MouseButtonRelease, hasta, Qt.NoButton),
        ):
            evento = QMouseEvent(tipo, punto, destino.mapToGlobal(punto), Qt.LeftButton,
                                 botones, Qt.NoModifier)
            QApplication.sendEvent(destino, evento)
            self.app.processEvents()

    def test_arrastrar_la_otra_pc_cambia_el_lado(self):
        from mouse_compartido.ui.editor_pantallas import EditorPantallas

        editor = EditorPantallas()
        editor.resize(700, 320)
        editor.show()
        self.app.processEvents()
        editor.configurar(Pantallas([Monitor(0, 0, 1920, 1080)]),
                          Pantallas([Monitor(0, 0, 1366, 768)]), "ESTA", "OTRA", DERECHA, True)
        avisos = []
        editor.lado_cambiado.connect(avisos.append)

        otra = editor._bloque_otra
        centro = editor.mapFromScene(otra.sceneBoundingRect().center())
        esta = editor._bloque_esta.sceneBoundingRect()
        izquierda = editor.mapFromScene(QPointF(esta.left() - 40, esta.center().y()))
        self._arrastrar(editor, QPointF(centro), QPointF(izquierda))
        self.assertEqual(avisos, [IZQUIERDA])
        self.assertEqual(editor.lado, IZQUIERDA)

        editor._animacion.setCurrentTime(editor._animacion.duration())  # Termina la animación.
        self.app.processEvents()
        self.assertLess(otra.sceneBoundingRect().right(), esta.left() + 1,
                        "Tiene que quedar pegada a la izquierda")
        editor.close()

    def test_no_editable_no_se_mueve(self):
        from mouse_compartido.ui.editor_pantallas import EditorPantallas

        editor = EditorPantallas()
        editor.resize(700, 320)
        editor.show()
        self.app.processEvents()
        editor.configurar(Pantallas([Monitor(0, 0, 1920, 1080)]), None, "E", "", ARRIBA, False)
        antes = editor._bloque_otra.pos()
        centro = editor.mapFromScene(editor._bloque_otra.sceneBoundingRect().center())
        self._arrastrar(editor, QPointF(centro), QPointF(centro) + QPointF(0, 200))
        self.assertEqual(editor._bloque_otra.pos(), antes)
        editor.close()

    def test_formulario_ida_y_vuelta_y_barra_de_cambios(self):
        from mouse_compartido.ui.ventana import VentanaPrincipal

        config = Config(rol="cliente", pin="abcd1234", ip_servidor="192.168.1.28",
                        carpeta_compartida="C:\\X", enfriamiento_ms=150)
        ventana = VentanaPrincipal(config)
        self.assertEqual(ventana._leer_formulario(), config)
        self.assertTrue(ventana.barra_guardar.isHidden())

        ventana.campo_pin.setText("otro-pin")
        self.assertFalse(ventana.barra_guardar.isHidden())
        ventana.campo_pin.setText("abcd1234")  # Volver al valor guardado esconde la barra.
        self.assertTrue(ventana.barra_guardar.isHidden())

        guardadas = []
        ventana.config_guardada.connect(guardadas.append)
        ventana._al_elegir_rol("servidor")
        ventana._al_elegir_lado(ABAJO, desde_boton=True)
        ventana._guardar()
        self.assertEqual(guardadas[-1].rol, "servidor")
        self.assertEqual(guardadas[-1].lado_otra_pantalla, ABAJO)
        ventana.deleteLater()

    def test_estado_en_botones(self):
        from mouse_compartido.ui.ventana import VentanaPrincipal

        ventana = VentanaPrincipal(Config(rol="servidor", pin="abcd1234"))
        ventana.mostrar_estado(False, {}, "")
        self.assertTrue(ventana.boton_iniciar.isEnabled())
        self.assertFalse(ventana.boton_pausar.isEnabled())
        ventana.mostrar_estado(True, {"estado": "conectado", "pausa_local": True}, "")
        self.assertFalse(ventana.boton_iniciar.isEnabled())
        self.assertIn("Reanudar", ventana.boton_pausar.text())
        self.assertEqual(ventana.titulo_estado.text(), "En pausa")
        ventana.deleteLater()

    def test_control_motor_de_punta_a_punta(self):
        """La interfaz arranca el motor real, lo pausa y lo detiene."""
        from mouse_compartido.motor.servidor import Servidor
        from mouse_compartido.ui.control_motor import ControlMotor
        from tests.test_integracion import CapturaFalsa

        config = Config(rol="cliente", puerto=24995, pin="prueba-ui", ip_servidor="127.0.0.1",
                        enfriamiento_ms=0, esquinas_muertas_px=0)
        captura = CapturaFalsa(config)
        servidor = Servidor(replace(config, rol="servidor"), captura=captura)
        hilo = threading.Thread(target=servidor.correr, daemon=True)
        hilo.start()
        self.assertTrue(servidor.escuchando.wait(5))
        self.addCleanup(lambda: (servidor.detener(), hilo.join(5)))

        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        ruta = Path(carpeta.name) / "config.json"
        ruta.write_text(json.dumps(asdict(config)), encoding="utf-8")
        control = ControlMotor(ruta)
        registro = []
        control.nuevo_registro.connect(registro.append)

        def esperar(condicion, segundos=8):
            limite = time.monotonic() + segundos
            while time.monotonic() < limite:
                self.app.processEvents()
                if condicion():
                    return True
                time.sleep(0.01)
            return False

        control.iniciar()
        self.assertTrue(esperar(lambda: (control.datos.get("otra_pc") or {}).get("nombre")),
                        "\n".join(registro))
        self.assertEqual(control.datos["estado"], "conectado")
        control.pausar()
        self.assertTrue(esperar(lambda: control.datos.get("pausa_local")))
        self.assertTrue(esperar(lambda: captura.logica.pausa_remota))
        control.detener()
        self.assertTrue(esperar(lambda: not control.activo))
        self.assertEqual(control.error, "")
        self.assertTrue(captura.desconectado.wait(5))


if __name__ == "__main__":
    unittest.main()
