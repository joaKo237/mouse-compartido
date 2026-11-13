"""Lectura y guardado de la configuración (archivo config.json).

Dónde está: con el programa instalado (.exe), en %APPDATA%\\Mouse Compartido; si
se corre desde el código, junto a main.py.

La interfaz edita este archivo; el motor lo lee al arrancar. También se puede
editar a mano con el Bloc de notas: los valores mal escritos se corrigen solos
al cargarlo o se informan como error.
"""

import ipaddress
import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from .pantallas import DERECHA, LADOS


def _ruta_por_defecto():
    if getattr(sys, "frozen", False):
        # Instalado: la carpeta del programa puede no dejar escribir (Archivos de programa).
        base = Path(os.environ.get("APPDATA") or Path.home()) / "Mouse Compartido"
        return base / "config.json"
    return Path(__file__).resolve().parents[2] / "config.json"


RUTA_POR_DEFECTO = _ruta_por_defecto()

SERVIDOR = "servidor"
CLIENTE = "cliente"
ROLES = (SERVIDOR, CLIENTE)

# Teclas que se pueden usar para cambiar de PC (nombre en el config -> tecla virtual).
TECLAS_CAMBIO = {"bloq_despl": 0x91, "pausa": 0x13}


@dataclass
class Config:
    # "servidor" = esta PC tiene el mouse y el teclado. "cliente" = esta PC recibe el control.
    rol: str = ""
    # Puerto TCP. Tiene que ser el mismo en las dos PCs. Se usan este y el siguiente.
    puerto: int = 24850
    # Identidad de esta PC (se genera sola la primera vez; no la cambies).
    id_pc: str = ""
    # La PC emparejada: quién es y la clave que comparten. La clave es secreta: no
    # copies este archivo a otra PC. Se llenan solos al emparejar.
    emparejado_id: str = ""
    emparejado_nombre: str = ""
    emparejado_clave: str = ""
    # Última IP en la que se encontró a la otra PC (para reconectar más rápido).
    ultima_ip_otra_pc: str = ""
    # Solo en el servidor: de qué lado está físicamente la otra pantalla
    # (izquierda, derecha, arriba o abajo).
    lado_otra_pantalla: str = DERECHA
    # Solo en el cliente y opcional: IP fija de la PC con el mouse, por si la red no
    # deja que se encuentren solas (algunos routers de bares u oficinas lo impiden).
    ip_servidor: str = ""
    # Píxeles de cada esquina que no pasan a la otra PC (para llegar a la X de una ventana).
    esquinas_muertas_px: int = 20
    # Tope de mensajes de movimiento por segundo (0 = sin tope).
    max_envios_mouse_hz: int = 500
    # Tiempo tras cruzar en el que no se puede volver a cruzar (evita rebotes).
    enfriamiento_ms: int = 200
    # En la consola: muestra cada 10 segundos la latencia de red medida.
    mostrar_latencia: bool = True
    # La interfaz arranca el motor sola al abrirse.
    conectar_al_abrir: bool = True
    # Se abre al iniciar sesión en Windows, minimizado en la bandeja.
    iniciar_con_windows: bool = False
    # Atajo para cambiar de PC sin llevar el mouse al borde (solo en la PC con el mouse).
    atajo_cambiar: bool = True
    tecla_cambiar: str = "bloq_despl"  # "bloq_despl" o "pausa"
    # La luz de Bloq Despl se prende mientras estás usando la otra PC.
    luz_otra_pc: bool = True
    # Volumen, play/pausa, etc. actúan sobre la PC que estás usando (si no, siempre en esta).
    multimedia_pc_activa: bool = True
    # Copiar en una PC y pegar en la otra (texto, texto con formato e imágenes).
    compartir_portapapeles: bool = True
    # Lo que pese más que esto (en MB) no se pasa a la otra PC.
    portapapeles_max_mb: int = 20
    # Copiar archivos en una PC y pegarlos en la otra (con Ctrl+C y Ctrl+V).
    compartir_archivos: bool = True
    # Tope para pasar archivos copiados (en MB). Lo que mandás a propósito no tiene tope.
    archivos_max_mb: int = 4096
    # Dónde se guardan los archivos que llegan (vacío = Descargas\Mouse Compartido).
    carpeta_recibidos: str = ""
    # Una carpeta que se mantiene igual en las dos PCs.
    sincronizar_carpeta: bool = False
    carpeta_compartida: str = ""
    # Lo que se sabe de la otra PC, para dibujarla en el editor de pantallas.
    nombre_otra_pc: str = ""
    monitores_otra_pc: list = field(default_factory=list)

    def errores(self, rol=None):
        """Devuelve la lista de problemas para correr con ese rol ("servidor" o "cliente")."""
        rol = rol or self.rol
        problemas = []
        if rol not in ROLES:
            problemas.append("Elegí si esta PC tiene el mouse (servidor) o recibe el control (cliente).")
        if not 1 <= self.puerto <= 65534:
            problemas.append("El puerto tiene que estar entre 1 y 65534.")
        if not self.emparejada:
            problemas.append("Falta emparejar esta PC con la otra (página Conexión).")
        if rol == SERVIDOR and self.lado_otra_pantalla not in LADOS:
            problemas.append('El lado tiene que ser "izquierda", "derecha", "arriba" o "abajo".')
        if rol == CLIENTE and self.ip_servidor:
            try:
                ipaddress.ip_address(self.ip_servidor)
            except ValueError:
                problemas.append("La IP fija de la otra PC está mal escrita (por ejemplo "
                                 "192.168.0.10). Si no la necesitás, dejala vacía.")
        if self.tecla_cambiar not in TECLAS_CAMBIO:
            problemas.append('La tecla para cambiar de PC tiene que ser "bloq_despl" o "pausa".')
        return problemas

    @property
    def emparejada(self):
        """¿Ya tiene una PC emparejada (con su clave)?"""
        return (len(self.id_pc) == 32 and len(self.emparejado_id) == 32
                and len(self.emparejado_clave) == 64)

    @property
    def vk_cambiar(self):
        return TECLAS_CAMBIO.get(self.tecla_cambiar, TECLAS_CAMBIO["bloq_despl"])


def con_identidad(config):
    """Devuelve la configuración con un número de identidad propio (lo crea si falta)."""
    try:
        valido = len(bytes.fromhex(config.id_pc)) == 16
    except ValueError:
        valido = False
    if valido:
        return config
    return replace(config, id_pc=os.urandom(16).hex())


def _a_bool(valor):
    if isinstance(valor, str):
        return valor.strip().lower() in ("1", "true", "si", "sí", "yes")
    return bool(valor)


def _convertir(valor, por_defecto):
    """Lleva un valor leído del JSON al tipo que corresponde (tolera "24850" entre comillas)."""
    if isinstance(por_defecto, bool):
        return _a_bool(valor)
    if isinstance(por_defecto, int):
        return int(valor)
    if isinstance(por_defecto, list):
        return list(valor) if isinstance(valor, list) else []
    return "" if valor is None else str(valor)


def cargar(ruta=RUTA_POR_DEFECTO):
    """Lee la configuración. Si el archivo no existe, usa los valores por defecto.

    Lanza ValueError si el archivo está roto (por ejemplo, una coma de más).
    Los campos viejos que ya no se usan (como el PIN de la versión 2) se ignoran.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        return Config()
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict):
        raise ValueError("config.json no tiene el formato esperado")
    base = Config()
    valores = {}
    for campo in fields(Config):
        if campo.name in datos:
            valores[campo.name] = _convertir(datos[campo.name], getattr(base, campo.name))
    config = Config(**valores)
    config.lado_otra_pantalla = config.lado_otra_pantalla.strip().lower()
    config.rol = config.rol.strip().lower()
    config.tecla_cambiar = config.tecla_cambiar.strip().lower()
    return config


def guardar(config, ruta=RUTA_POR_DEFECTO):
    """Escribe el archivo de forma segura: primero a uno temporal y después lo reemplaza.

    Así, si se corta la luz justo al guardar, no queda un config.json a medias.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, ruta)
