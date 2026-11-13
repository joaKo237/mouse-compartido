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
    from PySide6.QtWidgets import QApplication, QPushButton

    HAY_QT = True
except ImportError:  # pragma: no cover
    HAY_QT = False

from mouse_compartido.comun.config import Config
from mouse_compartido.comun.pantallas import ABAJO, ARRIBA, DERECHA, IZQUIERDA, Monitor, Pantallas
from mouse_compartido.ui import resumen as R
from mouse_compartido.ui.geometria import escala_para, lado_mas_cercano, posicion_pegada
from tests.ayuda import emparejada


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
        self.assertIn("por cable", R.resumir(True, {**datos, "ruta": "cable"}).detalle)
        self.assertNotIn("por", R.resumir(True, {**datos, "ruta": "red"}).detalle)

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

        config = Config(**emparejada(
            "cliente", ip_servidor="192.168.1.28", carpeta_compartida="C:\\X",
            enfriamiento_ms=150, tecla_cambiar="pausa", luz_otra_pc=False,
            multimedia_pc_activa=False, archivos_max_mb=100, carpeta_recibidos="C:\\R",
            sincronizar_carpeta=True, atajo_cambiar=False))
        ventana = VentanaPrincipal(config)
        self.assertEqual(ventana._leer_formulario(), config)
        self.assertTrue(ventana.barra_guardar.isHidden())
        self.assertFalse(ventana.fila_ip_fija.isHidden())  # En el cliente se ve la IP fija.

        ventana.campo_ip.setText("10.0.0.1")
        self.assertFalse(ventana.barra_guardar.isHidden())
        ventana.campo_ip.setText("192.168.1.28")  # Volver al valor guardado esconde la barra.
        self.assertTrue(ventana.barra_guardar.isHidden())
        ventana.combo_tecla.setCurrentIndex(0)
        self.assertEqual(ventana._leer_formulario().tecla_cambiar, "bloq_despl")
        ventana.combo_tecla.setCurrentIndex(1)

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

        ventana = VentanaPrincipal(Config(rol="servidor"))
        ventana.mostrar_estado(False, {}, "")
        self.assertTrue(ventana.boton_iniciar.isEnabled())
        self.assertFalse(ventana.boton_pausar.isEnabled())
        ventana.mostrar_estado(True, {"estado": "conectado", "pausa_local": True}, "")
        self.assertFalse(ventana.boton_iniciar.isEnabled())
        self.assertIn("Reanudar", ventana.boton_pausar.text())
        self.assertEqual(ventana.titulo_estado.text(), "En pausa")
        ventana.deleteLater()

    def test_estado_del_portapapeles(self):
        from mouse_compartido.ui.ventana import VentanaPrincipal

        ventana = VentanaPrincipal(Config(rol="servidor"))
        ventana.mostrar_portapapeles(True, True, True)
        self.assertIn("Listo", ventana.estado_portapapeles.text())
        ventana.mostrar_portapapeles(True, False, False)
        self.assertIn("conectadas", ventana.estado_portapapeles.text())
        ventana.mostrar_portapapeles(False, True, True)
        self.assertIn("Apagado", ventana.estado_portapapeles.text())
        ventana.int_portapapeles.setChecked(False)
        self.assertFalse(ventana.barra_guardar.isHidden())
        self.assertFalse(ventana._leer_formulario().compartir_portapapeles)
        ventana.deleteLater()

    def test_la_red_y_la_pc_emparejada_en_la_ventana(self):
        from mouse_compartido.red.descubrimiento import PcVista
        from mouse_compartido.ui.ventana import VentanaPrincipal

        sin_pareja = VentanaPrincipal(Config(rol="servidor", id_pc="11" * 16))
        pedidos = []
        sin_pareja.emparejar_pedido.connect(pedidos.append)
        self.assertTrue(sin_pareja.boton_olvidar.isHidden())
        notebook = PcVista("22" * 16, "NOTEBOOK", "cliente", 24850, "", 3,
                           {"10.0.0.2": (0, 1.0), "192.168.1.8": (1, 1.0)})
        sin_pareja.mostrar_red([notebook], None)
        botones = [b for b in sin_pareja.findChildren(QPushButton) if b.text() == "Emparejar"
                   and b.parent() is not None and b.parent().objectName() == "FilaPc"]
        self.assertEqual(len(botones), 1)
        botones[0].click()
        self.assertEqual(pedidos, ["10.0.0.2"], "Por cable, que es el mejor camino")
        sin_pareja.campo_ip_emparejar.setText("192.168.1.99")
        sin_pareja._emparejar_por_ip()
        self.assertEqual(pedidos[-1], "192.168.1.99")

        con_pareja = VentanaPrincipal(Config(**emparejada("servidor", emparejado_nombre="NOTEBOOK")))
        con_pareja.mostrar_red([notebook], notebook, "Ojo con algo")
        self.assertFalse(con_pareja.boton_olvidar.isHidden())
        self.assertIn("por cable (10.0.0.2)", con_pareja.estado_pareja.text())
        self.assertEqual(con_pareja.aviso_pareja.text(), "Ojo con algo")
        con_pareja.mostrar_red([], None)
        self.assertIn("No se la ve", con_pareja.estado_pareja.text())
        for ventana in (sin_pareja, con_pareja):
            ventana.deleteLater()

    def _aplicacion(self, **campos):
        """La app completa con un config.json temporal, sin tocar Windows (firewall,
        "Enviar a") ni molestar a una copia del programa abierta en esta PC."""
        from mouse_compartido.ui import app as modulo_app
        from mouse_compartido.ui import instancia

        for modulo, nombre, valor in (
            (instancia, "NOMBRE", f"MouseCompartido-prueba-{os.getpid()}"),
            (modulo_app.firewall, "asegurar", lambda puerto: (False, "")),
            (modulo_app.enviar_a, "existe", lambda: True),
            (modulo_app.enviar_a, "quitar", lambda: None),
        ):
            self.addCleanup(setattr, modulo, nombre, getattr(modulo, nombre))
            setattr(modulo, nombre, valor)
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        ruta = Path(carpeta.name) / "config.json"
        ruta.write_text(json.dumps(asdict(Config(conectar_al_abrir=False, puerto=25990, **campos))),
                        encoding="utf-8")
        aplicacion = modulo_app.Aplicacion(self.app, ruta, en_bandeja=True)

        def limpiar():  # Usa `aplicacion`: así sigue viva hasta acá.
            aplicacion.motor._proceso = None
            aplicacion.red.detener()
            aplicacion.archivos.detener()
            aplicacion.enlace.soltar()
            aplicacion.bandeja.esconder()
            aplicacion._reloj_carpeta.stop()
            aplicacion._servidor_instancia.close()

        self.addCleanup(limpiar)
        return aplicacion, ruta

    def test_la_aplicacion_conecta_el_canal_de_datos_con_el_motor(self):
        """El canal que pasa el motor llega al portapapeles (y a la ventana)."""
        import socket as modulo_socket

        aplicacion, ruta = self._aplicacion(**emparejada("servidor"))
        motor = aplicacion.motor
        motor._proceso = object()  # Como si el motor estuviera corriendo y conectado.
        motor.datos = {"estado": "conectado", "otra_pc": {"nombre": "OTRA", "ip": "10.0.0.2"}}
        aplicacion._al_cambiar_estado()
        self.assertIn("Conectando", aplicacion.ventana.estado_portapapeles.text())

        oyente = modulo_socket.create_server(("127.0.0.1", 0))
        nuestro = modulo_socket.create_connection(oyente.getsockname())
        del_otro, _ = oyente.accept()
        oyente.close()
        self.addCleanup(del_otro.close)
        motor.canal_datos.emit(nuestro)
        self.assertTrue(aplicacion.portapapeles.listo)
        self.assertIn("Listo", aplicacion.ventana.estado_portapapeles.text())

        motor.datos = {"estado": "esperando"}  # Se cortó el mouse: se suelta el canal.
        aplicacion._al_cambiar_estado()
        self.assertFalse(aplicacion.portapapeles.listo)
        self.assertIn("conectadas", aplicacion.ventana.estado_portapapeles.text())

        # Sin canal, mandar archivos (por ejemplo desde "Enviar a") avisa y no rompe nada.
        from mouse_compartido.ui import instancia

        aplicacion._al_recibir_de_otra_instancia(instancia.mensaje_enviar(["C:\\x.txt"]))
        self.assertIn("conectadas", aplicacion.ventana.registro.toPlainText())

    def test_emparejar_guarda_la_clave_y_completa_la_funcion(self):
        from mouse_compartido.red.emparejamiento import Emparejada, Intento

        aplicacion, ruta = self._aplicacion()
        self.assertTrue(len(aplicacion.config.id_pc) == 32, "La identidad se crea sola")
        self.assertEqual(json.loads(ruta.read_text(encoding="utf-8"))["id_pc"],
                         aplicacion.config.id_pc)
        intento = Intento(True, "10.0.0.2")
        resultado = Emparejada("33" * 16, "NOTEBOOK", "cliente", "10.0.0.2", b"\x07" * 32)
        aplicacion._al_terminar_emparejamiento(intento, resultado, "")
        guardado = json.loads(ruta.read_text(encoding="utf-8"))
        self.assertEqual(guardado["emparejado_id"], "33" * 16)
        self.assertEqual(guardado["emparejado_clave"], "07" * 32)
        self.assertEqual(guardado["ultima_ip_otra_pc"], "10.0.0.2")
        self.assertEqual(guardado["rol"], "servidor", "La otra es cliente: esta queda servidor")
        self.assertTrue(aplicacion.config.emparejada)
        self.assertEqual(aplicacion.ventana.nombre_pareja.text(), "NOTEBOOK")
        self.assertEqual(aplicacion.config.errores(), [])

    def test_archivos_copiados_pasan_a_la_otra_pc(self):
        """Dos "PCs" en este mismo proceso, unidas por un canal de datos de verdad."""
        import shutil
        import socket as modulo_socket

        from mouse_compartido.datos import transferencias as T
        from mouse_compartido.ui import archivos as modulo_archivos
        from mouse_compartido.ui.archivos import GestorArchivos
        from mouse_compartido.ui.enlace import EnlaceDatos

        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        self.addCleanup(setattr, modulo_archivos, "CARPETA_TEMPORAL",
                        modulo_archivos.CARPETA_TEMPORAL)
        modulo_archivos.CARPETA_TEMPORAL = base / "temporal"
        self.addCleanup(setattr, modulo_archivos, "AL_TOQUE", modulo_archivos.AL_TOQUE)
        modulo_archivos.AL_TOQUE = 1000  # Para probar también los "grandes" con poco.
        origen = base / "origen"
        origen.mkdir()
        (origen / "chico.txt").write_bytes(b"hola")
        (origen / "grande.bin").write_bytes(os.urandom(300 * 1024))

        oyente = modulo_socket.create_server(("127.0.0.1", 0))
        sock_a = modulo_socket.create_connection(oyente.getsockname())
        sock_b, _ = oyente.accept()
        oyente.close()
        pegados = {"a": [], "b": []}
        pcs = {}
        for nombre, sock in (("a", sock_a), ("b", sock_b)):
            enlace = EnlaceDatos()
            config = Config(carpeta_recibidos=str(base / f"recibidos-{nombre}"))
            gestor = GestorArchivos(config, enlace, base / f"estado-{nombre}.json",
                                    poner_archivos=pegados[nombre].append)
            enlace.conexion_cambiada(True)
            enlace.usar_canal(sock)
            pcs[nombre] = gestor
            self.addCleanup(enlace.soltar)
            self.addCleanup(gestor.detener)
        a, b = pcs["a"], pcs["b"]

        def esperar(condicion, segundos=8):
            limite = time.monotonic() + segundos
            while time.monotonic() < limite:
                self.app.processEvents()
                if condicion():
                    return True
                time.sleep(0.01)
            return False

        # 1. Algo chico: viaja enseguida y queda en el portapapeles de la otra PC.
        a.al_copiar_algo()
        a.al_copiar_archivos([str(origen / "chico.txt")])
        self.assertTrue(esperar(lambda: pegados["b"]))
        pegado = Path(pegados["b"][0][0])
        self.assertEqual(pegado.read_bytes(), b"hola")
        self.assertTrue(pegado.is_relative_to(base / "temporal"))

        # 2. Algo grande: espera a que el mouse llegue a la otra PC.
        b.poner_mouse_aca(False)
        a.al_copiar_algo()
        a.al_copiar_archivos([str(origen / "grande.bin")])
        self.assertTrue(esperar(lambda: b._oferta_entrante is not None
                                and b._oferta_entrante["estado"] == "esperando"))
        esperar(lambda: False, 0.3)
        self.assertEqual(len(pegados["b"]), 1, "Todavía no tiene que haber viajado")
        b.poner_mouse_aca(True)
        self.assertTrue(esperar(lambda: len(pegados["b"]) == 2))
        self.assertEqual(Path(pegados["b"][1][0]).read_bytes(),
                         (origen / "grande.bin").read_bytes())

        # 3. Si en la otra PC copiás otra cosa antes de llevar el mouse, no viaja.
        b.poner_mouse_aca(False)
        a.al_copiar_algo()
        a.al_copiar_archivos([str(origen / "grande.bin")])
        self.assertTrue(esperar(lambda: b._oferta_entrante is not None
                                and b._oferta_entrante["estado"] == "esperando"))
        b.al_copiar_algo()
        b.poner_mouse_aca(True)
        esperar(lambda: False, 0.5)
        self.assertEqual(len(pegados["b"]), 2)

        # 4. Mandar a propósito: va a la carpeta de recibidos de la otra PC.
        avances = []
        b.progreso_cambiado.connect(avances.append)
        self.assertEqual(a.mandar([str(origen)]), "")
        self.assertTrue(esperar(lambda: any(p.estado == "terminado" and p.motivo == T.ENVIADOS
                                            for p in avances)))
        recibidos = base / "recibidos-b" / "origen"
        self.assertEqual((recibidos / "chico.txt").read_bytes(), b"hola")
        self.assertEqual(len(pegados["b"]), 2, "Lo mandado no toca el portapapeles")

    def test_otra_instancia_le_pasa_rutas_a_la_abierta(self):
        """Lo que hace el clic derecho → Enviar a: un proceso cortito le pasa las rutas."""
        from mouse_compartido.ui import instancia

        self.addCleanup(setattr, instancia, "NOMBRE", instancia.NOMBRE)
        instancia.NOMBRE = f"MouseCompartido-prueba-instancia-{os.getpid()}"
        self.assertFalse(instancia.mandar(instancia.MOSTRAR, espera_ms=200), "No hay nadie")
        recibidos = []
        servidor = instancia.crear_servidor(None, recibidos.append)
        self.addCleanup(servidor.close)
        rutas = [r"C:\Mis cosas\foto ñ.jpg", r"D:\otra"]
        resultado = {}
        hilo = threading.Thread(target=lambda: resultado.setdefault(
            "ok", instancia.mandar(instancia.mensaje_enviar(rutas))))
        hilo.start()
        limite = time.monotonic() + 5
        while not recibidos and time.monotonic() < limite:
            self.app.processEvents()
            time.sleep(0.01)
        hilo.join(5)
        self.assertTrue(resultado.get("ok"))
        self.assertEqual(instancia.leer_mensaje(recibidos[0]), ("enviar", rutas))
        self.assertEqual(instancia.leer_mensaje(b"mostrar"), ("mostrar", []))

    def test_control_motor_de_punta_a_punta(self):
        """La interfaz arranca el motor real, recibe el canal de datos, lo pausa y lo detiene."""
        from mouse_compartido.motor.servidor import Servidor
        from mouse_compartido.red.canal_datos import CanalDatos
        from mouse_compartido.ui.control_motor import ControlMotor
        from tests.test_integracion import CapturaFalsa

        config = Config(**emparejada("cliente", puerto=24995, ip_servidor="127.0.0.1",
                                     enfriamiento_ms=0, esquinas_muertas_px=0))
        config_servidor = Config(**emparejada("servidor", puerto=24995, enfriamiento_ms=0,
                                              esquinas_muertas_px=0))
        captura = CapturaFalsa(config_servidor)
        canales_servidor = []
        servidor = Servidor(config_servidor, captura=captura,
                            entregar_canal=lambda s, c: canales_servidor.append((s, c)))
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
        canales_app = []
        control.canal_datos.connect(canales_app.append)

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

        # El motor (otro proceso) abrió el canal de datos y se lo pasó a este proceso.
        self.assertTrue(esperar(lambda: canales_app and canales_servidor), "\n".join(registro))
        recibidos = []
        sock_app, claves_app = canales_app[0]  # Las claves cruzaron de proceso junto al socket.
        sock_servidor, claves_servidor = canales_servidor[0]
        canal_app = CanalDatos(sock_app, lambda t, c: recibidos.append(c), claves=claves_app)
        canal_servidor = CanalDatos(sock_servidor, lambda t, c: recibidos.append(c),
                                    claves=(claves_servidor.envio, claves_servidor.recepcion))
        self.addCleanup(canal_app.cerrar)
        self.addCleanup(canal_servidor.cerrar)
        canal_app.enviar(40, b"de la ventana")
        canal_servidor.enviar(40, b"del servidor")
        self.assertTrue(esperar(lambda: len(recibidos) == 2))
        self.assertEqual(sorted(recibidos), [b"de la ventana", b"del servidor"])

        control.pausar()
        self.assertTrue(esperar(lambda: control.datos.get("pausa_local")))
        self.assertTrue(esperar(lambda: captura.logica.pausa_remota))
        control.detener()
        self.assertTrue(esperar(lambda: not control.activo))
        self.assertEqual(control.error, "")
        self.assertTrue(captura.desconectado.wait(5))


if __name__ == "__main__":
    unittest.main()
