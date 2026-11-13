"""Pasar archivos de una PC a la otra por el canal de datos (sin Qt, para poder probarlo).

Un "envío" es un grupo de archivos (lo que copiaste, lo que arrastraste, o lo que
pidió la carpeta sincronizada). Viaja así:

    ARCHIVO_INICIO  {"envio": 7, "ruta": "fotos/playa.jpg", "tam": 2400000, ...}
    ARCHIVO_DATOS   [7][256 KB del archivo]   (tantos como hagan falta)
    ARCHIVO_FIN     {"envio": 7, "ruta": "fotos/playa.jpg", "ok": true}
    ... el siguiente archivo ...
    ARCHIVO_FIN     {"envio": 7, "terminado": true}

Cuidados:
  * El que manda lee de a 256 KB y espera si hay mucho en cola: un archivo de
    10 GB no llena la memoria.
  * El que recibe escribe en un archivo ".mcparcial" y recién al final le pone
    el nombre de verdad: si se corta a la mitad, no queda un archivo roto con
    nombre de bueno.
  * Las rutas que llegan se revisan (ruta_segura): nada de "..", "C:\\" ni
    nombres prohibidos de Windows. Aunque la otra PC esté emparejada, no se le
    deja escribir fuera de la carpeta que corresponde.
"""

import json
import os
import shutil
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..red.protocolo import Tipo

PEDAZO = 256 * 1024
_NUMERO = struct.Struct("<I")
_INTERVALO_PROGRESO_S = 0.2
_RESERVA_DISCO = 100 * 1024 * 1024  # Que siempre queden al menos 100 MB libres.
SUFIJO_PARCIAL = ".mcparcial"

PORTAPAPELES = "portapapeles"  # Copiaste archivos y los pegás en la otra PC.
ENVIADOS = "enviados"  # Los mandaste a propósito (arrastrar a la ventana, "Enviar a").
CARPETA = "carpeta"  # Los pide la carpeta sincronizada.

_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
               *(f"LPT{i}" for i in range(1, 10))}
_PROHIBIDOS = set('<>:"|?*') | {chr(i) for i in range(32)}


@dataclass
class Entrada:
    """Un archivo (o una carpeta vacía) a mandar."""

    origen: str  # Ruta completa en esta PC.
    ruta: str  # Ruta relativa con "/", como llega a la otra PC.
    tam: int
    mtime: int  # Fecha de modificación en nanosegundos.
    carpeta: bool = False


@dataclass
class Progreso:
    """Lo que la interfaz muestra de un envío."""

    clave: str  # "sale-7" o "llega-7": único en esta PC.
    sale: bool  # True = de esta PC a la otra.
    motivo: str
    descripcion: str  # "3 archivos" o "playa.jpg".
    total: int
    cantidad: int
    hecho: int = 0
    archivos_hechos: int = 0
    estado: str = "en curso"  # "en curso", "terminado", "cancelado" o "error"
    detalle: str = ""
    inicio: float = field(default_factory=time.monotonic)
    destino: str = ""  # Carpeta donde quedaron (solo los que llegan).
    rutas_finales: list = field(default_factory=list)  # De primer nivel (para el portapapeles).
    extra: dict = field(default_factory=dict)

    @property
    def fraccion(self):
        return 1.0 if self.total <= 0 else min(1.0, self.hecho / self.total)

    @property
    def velocidad(self):
        """Bytes por segundo desde que empezó."""
        transcurrido = time.monotonic() - self.inicio
        return self.hecho / transcurrido if transcurrido > 0.2 else 0.0


def describir(entradas):
    archivos = [e for e in entradas if not e.carpeta]
    raices = {e.ruta.split("/", 1)[0] for e in entradas}
    if len(raices) == 1 and len(archivos) <= 1:
        return next(iter(raices))
    if len(raices) == 1:
        return f"la carpeta {next(iter(raices))} ({len(archivos)} archivos)"
    return f"{len(archivos)} archivos" if archivos else f"{len(raices)} carpetas"


def peso(bytes_):
    if bytes_ >= 1024 ** 3:
        return f"{bytes_ / 1024 ** 3:.1f} GB".replace(".", ",")
    if bytes_ >= 1024 ** 2:
        return f"{bytes_ / 1024 ** 2:.1f} MB".replace(".", ",")
    return f"{max(1, round(bytes_ / 1024))} KB"


# =====================================================================================
# Armar la lista de lo que se manda
# =====================================================================================
def listar(rutas, ignorar=lambda nombre: False):
    """Convierte rutas (archivos y carpetas) en la lista de Entradas a mandar."""
    entradas = []
    for ruta in rutas:
        ruta = Path(ruta)
        try:
            if ruta.is_file():
                info = ruta.stat()
                entradas.append(Entrada(str(ruta), ruta.name, info.st_size, info.st_mtime_ns))
            elif ruta.is_dir():
                entradas.extend(_listar_carpeta(ruta, ruta.name, ignorar))
        except OSError:
            continue  # Se borró justo, o no hay permiso: se saltea.
    return entradas


def _listar_carpeta(carpeta, nombre, ignorar):
    entradas = [Entrada(str(carpeta), nombre, 0, 0, carpeta=True)]
    for raiz, carpetas, archivos in os.walk(carpeta):  # No sigue accesos directos de carpetas.
        carpetas[:] = [c for c in carpetas if not ignorar(c)]
        relativa = Path(raiz).relative_to(carpeta)
        for c in carpetas:
            entradas.append(Entrada(os.path.join(raiz, c),
                                    "/".join((nombre, *relativa.parts, c)), 0, 0, carpeta=True))
        for a in archivos:
            if ignorar(a):
                continue
            completa = os.path.join(raiz, a)
            try:
                info = os.stat(completa)
            except OSError:
                continue
            entradas.append(Entrada(completa, "/".join((nombre, *relativa.parts, a)),
                                    info.st_size, info.st_mtime_ns))
    return entradas


def ruta_segura(base, relativa):
    """Devuelve dónde escribir `relativa` dentro de `base`. Lanza ValueError si es peligrosa."""
    if not isinstance(relativa, str) or not relativa or len(relativa) > 1000:
        raise ValueError("Ruta vacía o demasiado larga")
    if "\\" in relativa or relativa.startswith("/"):
        raise ValueError("Ruta con formato inválido")
    partes = relativa.split("/")
    for parte in partes:
        if not parte or parte in (".", ".."):
            raise ValueError("Ruta con partes inválidas")
        if any(c in _PROHIBIDOS for c in parte) or parte[-1] in ". ":
            raise ValueError(f"Nombre no permitido en Windows: {parte}")
        if parte.split(".", 1)[0].upper() in _RESERVADOS:
            raise ValueError(f"Nombre reservado de Windows: {parte}")
    base = Path(base).resolve()
    destino = base.joinpath(*partes)
    if os.path.commonpath([str(base), str(destino.resolve())]) != str(base):
        raise ValueError("La ruta se sale de la carpeta")
    return destino


def nombre_libre(carpeta, nombre):
    """"foto.jpg", o "foto (2).jpg" si ya existe, y así."""
    destino = Path(carpeta) / nombre
    if not destino.exists():
        return nombre
    base, punto, extension = nombre.rpartition(".")
    if not punto or not base:
        base, extension = nombre, ""
    for i in range(2, 10000):
        candidato = f"{base} ({i}).{extension}" if extension else f"{base} ({i})"
        if not (Path(carpeta) / candidato).exists():
            return candidato
    raise OSError("No encontré un nombre libre")


# =====================================================================================
# El que manda
# =====================================================================================
class Emisor(threading.Thread):
    """Manda un envío, en su propio hilo.

    `enviar(tipo, cuerpo)` y `enviar_bloque(tipo, cuerpo, timeout)` son los del
    canal de datos; `al_cambiar(progreso)` se llama cada tanto y al terminar.
    """

    def __init__(self, numero, motivo, entradas, enviar, enviar_bloque, al_cambiar,
                 extra=None, descripcion=None):
        super().__init__(name=f"envio-{numero}", daemon=True)
        self.numero = numero
        self.motivo = motivo
        self.entradas = entradas
        # Todo lo del envío va por la cola de pedazos, también el inicio y el fin de
        # cada archivo: si fueran por la cola rápida, el "terminó" se adelantaría a
        # los últimos pedazos. (`enviar` queda por compatibilidad.)
        self._enviar = lambda tipo, cuerpo: enviar_bloque(tipo, cuerpo, None)
        self._enviar_bloque = enviar_bloque
        self._al_cambiar = al_cambiar
        self._extra = extra or {}
        self._cancelado = threading.Event()
        archivos = [e for e in entradas if not e.carpeta]
        self.progreso = Progreso(
            f"sale-{numero}", True, motivo, descripcion or describir(entradas),
            sum(e.tam for e in archivos), len(archivos), extra=dict(self._extra))
        self._t_aviso = 0.0

    def cancelar(self, motivo="Cancelado"):
        self.progreso.detalle = motivo
        self._cancelado.set()

    def run(self):
        progreso = self.progreso
        try:
            for indice, entrada in enumerate(self.entradas):
                if self._cancelado.is_set():
                    break
                self._mandar(indice, entrada)
            if self._cancelado.is_set():
                progreso.estado = "cancelado"
                self._enviar(Tipo.ENVIO_CANCELADO, _json(envio=self.numero, lado="emisor",
                                                         motivo=progreso.detalle))
            else:
                self._enviar(Tipo.ARCHIVO_FIN, _json(envio=self.numero, terminado=True))
                progreso.estado = "terminado"
        except _CanalCerrado:
            progreso.estado = "error"
            progreso.detalle = "Se cortó la conexión con la otra PC"
        self._avisar(forzar=True)

    def _mandar(self, indice, entrada):
        cabecera = dict(envio=self.numero, motivo=self.motivo, ruta=entrada.ruta, tam=entrada.tam,
                        mtime=entrada.mtime, carpeta=entrada.carpeta, indice=indice,
                        cantidad=self.progreso.cantidad, total=self.progreso.total,
                        descripcion=self.progreso.descripcion, **self._extra)
        if entrada.carpeta:
            if not self._enviar(Tipo.ARCHIVO_INICIO, _json(**cabecera)):
                raise _CanalCerrado()
            return
        try:
            archivo = open(entrada.origen, "rb")
        except OSError as error:
            self._enviar(Tipo.ARCHIVO_FIN, _json(envio=self.numero, ruta=entrada.ruta, ok=False,
                                                 motivo=f"No se pudo abrir: {error}"))
            self.progreso.hecho += entrada.tam  # Para que la barra no quede trabada.
            return
        with archivo:
            if not self._enviar(Tipo.ARCHIVO_INICIO, _json(**cabecera)):
                raise _CanalCerrado()
            prefijo = _NUMERO.pack(self.numero)
            mandados = 0
            while not self._cancelado.is_set():
                try:
                    pedazo = archivo.read(PEDAZO)
                except OSError as error:
                    self._enviar(Tipo.ARCHIVO_FIN, _json(envio=self.numero, ruta=entrada.ruta,
                                                         ok=False, motivo=str(error)))
                    return
                if not pedazo:
                    break
                if not self._enviar_bloque(Tipo.ARCHIVO_DATOS, prefijo + pedazo, None):
                    raise _CanalCerrado()
                mandados += len(pedazo)
                self.progreso.hecho += len(pedazo)
                self._avisar()
            if self._cancelado.is_set():
                return
            # Si el archivo cambió mientras se mandaba, el tamaño no coincide y la otra
            # PC lo descarta (mejor nada que un archivo mezclado).
            ok = mandados == entrada.tam
            self._enviar(Tipo.ARCHIVO_FIN, _json(envio=self.numero, ruta=entrada.ruta, ok=ok,
                                                 tam=mandados))
            self.progreso.archivos_hechos += 1
            self.progreso.hecho += entrada.tam - mandados

    def _avisar(self, forzar=False):
        ahora = time.monotonic()
        if forzar or ahora - self._t_aviso >= _INTERVALO_PROGRESO_S:
            self._t_aviso = ahora
            self._al_cambiar(self.progreso)


class _CanalCerrado(Exception):
    pass


# =====================================================================================
# El que recibe
# =====================================================================================
class _Llegada:
    def __init__(self, numero, motivo, base, progreso):
        self.numero = numero
        self.motivo = motivo
        self.base = base
        self.progreso = progreso
        self.raices = {}  # Nombre de primer nivel que mandó la otra PC -> nombre usado acá.
        self.archivo = None
        self.parcial = None
        self.final = None
        self.info = None
        self.recibidos = 0
        self.t_aviso = 0.0


class Receptor:
    """Recibe envíos. Sus métodos se llaman desde el hilo de red (uno por tipo de mensaje).

    `destino(motivo, info)` devuelve la carpeta donde guardar ese envío (o lanza
    ValueError con el motivo para rechazarlo). `al_cambiar(progreso)` avisa el
    avance; `al_archivo(progreso, info, ruta_final)` se llama por cada archivo
    terminado (lo usa la carpeta sincronizada). `enviar` es el del canal (para
    avisar si se cancela).
    """

    def __init__(self, destino, al_cambiar, enviar, al_archivo=None, antes_de_reemplazar=None):
        self._destino = destino
        self._al_cambiar = al_cambiar
        self._al_archivo = al_archivo
        self._antes_de_reemplazar = antes_de_reemplazar
        self._enviar = enviar
        self._llegadas = {}
        self._candado = threading.Lock()

    def registrar_en(self, enlace):
        """Atiende los mensajes de archivos en el hilo de red de `enlace`."""
        enlace.atender_en_hilo(Tipo.ARCHIVO_INICIO, self.inicio)
        enlace.atender_en_hilo(Tipo.ARCHIVO_DATOS, self.datos)
        enlace.atender_en_hilo(Tipo.ARCHIVO_FIN, self.fin)

    def cancelar(self, numero, motivo="Cancelado en esta PC"):
        """El usuario canceló un envío que estaba llegando."""
        with self._candado:
            llegada = self._llegadas.pop(numero, None)
        if llegada is None:
            return
        self._enviar(Tipo.ENVIO_CANCELADO, _json(envio=numero, lado="receptor", motivo=motivo))
        self._abortar(llegada, "cancelado", motivo)

    def cancelado_alla(self, numero, motivo):
        """La otra PC canceló el envío que estaba mandando."""
        with self._candado:
            llegada = self._llegadas.pop(numero, None)
        if llegada is not None:
            self._abortar(llegada, "cancelado", motivo or "Se canceló en la otra PC")

    def cortar_todo(self):
        """Se cortó el canal: lo que estaba llegando queda a medias y se borra."""
        with self._candado:
            llegadas, self._llegadas = list(self._llegadas.values()), {}
        for llegada in llegadas:
            self._abortar(llegada, "error", "Se cortó la conexión con la otra PC")

    # ---- Mensajes -----------------------------------------------------------------------
    def inicio(self, cuerpo):
        info = _leer(cuerpo)
        if info is None:
            return
        numero = info.get("envio")
        with self._candado:
            llegada = self._llegadas.get(numero)
        if llegada is None:
            llegada = self._empezar(numero, info)
            if llegada is None:
                return
        self._cerrar_archivo(llegada)  # Por si el anterior no terminó bien.
        try:
            destino = self._ubicar(llegada, info.get("ruta"))
            if info.get("carpeta"):
                destino.mkdir(parents=True, exist_ok=True)
                return
            destino.parent.mkdir(parents=True, exist_ok=True)
            parcial = destino.with_name(destino.name + SUFIJO_PARCIAL)
            llegada.archivo = open(parcial, "wb")
            llegada.parcial, llegada.final, llegada.info = parcial, destino, info
            llegada.recibidos = 0
        except (ValueError, OSError) as error:
            llegada.progreso.detalle = f"No se pudo guardar {info.get('ruta')}: {error}"
            llegada.archivo = None

    def datos(self, cuerpo):
        if len(cuerpo) < 4:
            return
        numero = _NUMERO.unpack_from(cuerpo)[0]
        with self._candado:
            llegada = self._llegadas.get(numero)
        if llegada is None:
            return  # Envío cancelado o rechazado: se tira lo que siga llegando.
        pedazo = memoryview(cuerpo)[4:]
        if llegada.archivo is not None:
            try:
                llegada.archivo.write(pedazo)
            except OSError as error:
                self.cancelar(numero, f"No se pudo escribir en el disco: {error}")
                return
        llegada.recibidos += len(pedazo)
        llegada.progreso.hecho += len(pedazo)
        ahora = time.monotonic()
        if ahora - llegada.t_aviso >= _INTERVALO_PROGRESO_S:
            llegada.t_aviso = ahora
            self._al_cambiar(llegada.progreso)

    def fin(self, cuerpo):
        info = _leer(cuerpo)
        if info is None:
            return
        numero = info.get("envio")
        with self._candado:
            llegada = self._llegadas.get(numero)
        if llegada is None:
            return
        if info.get("terminado"):
            with self._candado:
                self._llegadas.pop(numero, None)
            self._cerrar_archivo(llegada)
            llegada.progreso.estado = "terminado"
            self._al_cambiar(llegada.progreso)
            return
        archivo, llegada.archivo = llegada.archivo, None
        if archivo is None:
            return
        archivo.close()
        esperado = llegada.info.get("tam")
        if not info.get("ok") or llegada.recibidos != esperado:
            _borrar(llegada.parcial)
            if info.get("motivo"):
                llegada.progreso.detalle = f"{info.get('ruta')}: {info.get('motivo')}"
            return
        try:
            if self._antes_de_reemplazar is not None:
                self._antes_de_reemplazar(llegada.progreso, llegada.info, llegada.final)
            os.replace(llegada.parcial, llegada.final)
            mtime = int(llegada.info.get("mtime") or 0)
            if mtime > 0:
                os.utime(llegada.final, ns=(mtime, mtime))  # Misma fecha que en la otra PC.
        except OSError as error:
            _borrar(llegada.parcial)
            llegada.progreso.detalle = f"No se pudo guardar {llegada.final.name}: {error}"
            return
        llegada.progreso.archivos_hechos += 1
        if self._al_archivo is not None:
            self._al_archivo(llegada.progreso, llegada.info, llegada.final)

    # ---- Internos -----------------------------------------------------------------------
    def _empezar(self, numero, info):
        motivo = info.get("motivo", ENVIADOS)
        progreso = Progreso(
            f"llega-{numero}", False, motivo, str(info.get("descripcion", ""))[:200],
            int(info.get("total") or 0), int(info.get("cantidad") or 0),
            extra={k: v for k, v in info.items() if k in ("oferta",)})
        try:
            base = Path(self._destino(motivo, info))
            base.mkdir(parents=True, exist_ok=True)
            libre = shutil.disk_usage(base).free
            if libre < progreso.total + _RESERVA_DISCO:
                raise ValueError(f"No hay lugar en el disco de esta PC (hacen falta "
                                 f"{peso(progreso.total)}, quedan {peso(libre)})")
        except (ValueError, OSError) as error:
            self._enviar(Tipo.ENVIO_CANCELADO, _json(envio=numero, lado="receptor",
                                                     motivo=str(error)))
            progreso.estado, progreso.detalle = "error", str(error)
            self._al_cambiar(progreso)
            return None
        progreso.destino = str(base)
        llegada = _Llegada(numero, motivo, base, progreso)
        with self._candado:
            self._llegadas[numero] = llegada
        self._al_cambiar(progreso)
        return llegada

    def _ubicar(self, llegada, ruta):
        """Dónde va este archivo. Los nombres de primer nivel no pisan nada existente
        (salvo en la carpeta sincronizada, donde reemplazar es justamente la idea)."""
        if not isinstance(ruta, str):
            raise ValueError("Ruta inválida")
        raiz, _, resto = ruta.partition("/")
        if llegada.motivo != CARPETA:
            if raiz not in llegada.raices:
                ruta_segura(llegada.base, raiz)  # Valida antes de usar el nombre.
                libre = nombre_libre(llegada.base, raiz)
                llegada.raices[raiz] = libre
                llegada.progreso.rutas_finales.append(str(Path(llegada.base) / libre))
            ruta = llegada.raices[raiz] + ("/" + resto if resto else "")
        return ruta_segura(llegada.base, ruta)

    def _cerrar_archivo(self, llegada):
        archivo, llegada.archivo = llegada.archivo, None
        if archivo is not None:
            archivo.close()
            _borrar(llegada.parcial)

    def _abortar(self, llegada, estado, motivo):
        self._cerrar_archivo(llegada)
        llegada.progreso.estado = estado
        llegada.progreso.detalle = motivo
        self._al_cambiar(llegada.progreso)


# =====================================================================================
# Todo junto: los envíos que salen y los que llegan
# =====================================================================================
class Transferencias:
    """Lleva la cuenta de los envíos en curso, en los dos sentidos.

    `canal` tiene enviar(tipo, cuerpo) y enviar_bloque(tipo, cuerpo, timeout).
    `al_cambiar(progreso)` se llama desde otros hilos cada vez que algo avanza.
    """

    def __init__(self, canal, destino, al_cambiar, al_archivo=None, antes_de_reemplazar=None):
        self._canal = canal
        self._al_cambiar = al_cambiar
        self.receptor = Receptor(destino, al_cambiar, canal.enviar, al_archivo,
                                 antes_de_reemplazar)
        self._emisores = {}
        self._numero = 0
        self._candado = threading.Lock()

    def registrar_en(self, enlace):
        """Atiende en el hilo de red los mensajes de archivos que lleguen por `enlace`."""
        self.receptor.registrar_en(enlace)
        enlace.atender_en_hilo(Tipo.ENVIO_CANCELADO, self.cancelado_alla)

    def mandar(self, entradas, motivo, extra=None, descripcion=None):
        """Empieza a mandar esos archivos. Devuelve el Progreso del envío."""
        with self._candado:
            self._numero += 1
            numero = self._numero

        def al_cambiar(progreso):
            if progreso.estado != "en curso":
                with self._candado:
                    self._emisores.pop(numero, None)
            self._al_cambiar(progreso)

        emisor = Emisor(numero, motivo, entradas, self._canal.enviar, self._canal.enviar_bloque,
                        al_cambiar, extra=extra, descripcion=descripcion)
        with self._candado:
            self._emisores[numero] = emisor
        self._al_cambiar(emisor.progreso)
        emisor.start()
        return emisor.progreso

    def cancelar(self, clave):
        """El usuario tocó Cancelar en un envío ("sale-3" o "llega-5")."""
        sentido, _, numero = clave.partition("-")
        try:
            numero = int(numero)
        except ValueError:
            return
        if sentido == "sale":
            with self._candado:
                emisor = self._emisores.get(numero)
            if emisor is not None:
                emisor.cancelar("Cancelado en esta PC")
        else:
            self.receptor.cancelar(numero)

    def cancelado_alla(self, cuerpo):
        """La otra PC canceló: un envío nuestro (lado receptor) o uno suyo (lado emisor)."""
        datos = _leer(cuerpo)
        if datos is None:
            return
        numero, motivo = datos.get("envio"), str(datos.get("motivo") or "")
        if datos.get("lado") == "receptor":
            with self._candado:
                emisor = self._emisores.get(numero)
            if emisor is not None:
                emisor.cancelar(f"La otra PC no lo quiso recibir: {motivo}" if motivo
                                else "Se canceló en la otra PC")
        else:
            self.receptor.cancelado_alla(numero, motivo)

    def cortar_todo(self):
        """Se cortó el canal: todo lo que estaba en curso termina."""
        with self._candado:
            emisores = list(self._emisores.values())
        for emisor in emisores:
            emisor.cancelar("Se cortó la conexión con la otra PC")
        self.receptor.cortar_todo()


def _json(**datos):
    return json.dumps(datos, ensure_ascii=False).encode("utf-8")


def _leer(cuerpo):
    try:
        datos = json.loads(bytes(cuerpo).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return datos if isinstance(datos, dict) else None


def leer_json(cuerpo):
    """Para los otros módulos: el dict de un mensaje JSON, o None si no se entiende."""
    return _leer(cuerpo)


def armar_json(**datos):
    return _json(**datos)


def _borrar(ruta):
    if ruta is None:
        return
    try:
        os.remove(ruta)
    except OSError:
        pass
