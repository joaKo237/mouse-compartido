"""Lectura y guardado de la configuración (archivo config.json junto a main.py).

La interfaz edita este archivo; el motor lo lee al arrancar. También se puede
editar a mano con el Bloc de notas: los valores mal escritos se corrigen solos
al cargarlo o se informan como error.
"""

import ipaddress
import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .pantallas import DERECHA, LADOS

RUTA_POR_DEFECTO = Path(__file__).resolve().parents[2] / "config.json"

SERVIDOR = "servidor"
CLIENTE = "cliente"
ROLES = (SERVIDOR, CLIENTE)


@dataclass
class Config:
    # "servidor" = esta PC tiene el mouse y el teclado. "cliente" = esta PC recibe el control.
    rol: str = ""
    # Puerto TCP. Tiene que ser el mismo en las dos PCs.
    puerto: int = 24850
    # Clave compartida. Tiene que ser la misma en las dos PCs.
    pin: str = ""
    # Solo en el servidor: de qué lado está físicamente la otra pantalla
    # (izquierda, derecha, arriba o abajo).
    lado_otra_pantalla: str = DERECHA
    # Solo en el cliente: IP de la PC que tiene el mouse y el teclado.
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
    # Carpeta que se mantendrá igual en las dos PCs (se activa en la etapa 7).
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
        if not 1 <= self.puerto <= 65535:
            problemas.append("El puerto tiene que estar entre 1 y 65535.")
        if len(self.pin) < 4:
            problemas.append("Falta el PIN (mínimo 4 caracteres, mejor 8 o más).")
        if rol == SERVIDOR and self.lado_otra_pantalla not in LADOS:
            problemas.append('El lado tiene que ser "izquierda", "derecha", "arriba" o "abajo".')
        if rol == CLIENTE:
            try:
                ipaddress.ip_address(self.ip_servidor)
            except ValueError:
                problemas.append("Falta la IP del servidor (por ejemplo 192.168.0.10).")
        return problemas


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
    return config


def guardar(config, ruta=RUTA_POR_DEFECTO):
    """Escribe el archivo de forma segura: primero a uno temporal y después lo reemplaza.

    Así, si se corta la luz justo al guardar, no queda un config.json a medias.
    """
    ruta = Path(ruta)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, ruta)
