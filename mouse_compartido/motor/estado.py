"""El estado del motor, tal como lo ve la interfaz.

Varios hilos lo actualizan (red, ganchos, órdenes). Cada vez que algo cambia de
verdad, se manda una foto completa a la interfaz. Solo pasa en los cambios
(conectar, cruzar, pausar), nunca por cada movimiento del mouse.
"""

import socket
import threading

# Valores de "estado":
INICIANDO = "iniciando"
ESPERANDO = "esperando"  # Servidor: esperando que se conecte la otra PC.
CONECTANDO = "conectando"  # Cliente: buscando al servidor.
CONECTADO = "conectado"
ERROR = "error"

# Por cable o con buen Wi-Fi, ida y vuelta tarda menos de 10 ms. Desde 50 ms el
# mouse ya se siente pesado o a los saltos.
DEMORA_ALTA_MS = 50.0


class Informante:
    def __init__(self, emitir=None, rol=""):
        self._emitir = emitir  # Función que recibe un dict, o None si nadie escucha.
        self._candado = threading.Lock()
        self.datos = {
            "estado": INICIANDO,
            "detalle": "",
            "rol": rol,
            "nombre_pc": socket.gethostname(),
            "ips": [],
            "otra_pc": None,  # {"nombre", "ip", "monitores"} mientras hay conexión.
            "lado": "",  # Dónde está la otra PC respecto de esta.
            "mouse_aca": True,  # ¿El mouse compartido está manejando ESTA PC?
            "pausa_local": False,
            "pausa_otra": False,
            "latencia_ms": None,
            "latencia_pico_ms": None,  # El peor valor de los últimos 30 segundos.
        }

    def actualizar(self, **cambios):
        """Aplica los cambios y avisa a la interfaz si alguno era nuevo."""
        with self._candado:
            nuevos = {k: v for k, v in cambios.items() if self.datos.get(k) != v}
            if not nuevos:
                return
            self.datos.update(nuevos)
            foto = dict(self.datos)
        if self._emitir is not None:
            self._emitir({"evento": "estado", **foto})

    def leer(self, clave):
        with self._candado:
            return self.datos.get(clave)
