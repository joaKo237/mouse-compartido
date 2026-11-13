"""Las PCs se encuentran solas en la red, como el Bluetooth.

Cada PC con el programa abierto avisa cada 2 segundos "estoy acá" a toda la red
(un mensaje UDP de "difusión", que reciben todas las PCs de esa red). El aviso
lleva su nombre, su número de identidad y qué hace (tiene el mouse o lo recibe).

  * En la página Conexión aparecen las PCs que se escuchan: así se empareja la
    primera vez, sin escribir ninguna IP.
  * Después, cuando se escucha a la PC emparejada, el cliente se conecta solo a
    la dirección de donde vino el aviso. Si llega por cable y por Wi-Fi, se
    prefiere el cable.

Se avisa por cada placa de red por separado: Windows, si no se le dice nada,
manda la difusión solo por la red principal y el cable directo quedaría afuera.

El aviso no lleva nada secreto: la clave del emparejamiento nunca sale de la PC.
Si alguien imitara el aviso, el cliente intentaría conectarse ahí y el saludo
(ver seguridad.py) fallaría, porque no tiene la clave.
"""

import json
import select
import socket
import threading
import time
from dataclasses import dataclass, field

from ..sistema import redes
from . import protocolo as P

MAGIA = "MCOM-D"
INTERVALO_ANUNCIO_S = 2.0
VENCE_S = 7.0  # Si no se escucha a una PC en este tiempo, se la da por ida.
_LARGO_MAXIMO = 2048


@dataclass
class PcVista:
    """Una PC que se escuchó en la red."""

    id: str
    nombre: str = ""
    rol: str = ""
    puerto: int = 0
    emparejado_con: str = ""  # El id de la PC con la que está emparejada ("" = ninguna).
    version: int = 0  # Versión del protocolo que usa.
    ips: dict = field(default_factory=dict)  # ip -> (prioridad, último momento visto)

    def destinos(self):
        """[(ip, prioridad)], el mejor camino primero (cable antes que Wi-Fi)."""
        return sorted(((ip, datos[0]) for ip, datos in self.ips.items()), key=lambda d: d[1])

    @property
    def mejor_prioridad(self):
        return min((datos[0] for datos in self.ips.values()), default=redes.SIN_RUTA)

    @property
    def ip(self):
        destinos = self.destinos()
        return destinos[0][0] if destinos else ""


class Descubridor:
    """Avisa que esta PC está y escucha los avisos de las demás, en un hilo propio.

    `datos_propios()` devuelve el dict a anunciar (id, nombre, rol, puerto,
    emparejado_con) y `al_cambiar()` se llama (desde el hilo) cuando aparece,
    cambia o desaparece alguna PC.
    """

    def __init__(self, puerto, datos_propios, al_cambiar=None, puerto_destino=None,
                 direcciones_extra=None, placas=redes.placas, reloj=time.monotonic):
        self.puerto = puerto
        self.puerto_destino = puerto_destino or puerto
        self._datos_propios = datos_propios
        self._al_cambiar = al_cambiar
        # IPs a las que también se avisa directo (la última conocida de la otra PC):
        # sirve en redes que bloquean la difusión pero no los mensajes directos.
        self._direcciones_extra = direcciones_extra or (lambda: [])
        self._placas = placas
        self._reloj = reloj
        self._pcs = {}
        self._candado = threading.Lock()
        self._parar = threading.Event()
        self._despertar = threading.Event()
        self._sock = None
        self._hilo = None
        self.error = ""

    # ---- Lo que usa la interfaz ----------------------------------------------------------
    def iniciar(self):
        """Empieza a escuchar. Devuelve False si el puerto está ocupado."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", self.puerto))
        except OSError as error:
            sock.close()
            self.error = f"No se puede usar el puerto {self.puerto} para encontrar PCs: {error}"
            return False
        self._sock = sock
        self._hilo = threading.Thread(target=self._correr, name="descubrimiento", daemon=True)
        self._hilo.start()
        return True

    def detener(self):
        self._parar.set()
        self._despertar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=2)

    def anunciar_ya(self):
        """Avisa ahora mismo (por ejemplo, porque cambió el rol o el emparejamiento)."""
        self._despertar.set()

    def pcs(self):
        """Las PCs que se están escuchando, ordenadas por nombre (copias)."""
        with self._candado:
            vistas = [_copiar(pc) for pc in self._pcs.values()]
        return sorted(vistas, key=lambda pc: pc.nombre.lower())

    def buscar(self, id_pc):
        with self._candado:
            pc = self._pcs.get(id_pc)
            return _copiar(pc) if pc else None

    # ---- Hilo ----------------------------------------------------------------------------
    def _correr(self):
        self._anunciar(pregunta=True)  # Al arrancar se pregunta: "¿hay alguien?".
        proximo = self._reloj() + INTERVALO_ANUNCIO_S
        try:
            while not self._parar.is_set():
                if self._despertar.is_set():
                    self._despertar.clear()
                    if self._parar.is_set():
                        break
                    proximo = 0.0
                ahora = self._reloj()
                if ahora >= proximo:
                    self._anunciar()
                    self._vencer(ahora)
                    proximo = ahora + INTERVALO_ANUNCIO_S
                try:
                    listos, _, _ = select.select([self._sock], [], [], min(0.25, max(0.0, proximo - ahora)))
                except (OSError, ValueError):
                    break
                if listos:
                    self._recibir()
        finally:
            self._sock.close()

    def _mensaje(self, tipo):
        datos = dict(self._datos_propios())
        datos.update(m=MAGIA, t=tipo, pv=P.VERSION)
        return json.dumps(datos, ensure_ascii=False).encode("utf-8")

    def _anunciar(self, pregunta=False):
        mensaje = self._mensaje("busco" if pregunta else "anuncio")
        try:
            placas = self._placas()
        except OSError:
            placas = []
        for placa in placas:
            # Un socket "atado" a la IP de cada placa: así la difusión sale por esa placa.
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((placa.ip, 0))
                for destino in {"255.255.255.255", placa.difusion}:
                    sock.sendto(mensaje, (destino, self.puerto_destino))
            except OSError:
                pass  # Esa placa se desconectó justo: se reintenta en 2 segundos.
            finally:
                sock.close()
        for ip in self._direcciones_extra():
            if ip:
                try:
                    self._sock.sendto(mensaje, (ip, self.puerto_destino))
                except OSError:
                    pass

    def _recibir(self):
        try:
            datos, (ip, puerto) = self._sock.recvfrom(_LARGO_MAXIMO)
        except OSError:
            return  # Windows avisa así que un mensaje directo anterior no llegó: no importa.
        try:
            aviso = json.loads(datos.decode("utf-8"))
            if aviso.get("m") != MAGIA:
                return
            id_pc = str(aviso.get("id", ""))[:64]
        except (ValueError, AttributeError):
            return
        propio = self._datos_propios()
        if not id_pc or id_pc == propio.get("id"):
            return  # Es nuestro propio aviso, que vuelve.
        if aviso.get("t") == "busco":
            # Alguien recién abrió el programa: se le contesta directo, sin esperar.
            try:
                self._sock.sendto(self._mensaje("anuncio"), (ip, puerto))
            except OSError:
                pass
        self._anotar(id_pc, ip, aviso)

    def _anotar(self, id_pc, ip, aviso):
        ahora = self._reloj()
        try:
            prioridad = redes.prioridad(ip, self._placas())
        except OSError:
            prioridad = redes.SIN_RUTA
        with self._candado:
            pc = self._pcs.get(id_pc)
            nueva = pc is None
            if nueva:
                pc = self._pcs[id_pc] = PcVista(id_pc)
            antes = (pc.nombre, pc.rol, pc.puerto, pc.emparejado_con, pc.version, set(pc.ips))
            pc.nombre = str(aviso.get("nombre", ""))[:64]
            pc.rol = str(aviso.get("rol", ""))[:16]
            try:
                pc.puerto = int(aviso.get("puerto", 0))
                pc.version = int(aviso.get("pv", 0))
            except (TypeError, ValueError):
                pass
            pc.emparejado_con = str(aviso.get("emparejado_con", ""))[:64]
            pc.ips[ip] = (prioridad, ahora)
            despues = (pc.nombre, pc.rol, pc.puerto, pc.emparejado_con, pc.version, set(pc.ips))
        if nueva or antes != despues:
            self._avisar()

    def _vencer(self, ahora):
        cambio = False
        with self._candado:
            for id_pc in list(self._pcs):
                pc = self._pcs[id_pc]
                for ip in [ip for ip, (_, visto) in pc.ips.items() if ahora - visto > VENCE_S]:
                    del pc.ips[ip]
                    cambio = True
                if not pc.ips:
                    del self._pcs[id_pc]
                    cambio = True
        if cambio:
            self._avisar()

    def _avisar(self):
        if self._al_cambiar is not None:
            try:
                self._al_cambiar()
            except Exception:  # Un error de la interfaz no tiene que matar este hilo.
                pass


def _copiar(pc):
    return PcVista(pc.id, pc.nombre, pc.rol, pc.puerto, pc.emparejado_con, pc.version,
                   dict(pc.ips))
