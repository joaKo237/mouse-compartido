"""Archivos entre las dos PCs, del lado de la interfaz.

Tres formas de pasar archivos, todas por el canal de datos (nunca por el del mouse):

1. Copiar y pegar (Ctrl+C en el Explorador de una PC, Ctrl+V en la otra).
   Al copiar, esta PC le "ofrece" los archivos a la otra:
     * Si pesan poco (hasta 64 MB) viajan enseguida, así ya están cuando pegues.
     * Si pesan más, viajan recién cuando llevás el mouse a la otra PC: si
       copiaste una película para pegarla en esta misma PC, no se manda al cuete.
   Cuando terminan de llegar, se ponen en el portapapeles de la otra PC como si
   los hubieras copiado ahí (quedan en una carpeta temporal hasta que pegues).

2. Mandar a propósito: arrastrarlos a la ventana del programa, el botón
   "Mandar archivos…" o el clic derecho → Enviar a → Mouse Compartido.
   Llegan a Descargas\\Mouse Compartido (o a la carpeta que elijas).

3. La carpeta sincronizada (datos/carpeta.py): esta clase solo la arranca, la
   frena y le pasa los mensajes.

¿Por qué no arrastrar un archivo hasta el borde de la pantalla? Porque en Windows
el arrastre lo maneja el programa de origen (el Explorador) y no hay forma
confiable de "continuarlo" en otra PC. Copiar y pegar hace lo mismo y no falla.
"""

import shutil
import socket
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Signal

from ..datos import transferencias as T
from ..datos.carpeta import SincroCarpeta
from ..red.protocolo import Tipo
from ..sistema.papelera import a_la_papelera
from .portapapeles import poner_archivos_en_windows

AL_TOQUE = 64 * 1024 * 1024  # Hasta esto, lo copiado viaja enseguida.
CARPETA_TEMPORAL = Path(tempfile.gettempdir()) / "Mouse Compartido" / "portapapeles"
_VIDA_TEMPORALES_S = 24 * 3600  # Lo pegado hace más de un día se borra al abrir el programa.


def carpeta_recibidos(config):
    """Dónde se guardan los archivos que te mandan desde la otra PC."""
    if config.carpeta_recibidos:
        return Path(config.carpeta_recibidos)
    descargas = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
    return Path(descargas or Path.home() / "Downloads") / "Mouse Compartido"


def limpiar_temporales(ahora=None):
    """Borra las tandas viejas de archivos pegados (se llama en un hilo al abrir)."""
    ahora = ahora or time.time()
    try:
        tandas = list(CARPETA_TEMPORAL.iterdir())
    except OSError:
        return
    for tanda in tandas:
        try:
            if ahora - tanda.stat().st_mtime > _VIDA_TEMPORALES_S:
                shutil.rmtree(tanda, ignore_errors=True)
        except OSError:
            pass


class GestorArchivos(QObject):
    progreso_cambiado = Signal(object)  # Un Progreso (copia), en el hilo de la ventana.
    nuevo_registro = Signal(str)  # Una línea para la actividad.
    aviso = Signal(str, str)  # (título, texto) para un globito de la bandeja.
    _progreso = Signal(object)  # Desde los hilos de red y de envío.
    _registro = Signal(str)
    _listado = Signal(object, object)  # (función, entradas): terminó de listar en un hilo.

    def __init__(self, config, enlace, ruta_estado_carpeta, poner_archivos=poner_archivos_en_windows,
                 parent=None):
        super().__init__(parent)
        self.config = config
        self._enlace = enlace
        self._ruta_estado = Path(ruta_estado_carpeta)
        self._poner_archivos = poner_archivos
        self._mouse_aca = True

        self.transferencias = T.Transferencias(
            enlace, self._destino, lambda p: self._progreso.emit(_copia(p)),
            al_archivo=self._al_archivo, antes_de_reemplazar=self._antes_de_reemplazar)
        self.transferencias.registrar_en(enlace)
        enlace.atender_en_hilo(Tipo.CARPETA_INDICE, self._indice_de_la_otra)
        enlace.atender_en_hilo(Tipo.CARPETA_PEDIDO, self._pedido_de_la_otra)
        enlace.mensaje.connect(self._al_llegar)
        enlace.abierto.connect(self._al_abrirse_canal)
        enlace.cerrado.connect(self._al_cerrarse_canal)

        self._progreso.connect(self._al_progresar)
        self._registro.connect(self._registrar)
        self._listado.connect(lambda funcion, entradas: funcion(entradas))

        # Copiar y pegar: lo que ofrece esta PC y lo que ofrece la otra.
        self._numero = 0  # Cuenta cada copia (para descartar listados que llegan tarde).
        self._oferta_saliente = None  # {"numero", "entradas", "descripcion"}
        self._envio_portapapeles = None  # Clave ("sale-N") del envío por portapapeles en curso.
        self._oferta_entrante = None  # {"numero", "descripcion", "total", "estado"}
        self._llegada_portapapeles = None  # Clave ("llega-N") de lo que está llegando.

        self._carpeta = None
        self._clave_carpeta = None
        self._armar_carpeta()

    # =====================================================================================
    # Lo que usa la app
    # =====================================================================================
    def poner_config(self, config):
        self.config = config
        self._armar_carpeta()

    def poner_mouse_aca(self, aca):
        """La app avisa si el mouse está manejando esta PC (para las ofertas grandes)."""
        llego = aca and not self._mouse_aca
        self._mouse_aca = aca
        if llego:
            self._pedir_oferta()

    def mandar(self, rutas):
        """Manda esos archivos o carpetas a la otra PC, a su carpeta de recibidos.
        Devuelve un texto con el problema, o "" si empezó."""
        if not self._enlace.listo:
            return "Las dos PCs tienen que estar conectadas para mandar archivos."
        if not self.config.compartir_archivos:
            return "Pasar archivos está apagado en esta PC (se prende en Compartir)."
        rutas = [str(r) for r in rutas if r]
        if not rutas:
            return "No hay nada para mandar."

        def mandar_lista(entradas):
            if not entradas:
                self._registrar("No se encontró nada para mandar (¿se borró?).")
                return
            progreso = self.transferencias.mandar(entradas, T.ENVIADOS)
            self._registrar(f"Mandando {progreso.descripcion} ({T.peso(progreso.total)}) a la "
                            "otra PC.")

        self._listar_en_hilo(rutas, mandar_lista)
        return ""

    def cancelar(self, clave):
        self.transferencias.cancelar(clave)

    def texto_carpeta(self):
        """Una línea sobre cómo está la carpeta sincronizada (página Compartir)."""
        config = self.config
        if not config.sincronizar_carpeta:
            return "Apagada en esta PC."
        if not config.carpeta_compartida:
            return "Elegí una carpeta y tocá Guardar cambios."
        sincro = self._carpeta
        if sincro is None:
            return "Falta emparejar esta PC con la otra (página Conexión)."
        if sincro.ultimo_estado == "sin carpeta":
            return f"No encuentro {sincro.carpeta}. ¿Se desenchufó el disco o la borraste?"
        if not self._enlace.listo:
            return "Se sincroniza cuando las dos PCs estén conectadas."
        otra = sincro.estado_otra
        if otra == "sin carpeta":
            return "La otra PC tiene la carpeta activada, pero no la encuentra."
        if otra == "sin datos":
            return ("Esperando a la otra PC. Si no avanza, activá la carpeta compartida allá "
                    "también.")
        if sincro.ultimo_estado == "remota vacía":
            return "La carpeta de la otra PC está vacía: por las dudas, acá no se borra nada."
        if sincro.ultimo_estado == "sincronizando":
            return "Sincronizando…"
        return "● Al día en las dos PCs."

    def detener(self):
        """Al cerrar el programa."""
        if self._carpeta is not None:
            self._carpeta.detener()
            self._carpeta = None
        self.transferencias.cortar_todo()

    # ---- Señales del portapapeles (ui/portapapeles.py) -------------------------------------
    def al_copiar_algo(self):
        """Copiaste algo en esta PC: lo que estaba pendiente de antes ya no vale."""
        self._numero += 1
        self._oferta_saliente = None
        self._cancelar(self._envio_portapapeles)
        self._envio_portapapeles = None
        self._descartar_oferta_entrante()

    def al_copiar_archivos(self, rutas):
        """Copiaste archivos en el Explorador de esta PC: se le ofrecen a la otra."""
        if not (self.config.compartir_archivos and self._enlace.listo):
            return
        self._numero += 1
        numero = self._numero
        self._listar_en_hilo(rutas, lambda entradas: self._ofrecer(numero, entradas))

    # =====================================================================================
    # Copiar y pegar
    # =====================================================================================
    def _ofrecer(self, numero, entradas):
        if numero != self._numero or not entradas:
            return  # Mientras se listaba, copiaste otra cosa.
        archivos = [e for e in entradas if not e.carpeta]
        total = sum(e.tam for e in archivos)
        descripcion = T.describir(entradas)
        tope = max(1, self.config.archivos_max_mb) * 1024 * 1024
        if total > tope:
            self._registrar(
                f"Copiaste {descripcion} ({T.peso(total)}): pasa el tope de "
                f"{self.config.archivos_max_mb} MB para copiar y pegar en la otra PC. Para "
                "mandarlo igual, arrastralo a la ventana del programa o usá clic derecho → "
                "Enviar a → Mouse Compartido.")
            return
        al_toque = total <= AL_TOQUE
        self._oferta_saliente = {"numero": numero, "entradas": entradas,
                                 "descripcion": descripcion}
        self._enlace.enviar(Tipo.ARCHIVOS_OFERTA, T.armar_json(
            oferta=numero, descripcion=descripcion, total=total, cantidad=len(archivos),
            ya=al_toque))
        if al_toque:
            self._mandar_oferta()
        else:
            self._registrar(f"Copiaste {descripcion} ({T.peso(total)}). Se pasa a la otra PC "
                            "cuando lleves el mouse allá.")

    def _mandar_oferta(self):
        oferta = self._oferta_saliente
        if oferta is None or self._envio_portapapeles is not None:
            return
        progreso = self.transferencias.mandar(
            oferta["entradas"], T.PORTAPAPELES, extra={"oferta": oferta["numero"]},
            descripcion=oferta["descripcion"])
        self._envio_portapapeles = progreso.clave

    def _llego_oferta(self, datos):
        self._descartar_oferta_entrante()
        al_toque = bool(datos.get("ya"))
        self._oferta_entrante = {
            "numero": datos.get("oferta"), "descripcion": str(datos.get("descripcion", "")),
            "total": int(datos.get("total") or 0),
            "estado": "pedida" if al_toque else "esperando",
        }
        if not al_toque:
            oferta = self._oferta_entrante
            self._registrar(f"En la otra PC copiaste {oferta['descripcion']} "
                            f"({T.peso(oferta['total'])}). Se pasa cuando traigas el mouse a "
                            "esta PC.")
            if self._mouse_aca:
                self._pedir_oferta()

    def _pedir_oferta(self):
        oferta = self._oferta_entrante
        if oferta and oferta["estado"] == "esperando" and self._enlace.listo:
            oferta["estado"] = "pedida"
            self._enlace.enviar(Tipo.ARCHIVOS_PEDIDO, T.armar_json(oferta=oferta["numero"]))

    def _descartar_oferta_entrante(self):
        self._oferta_entrante = None
        self._cancelar(self._llegada_portapapeles)
        self._llegada_portapapeles = None

    def _llegada_de_portapapeles(self, progreso):
        """Avance de archivos copiados en la otra PC que están llegando a esta."""
        oferta = self._oferta_entrante
        es_la_actual = oferta is not None and oferta["numero"] == progreso.extra.get("oferta")
        if progreso.estado == "en curso":
            if es_la_actual:
                self._llegada_portapapeles = progreso.clave
            return
        if self._llegada_portapapeles == progreso.clave:
            self._llegada_portapapeles = None
        if not es_la_actual:
            return  # Mientras llegaba copiaste otra cosa: no se toca el portapapeles.
        if progreso.estado != "terminado":
            oferta["estado"] = "fallida"
            return
        if not progreso.rutas_finales:
            return
        try:
            self._poner_archivos(progreso.rutas_finales)
        except OSError as error:
            self._registrar(f"Llegó {progreso.descripcion}, pero no se pudo poner en el "
                            f"portapapeles: {error}.")
            return
        oferta["estado"] = "lista"
        self._registrar(f"Llegó de la otra PC: {progreso.descripcion}. Ya podés pegarlo "
                        "(Ctrl+V).")

    # =====================================================================================
    # Mensajes y avances
    # =====================================================================================
    def _al_llegar(self, tipo, cuerpo):
        """Mensajes chicos, en el hilo de la ventana."""
        if tipo == Tipo.PORTAPAPELES:
            self._descartar_oferta_entrante()  # La otra PC copió otra cosa (texto, imagen).
            return
        if tipo not in (Tipo.ARCHIVOS_OFERTA, Tipo.ARCHIVOS_PEDIDO):
            return
        datos = T.leer_json(cuerpo)
        if datos is None:
            return
        if tipo == Tipo.ARCHIVOS_OFERTA:
            if self.config.compartir_archivos:
                self._llego_oferta(datos)
        else:
            oferta = self._oferta_saliente
            if oferta is not None and datos.get("oferta") == oferta["numero"]:
                self._mandar_oferta()

    def _al_progresar(self, progreso):
        if progreso.motivo == T.PORTAPAPELES:
            if progreso.sale:
                if progreso.estado != "en curso" and self._envio_portapapeles == progreso.clave:
                    self._envio_portapapeles = None
            else:
                self._llegada_de_portapapeles(progreso)
        if progreso.estado == "terminado" and progreso.motivo == T.ENVIADOS:
            if progreso.sale:
                self._registrar(f"Se mandó {progreso.descripcion} a la otra PC.")
            else:
                self._registrar(f"Llegó {progreso.descripcion} de la otra PC. Está en "
                                f"{progreso.destino}.")
                self.aviso.emit("Llegaron archivos",
                                f"{progreso.descripcion}, en {progreso.destino}")
        elif progreso.estado in ("error", "cancelado") and progreso.motivo != T.CARPETA:
            sentido = "a la otra PC" if progreso.sale else "de la otra PC"
            self._registrar(f"No se pasó {progreso.descripcion} {sentido}: "
                            f"{progreso.detalle or progreso.estado}.")
        self.progreso_cambiado.emit(progreso)

    def _destino(self, motivo, info):
        """Dónde guardar un envío que llega (se llama desde el hilo de red).
        Lanza ValueError para rechazarlo (la otra PC ve el motivo)."""
        config = self.config
        if motivo == T.CARPETA:
            sincro = self._carpeta
            if sincro is None:
                raise ValueError("La carpeta compartida no está activada en esta PC")
            return sincro.carpeta
        if not config.compartir_archivos:
            raise ValueError("Pasar archivos está apagado en esta PC")
        if motivo == T.PORTAPAPELES:
            total = int(info.get("total") or 0)
            if total > max(1, config.archivos_max_mb) * 1024 * 1024:
                raise ValueError(f"Pesa {T.peso(total)}, más que el tope de esta PC "
                                 f"({config.archivos_max_mb} MB)")
            tanda = f"{time.strftime('%Y%m%d-%H%M%S')}-{info.get('envio', 0)}"
            return CARPETA_TEMPORAL / tanda
        return carpeta_recibidos(config)

    def _al_archivo(self, progreso, info, final):
        sincro = self._carpeta
        if progreso.motivo == T.CARPETA and sincro is not None:
            sincro.archivo_recibido(info["ruta"], info["tam"], info["mtime"])

    def _antes_de_reemplazar(self, progreso, info, final):
        sincro = self._carpeta
        if progreso.motivo == T.CARPETA and sincro is not None:
            sincro.antes_de_reemplazar(info["ruta"], final)

    # ---- Canal ----------------------------------------------------------------------------
    def _al_abrirse_canal(self):
        if self._carpeta is not None:
            self._carpeta.canal_abierto()

    def _al_cerrarse_canal(self):
        self.transferencias.cortar_todo()
        self._oferta_saliente = None
        self._envio_portapapeles = None
        self._oferta_entrante = None
        self._llegada_portapapeles = None
        if self._carpeta is not None:
            self._carpeta.canal_cerrado()

    # ---- Carpeta sincronizada ---------------------------------------------------------------
    def _armar_carpeta(self):
        """Arranca, frena o cambia la carpeta sincronizada según la configuración."""
        config = self.config
        quiere = config.sincronizar_carpeta and config.carpeta_compartida and config.emparejada
        clave = (config.carpeta_compartida, config.id_pc, config.emparejado_id) if quiere else None
        if clave == self._clave_carpeta:
            return
        if self._carpeta is not None:
            self._carpeta.detener()
            self._carpeta = None
        self._clave_carpeta = clave
        if clave is None:
            return
        sincro = SincroCarpeta(
            config.carpeta_compartida, self._ruta_estado, config.id_pc, config.emparejado_id,
            socket.gethostname(), self._enlace.enviar,
            lambda entradas: self.transferencias.mandar(entradas, T.CARPETA),
            a_la_papelera, registrar=self._registro.emit)
        sincro.iniciar()
        self._carpeta = sincro
        if self._enlace.listo:
            sincro.canal_abierto()

    def _indice_de_la_otra(self, cuerpo):
        sincro = self._carpeta
        if sincro is not None:
            sincro.recibir_indice(cuerpo)

    def _pedido_de_la_otra(self, cuerpo):
        sincro = self._carpeta
        if sincro is not None:
            sincro.recibir_pedido(cuerpo)

    # ---- Internos ---------------------------------------------------------------------------
    def _listar_en_hilo(self, rutas, al_terminar):
        """Arma la lista de archivos en otro hilo (una carpeta enorme tarda) y después
        llama a `al_terminar(entradas)` en el hilo de la ventana."""
        rutas = list(rutas)

        def listar():
            self._listado.emit(al_terminar, T.listar(rutas))

        threading.Thread(target=listar, name="listar-archivos", daemon=True).start()

    def _cancelar(self, clave):
        if clave:
            self.transferencias.cancelar(clave)

    def _registrar(self, texto):
        self.nuevo_registro.emit(f"[{time.strftime('%H:%M:%S')}] {texto}")


def _copia(progreso):
    """Una foto del avance para la ventana (el original lo sigue cambiando otro hilo)."""
    return replace(progreso, rutas_finales=list(progreso.rutas_finales),
                   extra=dict(progreso.extra))
