"""Pruebas de pasar archivos y de la carpeta compartida (sin Qt, con sockets reales)."""

import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from mouse_compartido.datos import carpeta as C
from mouse_compartido.datos import transferencias as T
from mouse_compartido.red.canal_datos import CanalDatos
from mouse_compartido.red.protocolo import Tipo


def par_de_canales():
    """Dos "PCs" unidas por un canal de datos cifrado. Cada una reparte lo que le llega."""
    oyente = socket.socket()
    oyente.bind(("127.0.0.1", 0))
    oyente.listen(1)
    a = socket.create_connection(oyente.getsockname())
    b, _ = oyente.accept()
    oyente.close()
    clave_ab, clave_ba = os.urandom(32), os.urandom(32)
    pcs = []
    for sock, claves in ((a, (clave_ab, clave_ba)), (b, (clave_ba, clave_ab))):
        pc = PcFalsa()
        pc.canal = CanalDatos(sock, pc.repartir, claves=claves)
        pcs.append(pc)
    return pcs


class PcFalsa:
    """Hace de EnlaceDatos (ui/enlace.py) pero sin Qt."""

    def __init__(self):
        self.canal = None
        self.atender = {}
        self.otros = []

    def atender_en_hilo(self, tipo, funcion):
        self.atender[tipo] = funcion

    def repartir(self, tipo, cuerpo):
        funcion = self.atender.get(tipo)
        if funcion is not None:
            funcion(cuerpo)
        else:
            self.otros.append((tipo, cuerpo))

    def enviar(self, tipo, cuerpo=b""):
        return self.canal.enviar(tipo, cuerpo)

    def enviar_bloque(self, tipo, cuerpo, timeout=None):
        return self.canal.enviar_bloque(tipo, cuerpo, timeout)


def esperar(condicion, segundos=10.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


class RutasTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)

    def test_rutas_normales(self):
        self.assertEqual(T.ruta_segura(self.base, "fotos/playa.jpg"),
                         self.base.resolve() / "fotos" / "playa.jpg")

    def test_rutas_peligrosas_se_rechazan(self):
        for mala in ("../afuera.txt", "a/../../b", "C:/Windows/x", "/raiz", "a\\b", "",
                     "con.txt", "carpeta/NUL", "a:b", "nombre.", "espacio ", "a//b", "x?y"):
            with self.subTest(mala=mala), self.assertRaises(ValueError):
                T.ruta_segura(self.base, mala)

    def test_nombre_libre(self):
        (self.base / "foto.jpg").write_bytes(b"1")
        (self.base / "foto (2).jpg").write_bytes(b"2")
        self.assertEqual(T.nombre_libre(self.base, "foto.jpg"), "foto (3).jpg")
        self.assertEqual(T.nombre_libre(self.base, "otra.jpg"), "otra.jpg")
        (self.base / "LEEME").write_bytes(b"3")
        self.assertEqual(T.nombre_libre(self.base, "LEEME"), "LEEME (2)")

    def test_listar_carpeta_con_subcarpetas_y_vacias(self):
        (self.base / "proyecto" / "src").mkdir(parents=True)
        (self.base / "proyecto" / "vacia").mkdir()
        (self.base / "proyecto" / "src" / "a.py").write_bytes(b"print(1)")
        (self.base / "suelto.txt").write_bytes(b"hola")
        entradas = T.listar([self.base / "proyecto", self.base / "suelto.txt"])
        rutas = {e.ruta: e for e in entradas}
        self.assertTrue(rutas["proyecto"].carpeta)
        self.assertTrue(rutas["proyecto/vacia"].carpeta)
        self.assertEqual(rutas["proyecto/src/a.py"].tam, 8)
        self.assertEqual(rutas["suelto.txt"].tam, 4)
        self.assertEqual(T.describir(entradas), "2 archivos")


class TransferenciaTest(unittest.TestCase):
    def setUp(self):
        self.origen = Path(tempfile.mkdtemp())
        self.destino = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.origen, True)
        self.addCleanup(shutil.rmtree, self.destino, True)
        self.a, self.b = par_de_canales()
        self.addCleanup(self.a.canal.cerrar)
        self.addCleanup(self.b.canal.cerrar)
        self.progresos_a, self.progresos_b = [], []
        self.destino_b = lambda motivo, info: self.destino
        self.trans_a = T.Transferencias(self.a, lambda m, i: self.origen,
                                        lambda p: self.progresos_a.append((p.estado, p.hecho)))
        self.trans_b = T.Transferencias(self.b, lambda m, i: self.destino_b(m, i),
                                        self._anotar_b)
        self.trans_a.registrar_en(self.a)
        self.trans_b.registrar_en(self.b)
        self.ultimo_b = None

    def _anotar_b(self, progreso):
        self.ultimo_b = progreso
        self.progresos_b.append(progreso.estado)

    def test_pasa_archivos_y_carpetas_con_su_fecha(self):
        (self.origen / "album" / "vacia").mkdir(parents=True)
        grande = os.urandom(T.PEDAZO * 3 + 123)  # Más de un pedazo.
        (self.origen / "album" / "foto.jpg").write_bytes(grande)
        (self.origen / "nota.txt").write_text("hola", encoding="utf-8")
        fecha = 1_700_000_000_000_000_000
        os.utime(self.origen / "nota.txt", ns=(fecha, fecha))
        progreso = self.trans_a.mandar(T.listar([self.origen / "album", self.origen / "nota.txt"]),
                                       T.ENVIADOS)
        self.assertTrue(esperar(lambda: self.ultimo_b and self.ultimo_b.estado == "terminado"))
        self.assertEqual((self.destino / "album" / "foto.jpg").read_bytes(), grande)
        self.assertTrue((self.destino / "album" / "vacia").is_dir())
        self.assertEqual((self.destino / "nota.txt").stat().st_mtime_ns, fecha)
        self.assertEqual(sorted(Path(r).name for r in self.ultimo_b.rutas_finales),
                         ["album", "nota.txt"])
        self.assertEqual(self.ultimo_b.archivos_hechos, 2)
        self.assertTrue(esperar(lambda: progreso.estado == "terminado"))
        self.assertEqual(progreso.hecho, progreso.total)
        self.assertFalse(list(self.destino.rglob("*" + T.SUFIJO_PARCIAL)))

    def test_no_pisa_lo_que_ya_estaba(self):
        (self.destino / "nota.txt").write_text("vieja", encoding="utf-8")
        (self.origen / "nota.txt").write_text("nueva", encoding="utf-8")
        self.trans_a.mandar(T.listar([self.origen / "nota.txt"]), T.ENVIADOS)
        self.assertTrue(esperar(lambda: self.ultimo_b and self.ultimo_b.estado == "terminado"))
        self.assertEqual((self.destino / "nota.txt").read_text(encoding="utf-8"), "vieja")
        self.assertEqual((self.destino / "nota (2).txt").read_text(encoding="utf-8"), "nueva")

    def test_si_la_otra_pc_lo_rechaza_se_cancela(self):
        def sin_lugar(motivo, info):
            raise ValueError("No hay lugar en el disco de esta PC")

        self.destino_b = sin_lugar
        (self.origen / "x.bin").write_bytes(os.urandom(T.PEDAZO * 20))
        progreso = self.trans_a.mandar(T.listar([self.origen / "x.bin"]), T.ENVIADOS)
        self.assertTrue(esperar(lambda: progreso.estado != "en curso"))
        self.assertEqual(progreso.estado, "cancelado")
        self.assertIn("No hay lugar", progreso.detalle)
        self.assertFalse(list(self.destino.iterdir()))

    def test_cancelar_mientras_llega_no_deja_basura(self):
        (self.origen / "enorme.bin").write_bytes(os.urandom(T.PEDAZO * 200))  # 50 MB.
        progreso = self.trans_a.mandar(T.listar([self.origen / "enorme.bin"]), T.ENVIADOS)
        self.assertTrue(esperar(lambda: self.ultimo_b is not None and self.ultimo_b.hecho > 0))
        self.trans_b.cancelar(self.ultimo_b.clave)
        self.assertTrue(esperar(lambda: progreso.estado != "en curso"))
        self.assertEqual(progreso.estado, "cancelado")
        time.sleep(0.2)
        self.assertFalse(list(self.destino.iterdir()))

    def test_si_se_corta_el_canal_no_queda_nada_a_medias(self):
        (self.origen / "enorme.bin").write_bytes(os.urandom(T.PEDAZO * 200))
        progreso = self.trans_a.mandar(T.listar([self.origen / "enorme.bin"]), T.ENVIADOS)
        self.assertTrue(esperar(lambda: self.ultimo_b is not None and self.ultimo_b.hecho > 0))
        self.b.canal.cerrar()
        self.trans_b.cortar_todo()
        self.assertTrue(esperar(lambda: progreso.estado != "en curso"))
        self.assertEqual(self.ultimo_b.estado, "error")
        self.assertFalse(list(self.destino.iterdir()))


class DecidirTest(unittest.TestCase):
    """La tabla de datos/carpeta.py, caso por caso."""

    def decidir(self, local, remota, base, gana_la_otra=False):
        return C.decidir(local, remota, base, lambda ruta: gana_la_otra)

    def test_iguales_actualiza_la_base(self):
        pedir, borrar, conflicto, base = self.decidir({"a": (1, 10)}, {"a": (1, 10)}, {})
        self.assertEqual((pedir, borrar, conflicto, base), ([], [], [], {"a": (1, 10)}))

    def test_nuevo_alla_se_pide_y_nuevo_aca_no(self):
        pedir, borrar, _, _ = self.decidir({"mio": (1, 1)}, {"suyo": (2, 2)}, {})
        self.assertEqual((pedir, borrar), (["suyo"], []))

    def test_borrado_alla_se_borra_aca(self):
        _, borrar, _, _ = self.decidir({"a": (1, 10)}, {}, {"a": (1, 10)})
        self.assertEqual(borrar, ["a"])

    def test_borrado_aca_no_se_vuelve_a_pedir(self):
        pedir, borrar, _, _ = self.decidir({}, {"a": (1, 10)}, {"a": (1, 10)})
        self.assertEqual((pedir, borrar), ([], []))

    def test_si_lo_cambiaste_aca_y_alla_lo_borraron_no_se_borra(self):
        _, borrar, _, _ = self.decidir({"a": (5, 99)}, {}, {"a": (1, 10)})
        self.assertEqual(borrar, [])

    def test_cambio_de_un_solo_lado(self):
        pedir, _, _, _ = self.decidir({"a": (1, 10)}, {"a": (2, 50_000_000_000)}, {"a": (1, 10)})
        self.assertEqual(pedir, ["a"])
        pedir, _, _, _ = self.decidir({"a": (2, 50_000_000_000)}, {"a": (1, 10)}, {"a": (1, 10)})
        self.assertEqual(pedir, [])

    def test_conflicto(self):
        local, remota, base = {"a": (2, 20)}, {"a": (3, 30_000_000_000)}, {"a": (1, 10)}
        self.assertEqual(self.decidir(local, remota, base, gana_la_otra=True)[2], ["a"])
        self.assertEqual(self.decidir(local, remota, base, gana_la_otra=False)[2], [])

    def test_fecha_casi_igual_cuenta_como_igual(self):
        # Un pendrive FAT guarda la hora de a 2 segundos.
        _, _, _, base = self.decidir({"a": (1, 10_000_000_000)}, {"a": (1, 11_000_000_000)}, {})
        self.assertIn("a", base)

    def test_borrado_en_las_dos_sale_de_la_base(self):
        _, _, _, base = self.decidir({}, {}, {"a": (1, 1)})
        self.assertEqual(base, {})

    def test_nombre_de_conflicto(self):
        nombre = C.nombre_conflicto("docs/informe.docx", "NOTEBOOK", 0)
        self.assertTrue(nombre.startswith("docs/informe (conflicto NOTEBOOK "))
        self.assertTrue(nombre.endswith(").docx"))

    def test_revisar_no_informa_archivos_a_medio_escribir(self):
        carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, carpeta, True)
        (carpeta / "listo.txt").write_bytes(b"1")
        (carpeta / "~$temporal.docx").write_bytes(b"x")
        viejo = time.time_ns() - 60 * 10**9
        os.utime(carpeta / "listo.txt", ns=(viejo, viejo))
        (carpeta / "escribiendo.bin").write_bytes(b"123")
        lista = C.revisar(carpeta)
        self.assertEqual(set(lista), {"listo.txt"})


class SincroCarpetaTest(unittest.TestCase):
    """Dos carpetas de verdad, sincronizándose por un canal de datos de verdad."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.a, self.b = par_de_canales()
        self.addCleanup(self.a.canal.cerrar)
        self.addCleanup(self.b.canal.cerrar)
        self.papelera = self.raiz / "papelera"
        self.papelera.mkdir()
        self.registro = []
        viejo = time.time_ns() - 3600 * 10**9  # Fechas viejas: que no parezcan a medio escribir.
        self.viejo = viejo
        self.carpeta_a = self.raiz / "a"
        self.carpeta_b = self.raiz / "b"
        self.carpeta_a.mkdir()
        self.carpeta_b.mkdir()

    def escribir(self, carpeta, ruta, texto, hace_s=3600):
        archivo = carpeta.joinpath(*ruta.split("/"))
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text(texto, encoding="utf-8")
        fecha = time.time_ns() - int(hace_s * 1e9)
        os.utime(archivo, ns=(fecha, fecha))

    def armar(self, pc, carpeta, id_propio, id_otra, nombre):
        def a_la_papelera(ruta):
            shutil.move(ruta, self.papelera / f"{nombre}-{Path(ruta).name}")

        transferencias = T.Transferencias(
            pc, lambda motivo, info: carpeta, lambda p: None,
            al_archivo=lambda p, info, final: sincro.archivo_recibido(
                info["ruta"], info["tam"], info["mtime"]),
            antes_de_reemplazar=lambda p, info, final: sincro.antes_de_reemplazar(
                info["ruta"], final))
        transferencias.registrar_en(pc)
        sincro = C.SincroCarpeta(
            carpeta, self.raiz / f"estado-{nombre}.json", id_propio, id_otra, nombre,
            pc.enviar, lambda entradas: transferencias.mandar(entradas, T.CARPETA),
            a_la_papelera, registrar=self.registro.append)
        pc.atender_en_hilo(Tipo.CARPETA_INDICE, sincro.recibir_indice)
        pc.atender_en_hilo(Tipo.CARPETA_PEDIDO, sincro.recibir_pedido)
        return sincro

    def arrancar(self):
        self.sa = self.armar(self.a, self.carpeta_a, "aa" * 16, "bb" * 16, "ESCRITORIO")
        self.sb = self.armar(self.b, self.carpeta_b, "bb" * 16, "aa" * 16, "NOTEBOOK")
        for sincro in (self.sa, self.sb):
            sincro.iniciar()
            sincro.canal_abierto()
            self.addCleanup(sincro.detener)

    def leer(self, carpeta, ruta):
        archivo = carpeta.joinpath(*ruta.split("/"))
        return archivo.read_text(encoding="utf-8") if archivo.exists() else None

    def test_la_primera_vez_junta_lo_de_las_dos(self):
        self.escribir(self.carpeta_a, "de-a.txt", "A")
        self.escribir(self.carpeta_a, "sub/profundo.txt", "P")
        self.escribir(self.carpeta_b, "de-b.txt", "B")
        self.arrancar()
        self.assertTrue(esperar(lambda: self.leer(self.carpeta_b, "de-a.txt") == "A"
                                and self.leer(self.carpeta_a, "de-b.txt") == "B"
                                and self.leer(self.carpeta_b, "sub/profundo.txt") == "P"))

    def test_cambios_y_borrados_se_contagian(self):
        self.escribir(self.carpeta_a, "comun.txt", "v1")
        self.escribir(self.carpeta_a, "borrame.txt", "x")
        self.arrancar()
        self.assertTrue(esperar(lambda: self.leer(self.carpeta_b, "borrame.txt") == "x"))
        # Esperar a que las dos tengan la base (lo que coincidía).
        time.sleep(C.INTERVALO_REVISION_S * 1.5)
        self.escribir(self.carpeta_a, "comun.txt", "version-2", hace_s=10)
        os.remove(self.carpeta_b / "borrame.txt")
        self.assertTrue(esperar(lambda: self.leer(self.carpeta_b, "comun.txt") == "version-2"
                                and not (self.carpeta_a / "borrame.txt").exists(), 15))
        self.assertTrue((self.papelera / "ESCRITORIO-borrame.txt").exists(),
                        "Lo borrado va a la papelera, no desaparece")

    def test_conflicto_guarda_las_dos_versiones(self):
        self.escribir(self.carpeta_a, "informe.txt", "de A", hace_s=100)
        self.escribir(self.carpeta_b, "informe.txt", "de B, mas nuevo", hace_s=50)
        self.arrancar()
        self.assertTrue(esperar(lambda: self.leer(self.carpeta_a, "informe.txt")
                                == "de B, mas nuevo"
                                and len(list(self.carpeta_b.glob("informe (conflicto*"))) == 1,
                                15))
        copia = next(self.carpeta_b.glob("informe (conflicto*"))
        self.assertIn("ESCRITORIO", copia.name)
        self.assertEqual(copia.read_text(encoding="utf-8"), "de A")

    def test_si_la_otra_carpeta_esta_vacia_no_borra_nada(self):
        self.escribir(self.carpeta_a, "importante.txt", "no borrar")
        self.arrancar()
        self.assertTrue(esperar(lambda: self.leer(self.carpeta_b, "importante.txt")))
        time.sleep(C.INTERVALO_REVISION_S * 1.5)
        # La carpeta de B desaparece (pendrive desenchufado): B avisa que no la tiene.
        shutil.rmtree(self.carpeta_b)
        time.sleep(C.INTERVALO_REVISION_S * 2.5)
        self.assertEqual(self.leer(self.carpeta_a, "importante.txt"), "no borrar")


if __name__ == "__main__":
    unittest.main()
