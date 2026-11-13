"""Formato de los mensajes que viajan por la red.

Todo mensaje ("marco") tiene esta forma:

    [largo: 2 bytes][tipo: 1 byte][cuerpo: lo que corresponda al tipo]

`largo` cuenta los bytes que vienen después de él (tipo + cuerpo). TCP entrega
un chorro continuo de bytes, así que el largo es lo que permite saber dónde
termina cada mensaje. Un movimiento de mouse ocupa solamente 7 bytes.

Como cada marco dice cuánto mide, un programa viejo puede saltear mensajes que
no conoce: eso permite agregar funciones sin romper lo que ya anda.
"""

import json
import struct

# Versión 3: emparejamiento (sin PIN) y todo cifrado. Las dos PCs tienen que
# correr la misma versión (si no, el saludo lo avisa).
VERSION = 3
MAGIA = b"MCOM"  # Primeros bytes del saludo: confirman que hablamos con este programa.

# Canales: cada conexión TCP declara para qué se usa al saludar.
#   CANAL_ENTRADA: mouse y teclado. La abre el motor y la usa el motor.
#   CANAL_DATOS: portapapeles, archivos y carpeta compartida. Va por su propia
#     conexión para que un archivo de varios MB no demore los movimientos del mouse.
#     La abre el motor (así verifica el emparejamiento igual que la otra) y se la
#     pasa a la interfaz, que es la que la usa. Ver red/canal_datos.py.
CANAL_ENTRADA = 0
CANAL_DATOS = 1


class Tipo:
    """Códigos de cada mensaje. Son enteros comunes porque se consultan miles de veces."""

    # Saludo y verificación del emparejamiento (ver seguridad.py).
    HOLA = 1
    DESAFIO = 2
    RESPUESTA = 3
    ACEPTADO = 4
    RECHAZADO = 5

    # Control de la sesión.
    PING = 10
    PONG = 11
    ENTRAR = 12  # Servidor -> cliente: el cursor entra en tu pantalla.
    VOLVER = 13  # Cliente -> servidor: el cursor cruzó el borde de regreso.
    SALIR = 14  # Servidor -> cliente: el control volvió, soltá todo.
    PAUSA = 15  # En los dos sentidos: "puse en pausa" (1) o "reanudé" (0).
    INFO = 16  # En los dos sentidos, al conectar: nombre de la PC y sus monitores (JSON).

    # Mouse y teclado.
    MOVER = 20
    BOTON = 21
    RUEDA = 22
    TECLA = 23

    # Canal de datos (ver red/canal_datos.py).
    PORTAPAPELES = 40
    # Archivos (ver datos/transferencias.py). Los que dicen JSON llevan un dict.
    ARCHIVOS_OFERTA = 41  # JSON: "copié estos archivos" (todavía no viajan).
    ARCHIVOS_PEDIDO = 42  # JSON: "mandame los de esa oferta".
    ARCHIVO_INICIO = 43  # JSON: empieza un archivo (nombre, tamaño, fecha).
    ARCHIVO_DATOS = 44  # [número de envío: 4 bytes][pedazo del archivo]
    ARCHIVO_FIN = 45  # JSON: terminó un archivo o un envío entero.
    ENVIO_CANCELADO = 46  # JSON: alguno de los dos lados canceló un envío.
    # Carpeta compartida (ver datos/carpeta.py).
    CARPETA_INDICE = 50  # JSON: la lista de archivos de la carpeta, con fecha y tamaño.
    CARPETA_PEDIDO = 51  # JSON: "mandame estos archivos de tu carpeta".
    CARPETA_BORRADOS = 52  # JSON: "borré estos archivos, borralos vos también".


# Motivos de rechazo en el saludo.
RECHAZO_CLAVE = 1  # No demostró conocer la clave del emparejamiento.
RECHAZO_VERSION = 2
RECHAZO_CANAL = 3
RECHAZO_DESCONOCIDO = 4  # Esa PC no es la que está emparejada con esta.

# Códigos de los botones del mouse.
BOTON_IZQUIERDO = 1
BOTON_DERECHO = 2
BOTON_MEDIO = 3
BOTON_X1 = 4
BOTON_X2 = 5

# Banderas de una tecla.
TECLA_SOLTADA = 1
TECLA_EXTENDIDA = 2

LARGO_MAXIMO = 65535
LARGO_SELLO = 16  # Lo que agrega el cifrado a cada mensaje (ver sistema/cripto.py).

# Cuerpos de cada mensaje. "<" = little endian, sin relleno.
S_MOVER = struct.Struct("<hh")  # dx, dy
S_BOTON = struct.Struct("<BB")  # código, 1 si se aprieta / 0 si se suelta
S_RUEDA = struct.Struct("<hB")  # delta, 1 si es horizontal
S_TECLA = struct.Struct("<BBB")  # tecla virtual, código de escaneo, banderas
S_RATIO = struct.Struct("<H")  # altura relativa en el borde (0..65535)
S_TIEMPO = struct.Struct("<Q")  # marca de tiempo en nanosegundos

_S_LARGO = struct.Struct("<H")

# Marcos completos ya armados: evitan concatenar bytes en los mensajes frecuentes.
_M_MOVER = struct.Struct("<HBhh")
_M_BOTON = struct.Struct("<HBBB")
_M_RUEDA = struct.Struct("<HBhB")
_M_TECLA = struct.Struct("<HBBBB")
_M_RATIO = struct.Struct("<HBH")
_M_TIEMPO = struct.Struct("<HBQ")
_M_VACIO = struct.Struct("<HB")


class ErrorProtocolo(Exception):
    """El otro lado mandó algo que no respeta el formato."""


def marco(tipo, cuerpo=b""):
    """Arma un marco genérico. Sirve para cualquier mensaje con cuerpo variable."""
    largo = 1 + len(cuerpo)
    if largo > LARGO_MAXIMO:
        raise ValueError("Mensaje demasiado grande para el canal de entrada")
    return _M_VACIO.pack(largo, tipo) + bytes(cuerpo)


def _limitar_i16(valor):
    return max(-32768, min(32767, valor))


def mover(dx, dy):
    return _M_MOVER.pack(5, Tipo.MOVER, _limitar_i16(dx), _limitar_i16(dy))


def boton(codigo, apretado):
    return _M_BOTON.pack(3, Tipo.BOTON, codigo, 1 if apretado else 0)


def rueda(delta, horizontal):
    return _M_RUEDA.pack(4, Tipo.RUEDA, _limitar_i16(delta), 1 if horizontal else 0)


def tecla(vk, escaneo, banderas):
    return _M_TECLA.pack(4, Tipo.TECLA, vk & 0xFF, escaneo & 0xFF, banderas)


def entrar(ratio):
    return _M_RATIO.pack(3, Tipo.ENTRAR, ratio)


def volver(ratio):
    return _M_RATIO.pack(3, Tipo.VOLVER, ratio)


def salir():
    return _M_VACIO.pack(1, Tipo.SALIR)


def ping(tiempo_ns):
    return _M_TIEMPO.pack(9, Tipo.PING, tiempo_ns)


def pong(tiempo_ns):
    return _M_TIEMPO.pack(9, Tipo.PONG, tiempo_ns)


def pausa(activa):
    return marco(Tipo.PAUSA, b"\x01" if activa else b"\x00")


def info(nombre, monitores):
    """Presentación de cada PC: se manda una vez, justo después del saludo."""
    return marco(Tipo.INFO, json.dumps({"nombre": nombre, "monitores": monitores}).encode("utf-8"))


def leer_info(cuerpo):
    """Devuelve (nombre, monitores) o None si el mensaje no se entiende."""
    try:
        datos = json.loads(bytes(cuerpo).decode("utf-8"))
        return str(datos.get("nombre", ""))[:64], list(datos.get("monitores", []))[:16]
    except (ValueError, AttributeError, TypeError):
        return None


class LectorMarcos:
    """Reconstruye marcos completos a partir de los pedazos que entrega TCP.

    Con `descifrar`, cada marco llega cifrado: se descifra antes de separar el tipo.
    """

    def __init__(self, descifrar=None):
        self._buffer = bytearray()
        self._descifrar = descifrar

    @property
    def vacio(self):
        """True si no quedó ningún pedazo de marco esperando el resto."""
        return not self._buffer

    def alimentar(self, datos):
        """Agrega bytes recibidos y devuelve la lista de (tipo, cuerpo) ya completos."""
        buffer = self._buffer
        buffer += datos
        marcos = []
        posicion = 0
        total = len(buffer)
        while total - posicion >= 3:
            largo = _S_LARGO.unpack_from(buffer, posicion)[0]
            if largo == 0:
                raise ErrorProtocolo("Marco de largo cero")
            fin = posicion + 2 + largo
            if fin > total:
                break  # El resto del marco todavía no llegó.
            if self._descifrar is None:
                marcos.append((buffer[posicion + 2], bytes(buffer[posicion + 3:fin])))
            else:
                try:
                    plano = self._descifrar(bytes(buffer[posicion + 2:fin]))
                except Exception as error:  # ErrorCripto: alterado o de otra sesión.
                    raise ErrorProtocolo(f"Mensaje cifrado inválido: {error}") from error
                if not plano:
                    raise ErrorProtocolo("Mensaje cifrado vacío")
                marcos.append((plano[0], plano[1:]))
            posicion = fin
        if posicion:
            del buffer[:posicion]
        return marcos
