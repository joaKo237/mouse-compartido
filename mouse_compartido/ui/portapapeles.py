"""El portapapeles compartido, del lado de la ventana (corre en el proceso de la interfaz).

Cómo funciona:
  * Cuando copiás algo en esta PC, Windows avisa (señal dataChanged de Qt). Se
    espera un instante (hay programas que cambian el portapapeles varias veces
    seguidas al copiar), se lee lo copiado y se manda a la otra PC.
  * Cuando llega algo de la otra PC, se pone en el portapapeles de esta, como si
    lo hubieras copiado acá: lo pegás con Ctrl+V cuando quieras.
  * Lo que pone este programa lleva una marca invisible (MARCA). Cuando Windows
    avisa "cambió el portapapeles", la marca indica que fue este programa y no se
    reenvía. Sin eso, las dos PCs se lo devolverían una a la otra para siempre.

Todo esto pasa en el proceso de la ventana, nunca en el del mouse: leer o
convertir una imagen grande puede tardar, y el mouse no se tiene que enterar.

Para leer se usa Qt. Para escribir, Windows directo (sistema/portapapeles.py):
con Qt, poner una captura de pantalla tardaba un segundo (ver ahí por qué).

Los archivos copiados en el Explorador no viajan acá: se avisan con la señal
archivos_copiados y los maneja ui/archivos.py (pueden pesar gigas).
"""

import struct
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage

from ..datos import portapapeles as PP
from ..red.protocolo import Tipo

MARCA = "application/x-mouse-compartido"
_NATIVO = 'application/x-qt-windows-mime;value="{}"'  # Así llama Qt a los formatos de Windows.
_RTF = _NATIVO.format("Rich Text Format")
_PNG_NATIVO = _NATIVO.format("PNG")

_ESPERA_MS = 150  # Tras un cambio, cuánto esperar antes de leer.
_ESPERA_ENTRE_AVISOS_S = 30.0  # Para no repetir el mismo aviso con cada copia.

MOTIVO_PRIVADO = (
    "No se pasó a la otra PC: el programa que lo copió pidió que no se comparta "
    "(lo hacen los administradores de contraseñas)."
)
MOTIVO_ARCHIVOS = "archivos"  # No es un aviso: lo copiado son archivos (ver ui/archivos.py).


def leer_mime(mime):
    """Saca de lo copiado los formatos que se comparten.

    Devuelve (contenido, motivo). Si contenido es None no hay que mandar nada; en
    ese caso `motivo`, si no está vacío, explica por qué.
    """
    formatos = list(mime.formats())
    if any(MARCA in formato for formato in formatos):
        return None, ""  # Lo puso este programa: llegó de la otra PC.
    if PP.pide_privacidad(formatos, lambda formato: bytes(mime.data(formato))):
        return None, MOTIVO_PRIVADO
    contenido = {}
    # Ojo: hasText() de Qt también da True con archivos copiados (inventa un texto con
    # sus rutas). Por eso se mira si de verdad hay texto plano.
    if "text/plain" in formatos and mime.text():
        contenido[PP.TEXTO] = mime.text().encode("utf-8")
    if "text/html" in formatos:
        html = bytes(mime.data("text/html"))
        if html:
            contenido[PP.HTML] = html
    if _RTF in formatos:
        rtf = bytes(mime.data(_RTF))
        if rtf:
            contenido[PP.RTF] = rtf
    if mime.hasImage():
        png = _como_png(mime, formatos)
        if png:
            contenido[PP.PNG] = png
    if not contenido and mime.hasUrls():
        return None, MOTIVO_ARCHIVOS  # Archivos copiados en el Explorador.
    return (contenido or None), ""


def _como_png(mime, formatos):
    if _PNG_NATIVO in formatos:
        # El programa ya la ofrece en PNG (navegadores, Recortes): se pasa tal cual.
        datos = bytes(mime.data(_PNG_NATIVO))
        if datos.startswith(b"\x89PNG"):
            return datos
    imagen = mime.imageData()
    if hasattr(imagen, "toImage"):  # A veces Qt la da como QPixmap.
        imagen = imagen.toImage()
    if not isinstance(imagen, QImage) or imagen.isNull():
        return b""
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    imagen.save(buffer, "PNG")
    return bytes(buffer.data())


def formatos_para_windows(contenido):
    """Lo contrario de leer_mime(): los formatos de Windows a poner, como (número, bytes)."""
    from ..sistema import portapapeles as PW  # Solo Windows: las pruebas usan armar_mime().

    formatos = []
    if PP.TEXTO in contenido:
        texto = contenido[PP.TEXTO].decode("utf-8", "replace")
        formatos.append((PW.CF_UNICODETEXT, texto.encode("utf-16-le") + b"\0\0"))
    if PP.HTML in contenido:
        formatos.append((PW.formato("HTML Format"), PP.html_para_windows(contenido[PP.HTML])))
    if PP.RTF in contenido:
        formatos.append((PW.formato("Rich Text Format"), contenido[PP.RTF]))
    if PP.PNG in contenido:
        # El PNG tal cual llegó (sin volver a comprimir) y la versión clásica de Windows.
        formatos.append((PW.formato("PNG"), contenido[PP.PNG]))
        dib = dib_de_png(contenido[PP.PNG])
        if dib:
            formatos.append((PW.CF_DIB, dib))
    formatos.append((PW.formato(MARCA), b"1"))
    return formatos


def dib_de_png(png):
    """Convierte un PNG al formato de imagen clásico de Windows (DIB de 32 bits).

    Un DIB es una cabecera de 40 bytes y después los píxeles, de la fila de abajo
    a la de arriba (así lo inventó Windows), cada uno como azul, verde, rojo y un
    byte libre. Windows arma solo los otros formatos de imagen a partir de este.
    """
    imagen = QImage.fromData(png, "PNG")
    if imagen.isNull():
        return b""
    imagen = imagen.convertToFormat(QImage.Format_RGB32)  # 4 bytes por píxel, sin relleno.
    if hasattr(imagen, "flipped"):
        imagen = imagen.flipped(Qt.Vertical)
    else:  # PySide6 anterior a 6.9.
        imagen = imagen.mirrored(False, True)
    pixeles = bytes(imagen.constBits())[: imagen.width() * imagen.height() * 4]
    cabecera = struct.pack("<IiiHHIIiiII", 40, imagen.width(), imagen.height(), 1, 32, 0,
                           len(pixeles), 2835, 2835, 0, 0)
    return cabecera + pixeles


def poner_en_windows(contenido):
    from ..sistema import portapapeles as PW

    PW.poner(formatos_para_windows(contenido))


def formatos_de_archivos(rutas):
    """Los formatos de Windows para "copié estos archivos" (como el Ctrl+C del Explorador).

    CF_HDROP es una cabecera de 20 bytes (DROPFILES) y después las rutas en UTF-16,
    cada una terminada en cero, y un cero más al final. "Preferred DropEffect" = 1
    le dice al Explorador que al pegar los copie (no que los mueva).
    """
    from ..sistema import portapapeles as PW

    cabecera = struct.pack("<IiiII", 20, 0, 0, 0, 1)  # pFiles, punto, fNC, fWide=1
    lista = "".join(str(ruta) + "\0" for ruta in rutas) + "\0"
    return [
        (PW.CF_HDROP, cabecera + lista.encode("utf-16-le")),
        (PW.formato("Preferred DropEffect"), struct.pack("<I", 1)),
        (PW.formato(MARCA), b"1"),
    ]


def poner_archivos_en_windows(rutas):
    from ..sistema import portapapeles as PW

    PW.poner(formatos_de_archivos(rutas))


def armar_mime(contenido):
    """Como formatos_para_windows(), pero con Qt. Lo usan las pruebas, sin Windows real."""
    mime = QMimeData()
    if PP.TEXTO in contenido:
        mime.setText(contenido[PP.TEXTO].decode("utf-8", "replace"))
    if PP.HTML in contenido:
        mime.setData("text/html", QByteArray(contenido[PP.HTML]))
    if PP.RTF in contenido:
        mime.setData(_RTF, QByteArray(contenido[PP.RTF]))
    if PP.PNG in contenido:
        imagen = QImage.fromData(contenido[PP.PNG], "PNG")
        if not imagen.isNull():
            mime.setImageData(imagen)
    mime.setData(MARCA, QByteArray(b"1"))
    return mime


class SincroPortapapeles(QObject):
    nuevo_registro = Signal(str)  # Una línea para la actividad.
    estado_cambiado = Signal()  # Se abrió o se cerró el canal, o cambió la configuración.
    archivos_copiados = Signal(list)  # Copiaste archivos en esta PC (rutas).
    copiado_local = Signal()  # Copiaste cualquier cosa en esta PC (no llegada de la otra).

    def __init__(self, portapapeles, config, enlace, poner=poner_en_windows, parent=None):
        """`portapapeles` es el QClipboard (para leer y enterarse de los cambios),
        `enlace` el canal con la otra PC (ui/enlace.py) y `poner(contenido)` escribe
        en el portapapeles de esta PC."""
        super().__init__(parent)
        self._portapapeles = portapapeles
        self.config = config
        self._enlace = enlace
        self._poner = poner
        self._ultimos_avisos = {}

        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.setInterval(_ESPERA_MS)
        self._espera.timeout.connect(self._leer_lo_copiado)

        portapapeles.dataChanged.connect(self._al_copiar)
        enlace.mensaje.connect(self._al_llegar)
        enlace.estado_cambiado.connect(self.estado_cambiado)

    @property
    def activo(self):
        """Prendido en la configuración de esta PC."""
        return bool(self.config.compartir_portapapeles)

    @property
    def listo(self):
        """Hay canal con la otra PC."""
        return self._enlace.listo

    def poner_config(self, config):
        self.config = config
        self.estado_cambiado.emit()

    # ---- De esta PC a la otra ---------------------------------------------------------
    def _al_copiar(self):
        self._espera.start()  # Si vuelve a cambiar enseguida, la espera arranca de nuevo.

    def _leer_lo_copiado(self):
        mime = self._portapapeles.mimeData()
        if mime is None:
            return
        contenido, motivo = leer_mime(mime)
        if contenido is None and not motivo:
            return  # Lo puso este programa (llegó de la otra PC).
        self.copiado_local.emit()
        if motivo == MOTIVO_ARCHIVOS:
            rutas = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
            if rutas:
                self.archivos_copiados.emit(rutas)
            return
        if not (self.activo and self.listo):
            return
        if contenido is None:
            self._avisar(motivo)
            return
        peso = PP.tamanio(contenido)
        if peso > self._tope():
            self._avisar(
                f"No se pasó a la otra PC: pesa {PP.texto_peso(peso)} y el tope es "
                f"{self.config.portapapeles_max_mb} MB (se cambia en Compartir)."
            )
            return
        if self._enlace.enviar(Tipo.PORTAPAPELES, PP.codificar(contenido)):
            self._registrar(f"Pasó a la otra PC: {PP.describir(contenido)}.")

    # ---- De la otra PC a esta ---------------------------------------------------------
    def _al_llegar(self, tipo, cuerpo):
        if tipo != Tipo.PORTAPAPELES:
            return
        if not self.activo:
            self._avisar(
                "Llegó algo copiado en la otra PC, pero acá el portapapeles compartido "
                "está apagado (se prende en Compartir)."
            )
            return
        try:
            contenido = PP.decodificar(cuerpo)
        except ValueError as error:
            self._registrar(str(error))
            return
        if not contenido:
            return
        if PP.tamanio(contenido) > self._tope():
            self._avisar(
                f"Llegó de la otra PC algo de {PP.texto_peso(PP.tamanio(contenido))}, más que "
                f"el tope de esta PC ({self.config.portapapeles_max_mb} MB): no se pegó."
            )
            return
        try:
            self._poner(contenido)
        except (OSError, MemoryError) as error:
            self._registrar(f"Llegó {PP.describir(contenido)} de la otra PC, pero no se pudo "
                            f"poner en el portapapeles: {error}.")
            return
        self._registrar(f"Llegó de la otra PC: {PP.describir(contenido)}. Ya podés pegarlo.")

    # ---- Internos -----------------------------------------------------------------------
    def _tope(self):
        return max(1, self.config.portapapeles_max_mb) * 1024 * 1024

    def _registrar(self, texto):
        self.nuevo_registro.emit(f"[{time.strftime('%H:%M:%S')}] {texto}")

    def _avisar(self, texto):
        """Como _registrar, pero el mismo aviso sale como mucho cada 30 segundos."""
        ahora = time.monotonic()
        if ahora - self._ultimos_avisos.get(texto, float("-inf")) >= _ESPERA_ENTRE_AVISOS_S:
            self._ultimos_avisos[texto] = ahora
            self._registrar(texto)
