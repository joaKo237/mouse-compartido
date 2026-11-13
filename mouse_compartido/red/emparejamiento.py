"""Emparejar dos PCs una sola vez, como se empareja un teléfono por Bluetooth.

Qué ve el usuario: en una PC toca "Emparejar" al lado de la otra; en las dos
aparece el mismo número de 6 cifras; si coincide, toca "Coinciden" en las dos y
listo. Desde ahí se reconocen solas, para siempre (hasta que toques "Olvidar").

Qué pasa por dentro (es la "comparación numérica" del Bluetooth):
  1. Cada PC inventa un par de claves (ECDH P-256, ver sistema/cripto.py) y se
     mandan la parte pública. Con eso, las dos calculan el mismo secreto sin que
     viaje por la red.
  2. ¿Y si alguien de la red se metiera en el medio, haciéndose pasar por cada
     una ante la otra? Cada PC terminaría con un secreto distinto, y el número de
     6 cifras, que sale de las claves públicas de las dos, no coincidiría en las
     pantallas. Por eso hay que mirarlo.
  3. Para que el intruso no pueda probar millones de claves hasta acertar un
     número igual, la PC que responde se compromete con su número al azar (manda
     su "huella") antes de ver el de la otra, y lo muestra recién después.
  4. De ese secreto sale la clave de 32 bytes que se guarda en las dos PCs. Con
     ella se verifican y cifran todas las conexiones (ver seguridad.py).

Va por TCP, en el puerto siguiente al del mouse (24851), y lo atiende la interfaz
(el programa con ventana), que está abierta aunque el mouse no esté compartido.
"""

import hashlib
import hmac
import json
import os
import socket
import threading
import time
from dataclasses import dataclass

from ..sistema.cripto import ErrorCripto, ParDeClaves, hkdf
from . import protocolo as P
from .conexion import Conexion, ConexionCerrada

MAGIA = "MCOM-E"
_VERSION = 1
_ESPERA_RED_S = 10.0
_ESPERA_USUARIO_S = 120.0  # Tiempo para mirar los números y tocar "Coinciden".


class _Tipo:
    HOLA = 1
    COMPROMISO = 2
    NONCE_INICIA = 3
    NONCE_RESPONDE = 4
    CONFIRMA = 5
    CANCELA = 6


@dataclass(frozen=True)
class Emparejada:
    """Resultado: la otra PC y la clave que ahora comparten."""

    id_otra: str  # En hexadecimal, como en config.json.
    nombre_otra: str
    rol_otra: str
    ip_otra: str
    clave: bytes


class Intento:
    """Un emparejamiento en curso. La interfaz lee estos datos para mostrarlos."""

    def __init__(self, inicia, ip):
        self.inicia = inicia  # True si se tocó "Emparejar" en esta PC.
        self.ip = ip
        self.nombre_otra = ""
        self.rol_otra = ""
        self.id_otra = ""
        self.codigo = ""  # "123 456" cuando está listo para comparar.
        self._decision = None
        self._hay_decision = threading.Event()

    def decidir(self, acepta):
        """El usuario tocó "Coinciden" (True) o "No coinciden / Cancelar" (False)."""
        if self._decision is None:
            self._decision = bool(acepta)
        self._hay_decision.set()


class FalloEmparejamiento(Exception):
    pass


def _json(tipo, **datos):
    return P.marco(tipo, json.dumps(datos).encode("utf-8"))


def _leer_json(cuerpo):
    try:
        datos = json.loads(bytes(cuerpo).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise FalloEmparejamiento("La otra PC mandó algo que no se entiende") from error
    if not isinstance(datos, dict):
        raise FalloEmparejamiento("La otra PC mandó algo que no se entiende")
    return datos


def _hexa(datos, clave, largo):
    try:
        valor = bytes.fromhex(str(datos.get(clave, "")))
    except ValueError:
        valor = b""
    if len(valor) != largo:
        raise FalloEmparejamiento("La otra PC mandó un dato inválido")
    return valor


def codigo_de(publica_inicia, publica_responde, nonce_inicia, nonce_responde):
    """El número de 6 cifras que se muestra en las dos PCs, como "123 456"."""
    resumen = hashlib.sha256(
        b"mouse-compartido codigo" + publica_inicia + publica_responde
        + nonce_inicia + nonce_responde
    ).digest()
    numero = int.from_bytes(resumen[:4], "big") % 1_000_000
    texto = f"{numero:06d}"
    return f"{texto[:3]} {texto[3:]}"


class Emparejador:
    """Atiende pedidos de emparejamiento y los inicia, un intento a la vez.

    `datos_propios()` -> {"id", "nombre", "rol"} de esta PC.
    `eventos` tiene tres métodos, que se llaman desde otros hilos:
        pedido(intento)      otra PC pide emparejarse (todavía sin número).
        codigo(intento)      ya hay número: preguntar al usuario si coincide.
        terminado(intento, emparejada_o_None, motivo)
    """

    def __init__(self, puerto, datos_propios, eventos):
        self.puerto = puerto
        self._datos_propios = datos_propios
        self._eventos = eventos
        self._oyente = None
        self._parar = threading.Event()
        self._ocupado = threading.Lock()
        self.intento = None
        self.error = ""

    def iniciar(self):
        oyente = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            oyente.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            oyente.bind(("0.0.0.0", self.puerto))
            oyente.listen(2)
            oyente.settimeout(0.5)
        except OSError as error:
            oyente.close()
            self.error = f"No se puede usar el puerto {self.puerto} para emparejar: {error}"
            return False
        self._oyente = oyente
        threading.Thread(target=self._escuchar, name="emparejar-oyente", daemon=True).start()
        return True

    def detener(self):
        self._parar.set()
        intento = self.intento
        if intento is not None:
            intento.decidir(False)
        oyente, self._oyente = self._oyente, None
        if oyente is not None:
            try:
                oyente.close()  # Libera el puerto ya (accept() se despierta con un error).
            except OSError:
                pass

    def emparejar_con(self, ip, puerto=None):
        """Empieza a emparejar con la PC de esa IP. Devuelve False si ya hay otro en curso."""
        if not self._ocupado.acquire(blocking=False):
            return False
        intento = Intento(True, ip)
        self.intento = intento
        threading.Thread(target=self._iniciar_intento, args=(intento, puerto or self.puerto),
                         name="emparejar", daemon=True).start()
        return True

    # ---- Hilos -------------------------------------------------------------------------
    def _escuchar(self):
        oyente = self._oyente
        while not self._parar.is_set():
            try:
                sock, direccion = oyente.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self._ocupado.acquire(blocking=False):
                # Ya hay un emparejamiento en curso: se avisa y se corta.
                conexion = Conexion(sock)
                conexion.enviar(_json(_Tipo.CANCELA, motivo="La otra PC ya está emparejando"))
                conexion.cerrar()
                continue
            intento = Intento(False, direccion[0])
            self.intento = intento
            threading.Thread(target=self._responder_intento, args=(intento, sock),
                             name="emparejar", daemon=True).start()
        try:
            oyente.close()
        except OSError:
            pass

    def _iniciar_intento(self, intento, puerto):
        conexion = None
        try:
            try:
                sock = socket.create_connection((intento.ip, puerto), timeout=4)
            except OSError as error:
                raise FalloEmparejamiento(
                    f"No se pudo conectar con {intento.ip} ({error}). ¿Está abierto el "
                    "programa allá?") from error
            conexion = Conexion(sock)
            propios = self._datos_propios()
            par = ParDeClaves()
            conexion.enviar(_json(_Tipo.HOLA, m=MAGIA, v=_VERSION, id=propios["id"],
                                  nombre=propios["nombre"], rol=propios["rol"],
                                  pub=par.publica.hex()))
            respuesta = self._esperar(conexion, _Tipo.COMPROMISO)
            self._anotar_otra(intento, respuesta)
            publica_otra = _hexa(respuesta, "pub", 64)
            compromiso = _hexa(respuesta, "compromiso", 32)
            nonce = os.urandom(16)
            conexion.enviar(_json(_Tipo.NONCE_INICIA, nonce=nonce.hex()))
            nonce_otra = _hexa(self._esperar(conexion, _Tipo.NONCE_RESPONDE), "nonce", 16)
            esperado = hmac.new(nonce_otra, publica_otra + par.publica, hashlib.sha256).digest()
            if not hmac.compare_digest(compromiso, esperado):
                raise FalloEmparejamiento(
                    "La otra PC hizo trampa en el emparejamiento: no se emparejó.")
            self._comparar(intento, conexion, par, propios["id"], intento.id_otra,
                           par.publica, publica_otra, nonce, nonce_otra, publica_otra)
        except FalloEmparejamiento as error:
            self._terminar(intento, None, str(error), conexion)
        except (ConexionCerrada, TimeoutError, OSError, ErrorCripto) as error:
            self._terminar(intento, None, _motivo_red(error), conexion)

    def _responder_intento(self, intento, sock):
        conexion = Conexion(sock)
        try:
            hola = self._esperar(conexion, _Tipo.HOLA)
            if hola.get("m") != MAGIA:
                raise FalloEmparejamiento("Se conectó algo que no es este programa")
            if hola.get("v") != _VERSION:
                raise FalloEmparejamiento(
                    "La otra PC tiene otra versión del programa: instalá la misma en las dos")
            self._anotar_otra(intento, hola)
            publica_otra = _hexa(hola, "pub", 64)
            self._avisar("pedido", intento)
            propios = self._datos_propios()
            par = ParDeClaves()
            nonce = os.urandom(16)
            compromiso = hmac.new(nonce, par.publica + publica_otra, hashlib.sha256).digest()
            conexion.enviar(_json(_Tipo.COMPROMISO, id=propios["id"], nombre=propios["nombre"],
                                  rol=propios["rol"], pub=par.publica.hex(),
                                  compromiso=compromiso.hex()))
            nonce_otra = _hexa(self._esperar(conexion, _Tipo.NONCE_INICIA), "nonce", 16)
            conexion.enviar(_json(_Tipo.NONCE_RESPONDE, nonce=nonce.hex()))
            self._comparar(intento, conexion, par, intento.id_otra, propios["id"],
                           publica_otra, par.publica, nonce_otra, nonce, publica_otra)
        except FalloEmparejamiento as error:
            self._terminar(intento, None, str(error), conexion)
        except (ConexionCerrada, TimeoutError, OSError, ErrorCripto) as error:
            self._terminar(intento, None, _motivo_red(error), conexion)

    # ---- Pasos compartidos ----------------------------------------------------------------
    def _comparar(self, intento, conexion, par, id_inicia, id_responde, pub_inicia,
                  pub_responde, nonce_inicia, nonce_responde, publica_otra):
        """Muestra el número, espera la decisión de las dos personas y guarda la clave."""
        secreto = par.acordar(publica_otra)
        material = hkdf(secreto, nonce_inicia + nonce_responde,
                        b"mouse-compartido emparejamiento" + bytes.fromhex(id_inicia)
                        + bytes.fromhex(id_responde), 64)
        clave, clave_mac = material[:32], material[32:]
        mi_letra, su_letra = (b"I", b"R") if intento.inicia else (b"R", b"I")
        intento.codigo = codigo_de(pub_inicia, pub_responde, nonce_inicia, nonce_responde)
        self._avisar("codigo", intento)

        limite = time.monotonic() + _ESPERA_USUARIO_S
        mi_ok = su_ok = None
        while mi_ok is None or su_ok is None:
            if self._parar.is_set():
                raise FalloEmparejamiento("Se cerró el programa")
            if time.monotonic() > limite:
                raise FalloEmparejamiento("Se acabó el tiempo para confirmar el número")
            if mi_ok is None and intento._hay_decision.wait(0.05):
                mi_ok = intento._decision
                mac = hmac.new(clave_mac, b"confirma" + mi_letra + bytes([mi_ok]),
                               hashlib.sha256).hexdigest()
                conexion.enviar(_json(_Tipo.CONFIRMA, ok=mi_ok, mac=mac))
                if not mi_ok:
                    raise FalloEmparejamiento("Cancelaste el emparejamiento")
            if su_ok is not None:
                continue  # Ya confirmó la otra: solo falta esta (la otra puede haber cerrado).
            for tipo, cuerpo in conexion.recibir(0.05):
                datos = _leer_json(cuerpo)
                if tipo == _Tipo.CANCELA:
                    raise FalloEmparejamiento(datos.get("motivo") or "Se canceló en la otra PC")
                if tipo != _Tipo.CONFIRMA:
                    continue
                ok = bool(datos.get("ok"))
                esperado = hmac.new(clave_mac, b"confirma" + su_letra + bytes([ok]),
                                    hashlib.sha256).hexdigest()
                if not hmac.compare_digest(str(datos.get("mac", "")), esperado):
                    raise FalloEmparejamiento(
                        "Los números no coincidían de verdad: no se emparejó (por seguridad).")
                if not ok:
                    raise FalloEmparejamiento("En la otra PC tocaron que los números no coinciden")
                su_ok = True
        resultado = Emparejada(intento.id_otra, intento.nombre_otra, intento.rol_otra,
                               intento.ip, clave)
        self._terminar(intento, resultado, "", conexion)

    def _esperar(self, conexion, tipo_esperado):
        tipo, cuerpo = conexion.esperar_marco(_ESPERA_RED_S)
        datos = _leer_json(cuerpo)
        if tipo == _Tipo.CANCELA:
            raise FalloEmparejamiento(datos.get("motivo") or "Se canceló en la otra PC")
        if tipo != tipo_esperado:
            raise FalloEmparejamiento("La otra PC respondió algo inesperado")
        return datos

    @staticmethod
    def _anotar_otra(intento, datos):
        id_otra = str(datos.get("id", ""))
        try:
            if len(bytes.fromhex(id_otra)) != 16:
                raise ValueError
        except ValueError as error:
            raise FalloEmparejamiento("La otra PC mandó una identidad inválida") from error
        intento.id_otra = id_otra
        intento.nombre_otra = str(datos.get("nombre", ""))[:64] or intento.ip
        intento.rol_otra = str(datos.get("rol", ""))[:16]

    def _terminar(self, intento, resultado, motivo, conexion):
        if conexion is not None:
            if resultado is None and not conexion.cerrada:
                conexion.enviar(_json(_Tipo.CANCELA,
                                      motivo="Se canceló el emparejamiento en la otra PC"))
            time.sleep(0.05)  # Que el último mensaje alcance a salir.
            conexion.cerrar()
        if self.intento is intento:
            self.intento = None
        self._ocupado.release()
        self._avisar("terminado", intento, resultado, motivo)

    def _avisar(self, nombre, *argumentos):
        try:
            getattr(self._eventos, nombre)(*argumentos)
        except Exception:  # Un error de la interfaz no tiene que trabar el emparejamiento.
            pass


def _motivo_red(error):
    if isinstance(error, TimeoutError):
        return "La otra PC dejó de responder"
    if isinstance(error, ErrorCripto):
        return f"La clave de la otra PC no sirve ({error})"
    return f"Se cortó la conexión con la otra PC ({error})"
