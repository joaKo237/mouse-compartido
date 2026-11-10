"""Lectura y guardado de la configuración (archivo config.json junto a main.py)."""

import ipaddress
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .pantallas import DERECHA, IZQUIERDA

RUTA_POR_DEFECTO = Path(__file__).resolve().parent.parent / "config.json"


@dataclass
class Config:
    # Puerto TCP. Tiene que ser el mismo en las dos PCs.
    puerto: int = 24850
    # Clave compartida. Tiene que ser la misma en las dos PCs.
    pin: str = ""
    # Solo en el servidor: de qué lado está físicamente la otra pantalla.
    lado_otra_pantalla: str = DERECHA
    # Solo en el cliente: IP de la PC que tiene el mouse y el teclado.
    ip_servidor: str = ""
    # Píxeles de cada esquina que no pasan a la otra PC (para llegar a la X de una ventana).
    esquinas_muertas_px: int = 20
    # Tope de mensajes de movimiento por segundo (0 = sin tope).
    max_envios_mouse_hz: int = 500
    # Tiempo tras cruzar en el que no se puede volver a cruzar (evita rebotes).
    enfriamiento_ms: int = 200
    # Muestra cada 10 segundos la latencia de red medida.
    mostrar_latencia: bool = True

    def errores(self, rol):
        """Devuelve la lista de problemas para correr con ese rol ("servidor" o "cliente")."""
        problemas = []
        if not 1 <= self.puerto <= 65535:
            problemas.append("El puerto tiene que estar entre 1 y 65535.")
        if len(self.pin) < 4:
            problemas.append("Falta el PIN (mínimo 4 caracteres, mejor 8 o más).")
        if rol == "servidor" and self.lado_otra_pantalla not in (IZQUIERDA, DERECHA):
            problemas.append('El lado tiene que ser "izquierda" o "derecha".')
        if rol == "cliente":
            try:
                ipaddress.ip_address(self.ip_servidor)
            except ValueError:
                problemas.append("Falta la IP del servidor (por ejemplo 192.168.0.10).")
        return problemas


def cargar(ruta=RUTA_POR_DEFECTO):
    """Lee la configuración. Si el archivo no existe, usa los valores por defecto."""
    ruta = Path(ruta)
    if not ruta.exists():
        return Config()
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    conocidos = {campo.name for campo in fields(Config)}
    config = Config(**{clave: valor for clave, valor in datos.items() if clave in conocidos})
    # Tolera números escritos entre comillas al editar el archivo a mano.
    config.puerto = int(config.puerto)
    config.esquinas_muertas_px = int(config.esquinas_muertas_px)
    config.max_envios_mouse_hz = int(config.max_envios_mouse_hz)
    config.enfriamiento_ms = int(config.enfriamiento_ms)
    config.pin = str(config.pin)
    return config


def guardar(config, ruta=RUTA_POR_DEFECTO):
    Path(ruta).write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")
