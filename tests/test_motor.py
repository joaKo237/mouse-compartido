"""El motor como proceso aparte, tal como lo maneja la interfaz.

Se arranca `main.py motor` de verdad (como cliente, contra un servidor de prueba)
y se le habla por su entrada y salida, igual que la interfaz. No mueve el mouse
real: el servidor de prueba nunca le pasa el control.
"""

import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from mouse_compartido.comun.config import Config
from mouse_compartido.motor.servidor import Servidor
from tests.ayuda import emparejada
from tests.test_integracion import CapturaFalsa

RAIZ = Path(__file__).resolve().parent.parent
PUERTO = 24997
_COMUNES = dict(puerto=PUERTO, ip_servidor="127.0.0.1", max_envios_mouse_hz=0,
                esquinas_muertas_px=0, enfriamiento_ms=0)
CONFIG = Config(**emparejada("cliente", **_COMUNES))
CONFIG_SERVIDOR = Config(**emparejada("servidor", **_COMUNES))


class Motor:
    """Arranca el proceso y junta lo que va diciendo."""

    def __init__(self, config):
        carpeta = tempfile.TemporaryDirectory()
        self._carpeta = carpeta
        ruta = Path(carpeta.name) / "config.json"
        ruta.write_text(json.dumps(asdict(config)), encoding="utf-8")
        self.proceso = subprocess.Popen(
            [sys.executable, str(RAIZ / "main.py"), "motor", "--config", str(ruta)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=RAIZ, text=True, encoding="utf-8",
        )
        self.eventos = queue.Queue()
        threading.Thread(target=self._leer, daemon=True).start()

    def _leer(self):
        for linea in self.proceso.stdout:
            self.eventos.put(json.loads(linea))

    def ordenar(self, orden):
        self.proceso.stdin.write(json.dumps({"orden": orden}) + "\n")
        self.proceso.stdin.flush()

    def esperar_estado(self, condicion, segundos=8.0):
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            try:
                evento = self.eventos.get(timeout=0.2)
            except queue.Empty:
                continue
            if evento.get("evento") == "estado" and condicion(evento):
                return evento
        return None

    def cerrar(self):
        if self.proceso.poll() is None:
            self.proceso.kill()
        self.proceso.wait(5)
        for flujo in (self.proceso.stdin, self.proceso.stdout, self.proceso.stderr):
            try:
                flujo.close()
            except OSError:
                pass
        self._carpeta.cleanup()


class MotorTest(unittest.TestCase):
    def arrancar_servidor(self):
        self.captura = CapturaFalsa(CONFIG_SERVIDOR)
        self.servidor = Servidor(CONFIG_SERVIDOR, captura=self.captura)
        hilo = threading.Thread(target=self.servidor.correr, daemon=True)
        hilo.start()
        self.assertTrue(self.servidor.escuchando.wait(5))
        self.addCleanup(lambda: (self.servidor.detener(), hilo.join(5)))

    def test_conecta_obedece_y_termina_limpio(self):
        self.arrancar_servidor()
        motor = Motor(CONFIG)
        self.addCleanup(motor.cerrar)

        conectado = motor.esperar_estado(
            lambda e: e["estado"] == "conectado" and (e["otra_pc"] or {}).get("nombre")
        )
        self.assertIsNotNone(conectado, motor.proceso.stderr.read() if motor.proceso.poll() else "")
        self.assertEqual(conectado["rol"], "cliente")
        self.assertEqual(conectado["lado"], "izquierda")

        motor.ordenar("pausar")
        self.assertIsNotNone(motor.esperar_estado(lambda e: e["pausa_local"]))
        limite = time.monotonic() + 3
        while not self.captura.logica.pausa_remota and time.monotonic() < limite:
            time.sleep(0.01)
        self.assertTrue(self.captura.logica.pausa_remota, "La pausa tiene que llegar al servidor")

        motor.ordenar("reanudar")
        self.assertIsNotNone(motor.esperar_estado(lambda e: not e["pausa_local"]))

        motor.ordenar("salir")
        self.assertEqual(motor.proceso.wait(5), 0)
        self.assertTrue(self.captura.desconectado.wait(5))

    def test_si_se_cierra_la_interfaz_el_motor_termina_solo(self):
        motor = Motor(replace(CONFIG, puerto=PUERTO + 1))  # Nadie escucha: queda reintentando.
        self.addCleanup(motor.cerrar)
        self.assertIsNotNone(motor.esperar_estado(lambda e: e["estado"] == "conectando"))
        motor.proceso.stdin.close()  # Como si la interfaz se hubiera cerrado de golpe.
        self.assertEqual(motor.proceso.wait(6), 0)

    def test_sin_configuracion_avisa_el_error(self):
        motor = Motor(replace(CONFIG, emparejado_clave=""))
        self.addCleanup(motor.cerrar)
        error = motor.esperar_estado(lambda e: e["estado"] == "error")
        self.assertIn("emparejar", error["detalle"])
        self.assertEqual(motor.proceso.wait(5), 2)


if __name__ == "__main__":
    unittest.main()
