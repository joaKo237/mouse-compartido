"""La carpeta compartida: una carpeta en cada PC que se mantiene igual en las dos.

Cómo se decide qué hacer con cada archivo:
  * Cada PC revisa su carpeta cada pocos segundos y, si algo cambió, le manda a
    la otra la lista completa (nombre, tamaño y fecha de cada archivo).
  * Cada PC recuerda cómo estaban los archivos la última vez que coincidían en
    las dos (la "base", guardada en un archivo). Comparando las tres cosas (lo de
    acá, lo de allá y la base) se sabe quién cambió qué:

        acá       allá      base      ->  qué hace ESTA PC
        igual     igual     -         ->  nada (anota la base)
        está      no está   = acá     ->  allá lo borraron: lo manda a la papelera
        está      no está   ≠ / no    ->  nada (es nuevo acá: lo va a pedir la otra)
        no está   está      = allá    ->  nada (lo borraste acá: lo borra la otra)
        no está   está      ≠ / no    ->  lo pide
        cambió    igual a base        ->  nada (lo pide la otra)
        igual a base   cambió         ->  lo pide
        cambió    cambió              ->  conflicto: gana el más nuevo; el otro se
                                          guarda como "nombre (conflicto PC fecha)"

  * Cada PC solo PIDE lo que le falta y solo BORRA lo propio: como las dos hacen
    la misma cuenta con los mismos datos, nunca hacen lo mismo dos veces.
  * Lo borrado va a la Papelera de reciclaje, nunca se elimina del todo.
  * Si la lista de la otra PC llega vacía teniendo historia (por ejemplo, la
    carpeta estaba en un pendrive que se desenchufó), no se borra nada.
"""

import json
import os
import threading
import time
from pathlib import Path

from ..red.protocolo import Tipo
from .transferencias import SUFIJO_PARCIAL, Entrada, armar_json, leer_json

INTERVALO_REVISION_S = 2.0
_ESTABLE_S = 2.0  # Un archivo modificado hace menos que esto quizá se está escribiendo.
_TOLERANCIA_FECHA_NS = 2_000_000_000  # Los discos FAT guardan la hora de a 2 segundos.
_PEDIDO_VENCE_S = 600.0
_GUARDAR_CADA_S = 2.0


def ignorar(nombre):
    """Archivos que no se sincronizan: temporales de Office, de Windows o nuestros."""
    bajo = nombre.lower()
    return (bajo.startswith(("~$", ".~")) or bajo.endswith((".tmp", SUFIJO_PARCIAL))
            or bajo in ("desktop.ini", "thumbs.db", ".ds_store"))


def igual(a, b):
    return (a is not None and b is not None and a[0] == b[0]
            and abs(a[1] - b[1]) < _TOLERANCIA_FECHA_NS)


def revisar(carpeta, anterior=None, ahora_ns=None):
    """Lista la carpeta: {ruta relativa con "/": (tamaño, fecha en ns)}.

    Un archivo que se modificó recién (quizá se está escribiendo) se informa con
    sus datos anteriores, o no se informa si es nuevo: así la otra PC no se lleva
    un archivo a medio escribir.
    """
    carpeta = Path(carpeta)
    anterior = anterior or {}
    ahora_ns = time.time_ns() if ahora_ns is None else ahora_ns
    lista = {}
    for raiz, carpetas, archivos in os.walk(carpeta):
        carpetas[:] = [c for c in carpetas if not ignorar(c)]
        relativa = Path(raiz).relative_to(carpeta).parts
        for nombre in archivos:
            if ignorar(nombre):
                continue
            ruta = "/".join((*relativa, nombre))
            try:
                info = os.stat(os.path.join(raiz, nombre))
            except OSError:
                continue
            datos = (info.st_size, info.st_mtime_ns)
            if ahora_ns - info.st_mtime_ns < _ESTABLE_S * 1e9 and datos != anterior.get(ruta):
                if ruta in anterior:
                    lista[ruta] = anterior[ruta]
                continue
            lista[ruta] = datos
    return lista


def decidir(local, remota, base, gana_la_otra):
    """La tabla de arriba. Devuelve (a_pedir, a_borrar, en_conflicto, base_nueva).

    `gana_la_otra(ruta)` desempata conflictos: True si se queda la versión de allá.
    """
    pedir, borrar, conflicto = [], [], []
    base = dict(base)
    for ruta in set(local) | set(remota):
        L, R, B = local.get(ruta), remota.get(ruta), base.get(ruta)
        if L is not None and R is not None and igual(L, R):
            base[ruta] = L
        elif R is None:
            if B is not None and igual(L, B):
                borrar.append(ruta)
        elif L is None:
            if not (B is not None and igual(R, B)):
                pedir.append(ruta)
        else:
            cambio_aca = not (B is not None and igual(L, B))
            cambio_alla = not (B is not None and igual(R, B))
            if cambio_alla and not cambio_aca:
                pedir.append(ruta)
            elif cambio_alla and cambio_aca and gana_la_otra(ruta):
                conflicto.append(ruta)
    for ruta in list(base):
        if ruta not in local and ruta not in remota:
            del base[ruta]  # Ya no está en ninguna: se borró en las dos.
    return sorted(pedir), sorted(borrar), sorted(conflicto), base


def nombre_conflicto(ruta, nombre_pc, momento=None):
    """"informe.docx" -> "informe (conflicto NOTEBOOK 2026-11-13 14.05).docx"."""
    momento = time.strftime("%Y-%m-%d %H.%M", time.localtime(momento))
    carpeta, _, nombre = ruta.rpartition("/")
    base, punto, extension = nombre.rpartition(".")
    if not punto or not base:
        base, extension = nombre, ""
    nuevo = f"{base} (conflicto {nombre_pc} {momento})" + (f".{extension}" if extension else "")
    return f"{carpeta}/{nuevo}" if carpeta else nuevo


class SincroCarpeta:
    """Mantiene la carpeta igual a la de la otra PC. Corre en su propio hilo.

    `enviar(tipo, cuerpo)`: el canal de datos. `mandar(entradas)`: arranca un envío
    de archivos de la carpeta (motivo "carpeta"). `papelera(ruta)`: manda un archivo
    a la papelera. `registrar(texto)`: una línea para la actividad.
    """

    def __init__(self, carpeta, ruta_estado, id_propio, id_otra, nombre_pc, enviar, mandar,
                 papelera, registrar=lambda texto: None):
        self.carpeta = Path(carpeta)
        self._ruta_estado = Path(ruta_estado)
        self._id_propio = id_propio
        self._id_otra = id_otra
        self._nombre_pc = nombre_pc
        self._enviar = enviar
        self._mandar = mandar
        self._papelera = papelera
        self._registrar = registrar
        self._candado = threading.RLock()
        self._local = {}
        self._remota = None  # Lo que tiene la otra PC (None = todavía no se sabe).
        self._remota_sin_carpeta = False
        self._base = self._cargar_base()
        self._pedidos = {}  # ruta -> (cuándo se pidió, cómo estaba acá en ese momento)
        self._canal = False
        self._mandar_indice = False
        self._base_cambiada = False
        self._t_guardado = 0.0
        self._parar = threading.Event()
        self._despertar = threading.Event()
        self._hilo = None
        self.ultimo_estado = ""

    # ---- Desde la interfaz -----------------------------------------------------------------
    @property
    def estado_otra(self):
        """Lo que se sabe de la carpeta de la otra PC: "ok", "sin carpeta" o "sin datos"."""
        with self._candado:
            if self._remota_sin_carpeta:
                return "sin carpeta"
            return "sin datos" if self._remota is None else "ok"

    def iniciar(self):
        self._hilo = threading.Thread(target=self._correr, name="carpeta", daemon=True)
        self._hilo.start()

    def detener(self):
        self._parar.set()
        self._despertar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=5)
        self._guardar_base(forzar=True)

    def canal_abierto(self):
        with self._candado:
            self._canal = True
            self._remota = None
            self._pedidos.clear()
            self._mandar_indice = True
        self._despertar.set()

    def canal_cerrado(self):
        with self._candado:
            self._canal = False
            self._remota = None
            self._pedidos.clear()

    # ---- Desde el hilo de red --------------------------------------------------------------
    def recibir_indice(self, cuerpo):
        datos = leer_json(cuerpo)
        if datos is None:
            return
        with self._candado:
            if datos.get("sin_carpeta"):
                self._remota, self._remota_sin_carpeta = None, True
                return
            archivos = datos.get("archivos")
            if not isinstance(archivos, dict):
                return
            remota = {}
            for ruta, valor in archivos.items():
                try:
                    remota[str(ruta)] = (int(valor[0]), int(valor[1]))
                except (TypeError, ValueError, IndexError):
                    continue
            self._remota, self._remota_sin_carpeta = remota, False
        self._despertar.set()

    def recibir_pedido(self, cuerpo):
        """La otra PC pide archivos de esta carpeta: se le mandan los que existan."""
        datos = leer_json(cuerpo)
        if datos is None or not isinstance(datos.get("rutas"), list):
            return
        entradas = []
        for ruta in datos["rutas"][:10000]:
            if not isinstance(ruta, str) or ignorar(ruta.rsplit("/", 1)[-1]):
                continue
            completa = self.carpeta.joinpath(*ruta.split("/"))
            try:
                # Solo archivos que de verdad están dentro de la carpeta.
                completa.resolve().relative_to(self.carpeta.resolve())
                info = completa.stat()
            except (OSError, ValueError):
                continue
            if completa.is_file():
                entradas.append(Entrada(str(completa), ruta, info.st_size, info.st_mtime_ns))
        if entradas:
            self._mandar(entradas)

    def antes_de_reemplazar(self, ruta, final):
        """Justo antes de pisar un archivo con el que llegó: si cambió acá desde que se
        pidió, se guarda una copia "en conflicto" para no perder lo tuyo."""
        with self._candado:
            pedido = self._pedidos.get(ruta)
        if pedido is None or not os.path.exists(final):
            return
        try:
            info = os.stat(final)
        except OSError:
            return
        if not igual((info.st_size, info.st_mtime_ns), pedido[1]) and pedido[1] is not None:
            self._renombrar_conflicto(ruta)

    def archivo_recibido(self, ruta, tam, mtime):
        with self._candado:
            self._pedidos.pop(ruta, None)
            self._base[ruta] = (tam, mtime)
            self._base_cambiada = True
            self._mandar_indice = True  # Que la otra PC se entere de que ya lo tenemos.
        self._despertar.set()

    # ---- Hilo ------------------------------------------------------------------------------
    def _correr(self):
        while not self._parar.is_set():
            try:
                self._vuelta()
            except Exception as error:  # Un error raro no tiene que apagar la sincronización.
                self._registrar(f"Carpeta compartida: error inesperado ({error!r}).")
            self._despertar.wait(INTERVALO_REVISION_S)
            self._despertar.clear()

    def _vuelta(self):
        if not self.carpeta.is_dir():
            if self.ultimo_estado != "sin carpeta":
                self.ultimo_estado = "sin carpeta"
                self._registrar(f"Carpeta compartida: no encuentro {self.carpeta}. "
                                "¿Se desenchufó el disco o la borraste?")
            if self._canal:
                self._enviar(Tipo.CARPETA_INDICE, armar_json(sin_carpeta=True))
            return
        with self._candado:
            anterior = dict(self._local)
        local = revisar(self.carpeta, anterior)
        with self._candado:
            cambio = local != self._local or self._mandar_indice
            self._local = local
            canal, remota = self._canal, self._remota
            if canal and cambio:
                self._mandar_indice = False
        if canal and cambio:
            self._enviar(Tipo.CARPETA_INDICE, armar_json(archivos={r: list(v) for r, v in
                                                                   local.items()}))
        if canal and remota is not None:
            self._sincronizar(local, remota)
        self._guardar_base()

    def _sincronizar(self, local, remota):
        with self._candado:
            base = dict(self._base)
        if not remota and base:
            if self.ultimo_estado != "remota vacía":
                self.ultimo_estado = "remota vacía"
                self._registrar("Carpeta compartida: la de la otra PC está vacía. Por las "
                                "dudas no borro nada acá (si la vaciaste a propósito, borrá "
                                "los archivos acá también).")
            return
        pedir, borrar, conflicto, base = decidir(local, remota, base, self._gana_la_otra)
        with self._candado:
            if base != self._base:
                self._base = base
                self._base_cambiada = True
        for ruta in conflicto:
            self._renombrar_conflicto(ruta)
        for ruta in borrar:
            self._borrar(ruta, local[ruta])
        ahora = time.monotonic()
        with self._candado:
            for ruta, (cuando, _) in list(self._pedidos.items()):
                if ahora - cuando > _PEDIDO_VENCE_S:
                    del self._pedidos[ruta]
            nuevos = [r for r in pedir + conflicto if r not in self._pedidos]
            for ruta in nuevos:
                self._pedidos[ruta] = (ahora, local.get(ruta))
        if nuevos:
            self._enviar(Tipo.CARPETA_PEDIDO, armar_json(rutas=nuevos))
        estado = "al día" if not (pedir or borrar or conflicto) else "sincronizando"
        if estado != self.ultimo_estado:
            if estado == "al día" and self.ultimo_estado == "sincronizando":
                self._registrar("Carpeta compartida: al día en las dos PCs.")
            self.ultimo_estado = estado

    def _gana_la_otra(self, ruta):
        """Desempate de un conflicto: el archivo más nuevo; si tienen la misma hora, el
        de la PC con el número de identidad más alto (las dos llegan a lo mismo)."""
        local, remota = self._local.get(ruta), (self._remota or {}).get(ruta)
        if local is None or remota is None:
            return remota is not None
        return (remota[1], self._id_otra) > (local[1], self._id_propio)

    def _renombrar_conflicto(self, ruta):
        origen = self.carpeta.joinpath(*ruta.split("/"))
        destino_relativo = nombre_conflicto(ruta, self._nombre_pc)
        destino = self.carpeta.joinpath(*destino_relativo.split("/"))
        try:
            os.replace(origen, destino)
        except OSError as error:
            self._registrar(f"Carpeta compartida: no se pudo guardar la copia en conflicto de "
                            f"{ruta}: {error}.")
            return
        with self._candado:
            self._local.pop(ruta, None)
            self._mandar_indice = True
        self._registrar(f"Carpeta compartida: {ruta} cambió en las dos PCs. Quedó la versión "
                        f"más nueva y la tuya se guardó como {destino.name}.")

    def _borrar(self, ruta, como_estaba):
        completa = self.carpeta.joinpath(*ruta.split("/"))
        try:
            info = completa.stat()
        except OSError:
            return
        if not igual((info.st_size, info.st_mtime_ns), como_estaba):
            return  # Cambió recién: no se borra (en la próxima vuelta se decide de nuevo).
        try:
            self._papelera(str(completa))
        except OSError as error:
            self._registrar(f"Carpeta compartida: no se pudo borrar {ruta}: {error}.")
            return
        with self._candado:
            self._local.pop(ruta, None)
            self._base.pop(ruta, None)
            self._base_cambiada = True
            self._mandar_indice = True
        self._registrar(f"Carpeta compartida: se borró {ruta} en la otra PC; acá fue a la "
                        "Papelera de reciclaje.")

    # ---- La base (lo último que coincidía en las dos) --------------------------------------
    def _clave_estado(self):
        return f"{self._id_otra}|{os.path.normcase(str(self.carpeta.resolve()))}"

    def _cargar_base(self):
        try:
            todo = json.loads(self._ruta_estado.read_text(encoding="utf-8"))
            datos = todo.get(self._clave_estado(), {})
            return {str(r): (int(v[0]), int(v[1])) for r, v in datos.items()}
        except (OSError, ValueError, AttributeError, TypeError, IndexError):
            return {}

    def _guardar_base(self, forzar=False):
        ahora = time.monotonic()
        with self._candado:
            if not self._base_cambiada or (not forzar and ahora - self._t_guardado < _GUARDAR_CADA_S):
                return
            base = {r: list(v) for r, v in self._base.items()}
            self._base_cambiada = False
            self._t_guardado = ahora
        try:
            todo = json.loads(self._ruta_estado.read_text(encoding="utf-8"))
            if not isinstance(todo, dict):
                todo = {}
        except (OSError, ValueError):
            todo = {}
        todo[self._clave_estado()] = base
        try:
            self._ruta_estado.parent.mkdir(parents=True, exist_ok=True)
            temporal = self._ruta_estado.with_name(self._ruta_estado.name + ".tmp")
            temporal.write_text(json.dumps(todo), encoding="utf-8")
            os.replace(temporal, self._ruta_estado)
        except OSError:
            pass
