"""Traduce el estado técnico del motor a lo que se muestra: color, título y detalle.

No usa Qt, así que se puede probar sola. La ventana y la bandeja muestran
exactamente lo mismo porque las dos usan esta función.
"""

from dataclasses import dataclass

from ..motor.estado import DEMORA_ALTA_MS

DETENIDO = "detenido"
ESPERANDO = "esperando"
CONECTADO = "conectado"
PAUSADO = "pausado"
ERROR = "error"

NOMBRES_LADO = {
    "izquierda": "a la izquierda",
    "derecha": "a la derecha",
    "arriba": "arriba",
    "abajo": "abajo",
}


@dataclass(frozen=True)
class Resumen:
    clave: str  # Una de las constantes de arriba: decide el color del ícono.
    titulo: str
    detalle: str


def nombre_otra(datos):
    otra = (datos or {}).get("otra_pc") or {}
    return otra.get("nombre") or otra.get("ip") or "la otra PC"


def resumir(motor_activo, datos, error=""):
    """`motor_activo`: si el proceso del motor está corriendo. `datos`: su última foto."""
    datos = datos or {}
    if not motor_activo:
        if error:
            return Resumen(ERROR, "Hay un problema", error)
        return Resumen(DETENIDO, "Detenido", "Tocá Iniciar para compartir el mouse y el teclado.")

    estado = datos.get("estado", "iniciando")
    if estado == "error":
        return Resumen(ERROR, "Hay un problema", datos.get("detalle") or error)

    if estado == "conectado":
        otra = nombre_otra(datos)
        if datos.get("pausa_local"):
            return Resumen(PAUSADO, "En pausa",
                           f"Sigue conectado con {otra}, pero el mouse no cambia de PC. "
                           "Tocá Reanudar.")
        if datos.get("pausa_otra"):
            return Resumen(PAUSADO, "En pausa desde la otra PC",
                           f"{otra} pausó el cambio de PC. Se reanuda desde allá.")
        ip = ((datos.get("otra_pc") or {}).get("ip")) or ""
        con_ip = f"{otra} ({ip})" if ip and ip != otra else otra
        ruta = datos.get("ruta")  # "cable" o "Wi-Fi": lo agrega la app (ui/app.py).
        por = f", por {ruta}" if ruta in ("cable", "Wi-Fi") else ""
        return Resumen(CONECTADO, "Conectado", f"Conectado con {con_ip}{por}.")

    if estado == "esperando":
        detalle = ("Abrí el programa en la otra PC para que se conecte (se encuentran solas "
                   "en la red).")
        if datos.get("pausa_local"):
            detalle += " Además está en pausa."
        return Resumen(ESPERANDO, "Esperando a la otra PC", detalle)
    if estado == "conectando":
        return Resumen(ESPERANDO, "Buscando a la otra PC",
                       datos.get("detalle") or "Intentando conectar...")
    return Resumen(ESPERANDO, "Iniciando...", "")


def texto_latencia(datos):
    """'2.4 ms', o '2.4 ms · tirón de 180 ms' si hubo uno en los últimos 30 segundos."""
    datos = datos or {}
    latencia = datos.get("latencia_ms")
    if latencia is None:
        return "—"
    texto = f"{latencia:.1f} ms"
    pico = datos.get("latencia_pico_ms")
    if pico is not None and pico >= DEMORA_ALTA_MS:
        texto += f" · tirón de {pico:.0f} ms"
    return texto


def donde_esta_el_mouse(datos):
    """Texto corto para "El mouse está en ..."."""
    datos = datos or {}
    if datos.get("estado") != "conectado":
        return "En esta PC"
    if datos.get("mouse_aca"):
        return "En esta PC"
    return f"En {nombre_otra(datos)}"
