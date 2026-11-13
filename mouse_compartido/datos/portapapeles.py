"""El portapapeles tal como viaja de una PC a la otra.

Cuando copiás algo, el programa de origen lo ofrece en varios formatos a la vez
(por ejemplo, un navegador da el texto solo y también con negritas y links). Al
pegar, el programa de destino elige el que mejor entiende. Por eso se pasan
todos los que haya de estos:

    texto -> texto plano, en UTF-8. Lo entiende cualquier programa.
    html  -> texto con formato (negritas, links, tablas): navegadores, Word, Excel...
    rtf   -> texto con formato de WordPad y Word.
    png   -> una imagen (una captura de pantalla, algo de Paint o del navegador).

Un "contenido" es un diccionario {formato: bytes}. Viaja así:

    [cantidad: 1 byte] y por cada formato:
    [largo del nombre: 1 byte][nombre][largo de los datos: 4 bytes][datos]
"""

import struct

TEXTO = "texto"
HTML = "html"
RTF = "rtf"
PNG = "png"
FORMATOS = (TEXTO, HTML, RTF, PNG)

# Marcas que dejan los administradores de contraseñas (KeePass, Bitwarden,
# 1Password...) para pedir "esto no lo compartas ni lo guardes en el historial".
MARCA_NO_MONITOREAR = "ExcludeClipboardContentFromMonitorProcessing"
MARCA_NUBE = "CanUploadToCloudClipboard"  # Si vale 0: "no lo subas a otra PC".

_LARGO = struct.Struct("<I")
_FIRMA_PNG = b"\x89PNG\r\n\x1a\n"


def codificar(contenido):
    """Convierte un contenido en bytes para mandarlo por el canal de datos."""
    partes = [bytes([len(contenido)])]
    for nombre, datos in contenido.items():
        clave = nombre.encode("ascii")
        partes += [bytes([len(clave)]), clave, _LARGO.pack(len(datos)), bytes(datos)]
    return b"".join(partes)


def decodificar(datos):
    """Lo contrario de codificar(). Lanza ValueError si los bytes no tienen sentido.

    Los formatos desconocidos (de una versión más nueva) se ignoran.
    """
    vista = memoryview(datos)
    contenido = {}
    try:
        cantidad = vista[0]
        posicion = 1
        for _ in range(cantidad):
            largo_nombre = vista[posicion]
            posicion += 1
            nombre = bytes(vista[posicion:posicion + largo_nombre]).decode("ascii")
            posicion += largo_nombre
            (largo,) = _LARGO.unpack_from(vista, posicion)
            posicion += _LARGO.size
            if posicion + largo > len(vista):
                raise ValueError("faltan datos")
            contenido[nombre] = bytes(vista[posicion:posicion + largo])
            posicion += largo
    except (IndexError, struct.error, ValueError) as error:
        raise ValueError("Lo copiado en la otra PC llegó dañado") from error
    if posicion != len(vista):
        raise ValueError("Lo copiado en la otra PC llegó dañado")
    return {nombre: datos for nombre, datos in contenido.items() if nombre in FORMATOS}


_INICIO_FRAGMENTO = b"<!--StartFragment-->"
_FIN_FRAGMENTO = b"<!--EndFragment-->"
_CABECERA_HTML = ("Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\n"
                  "StartFragment:{:010d}\r\nEndFragment:{:010d}\r\n")


def html_para_windows(html):
    """Arma el formato "HTML Format" de Windows a partir del HTML (en UTF-8).

    Windows pide, antes del HTML, una cabecera que diga en qué byte empieza y
    termina el documento y la parte copiada ("fragmento"). Si el HTML no marca el
    fragmento, se toma todo lo que está dentro de <body>, o todo el texto.
    """
    documento = bytes(html)
    if _INICIO_FRAGMENTO not in documento or _FIN_FRAGMENTO not in documento:
        minusculas = documento.lower()
        apertura = minusculas.find(b"<body")
        cierre = minusculas.rfind(b"</body")
        fin_apertura = minusculas.find(b">", apertura) + 1 if apertura >= 0 else 0
        if apertura >= 0 and fin_apertura and cierre >= fin_apertura:
            documento = (documento[:fin_apertura] + _INICIO_FRAGMENTO
                         + documento[fin_apertura:cierre] + _FIN_FRAGMENTO + documento[cierre:])
        else:
            documento = (b"<html><body>" + _INICIO_FRAGMENTO + documento + _FIN_FRAGMENTO
                         + b"</body></html>")
    largo = len(_CABECERA_HTML.format(0, 0, 0, 0))
    inicio = documento.index(_INICIO_FRAGMENTO) + len(_INICIO_FRAGMENTO)
    fin = documento.index(_FIN_FRAGMENTO)
    cabecera = _CABECERA_HTML.format(largo, largo + len(documento), largo + inicio, largo + fin)
    return cabecera.encode("ascii") + documento


def tamanio(contenido):
    return sum(len(datos) for datos in contenido.values())


def pide_privacidad(formatos, leer):
    """True si el programa que copió pidió que no se comparta.

    `formatos` son los nombres de los formatos (como los da Qt) y `leer(formato)`
    devuelve los bytes de uno de ellos.
    """
    for formato in formatos:
        if MARCA_NO_MONITOREAR in formato:
            return True
        if MARCA_NUBE in formato and bytes(leer(formato))[:4] == b"\0\0\0\0":
            return True
    return False


def medidas_png(datos):
    """(ancho, alto) leídos de la cabecera de un PNG, o None si no es un PNG."""
    if len(datos) >= 24 and datos[:8] == _FIRMA_PNG and datos[12:16] == b"IHDR":
        return struct.unpack(">II", bytes(datos[16:24]))
    return None


def texto_peso(cantidad):
    """'35 KB', '2,1 MB'... para los mensajes."""
    if cantidad >= 1024 * 1024:
        return f"{cantidad / (1024 * 1024):.1f} MB".replace(".", ",")
    if cantidad >= 1024:
        return f"{cantidad // 1024} KB"
    return f"{cantidad} bytes"


def describir(contenido):
    """Una frase corta para la actividad: 'texto (35 caracteres)', 'una imagen de 1920×1080'..."""
    if TEXTO in contenido:
        cantidad = len(contenido[TEXTO].decode("utf-8", "replace"))
        formato = " con formato" if HTML in contenido or RTF in contenido else ""
        return f"texto{formato} ({cantidad} {'carácter' if cantidad == 1 else 'caracteres'})"
    if PNG in contenido:
        peso = texto_peso(len(contenido[PNG]))
        medidas = medidas_png(contenido[PNG])
        if medidas:
            return f"una imagen de {medidas[0]}×{medidas[1]} ({peso})"
        return f"una imagen ({peso})"
    if HTML in contenido or RTF in contenido:
        return "texto con formato"
    return "algo en un formato desconocido"
