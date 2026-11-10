"""Menú de consola y arranque de cada modo.

Para agregar una opción nueva alcanza con sumar una línea a la lista OPCIONES.
"""

import threading
from dataclasses import dataclass, replace
from typing import Callable

from . import config as modulo_config
from . import win32 as W
from .captura import HiloCaptura
from .cliente import Cliente
from .conexion import ips_locales
from .inyeccion import SalidaSimulada
from .pantallas import DERECHA, IZQUIERDA
from .registro import log
from .servidor import Servidor


def _hay_errores(config, rol):
    problemas = config.errores(rol)
    for problema in problemas:
        print(f"  ! {problema}")
    if problemas:
        print("  Corregilo en la opción de configuración del menú (o en config.json).")
    return bool(problemas)


def _avisar_si_no_es_admin():
    if not W.es_administrador():
        log("Aviso: sin permisos de Administrador no se controlan las ventanas elevadas "
            "(Administrador de tareas, instaladores, etc.). Usá iniciar.bat para evitarlo.")


def correr_servidor(config):
    if _hay_errores(config, "servidor"):
        return
    _avisar_si_no_es_admin()
    try:
        Servidor(config).correr()
    except KeyboardInterrupt:
        pass
    except OSError as error:
        log(f"No se pudo abrir el puerto {config.puerto}: {error}")


def correr_cliente(config, simular=False):
    if _hay_errores(config, "cliente"):
        return
    _avisar_si_no_es_admin()
    try:
        Cliente(config, salida=SalidaSimulada() if simular else None).correr()
    except KeyboardInterrupt:
        pass


def correr_prueba(config):
    """Prueba en una sola PC: captura real, cliente simulado que solo muestra los eventos."""
    config = replace(config, pin="prueba-local", ip_servidor="127.0.0.1")
    log("MODO PRUEBA: lo que hagas en la 'otra PC' se muestra acá y no se ejecuta.")
    log(f"Llevá el cursor al borde de la {config.lado_otra_pantalla}. Ctrl+Alt+Esc lo devuelve. "
        "Por seguridad, a los 30 segundos vuelve solo.")
    cliente = Cliente(config, salida=SalidaSimulada())
    servidor = Servidor(config, captura=HiloCaptura(config, limite_remoto_s=30.0))

    def arrancar_cliente():
        if servidor.escuchando.wait(10):
            cliente.correr()

    threading.Thread(target=arrancar_cliente, name="cliente-prueba", daemon=True).start()
    try:
        servidor.correr()
    except KeyboardInterrupt:
        pass
    except OSError as error:
        log(f"No se pudo abrir el puerto {config.puerto}: {error}")
    finally:
        cliente.detener()


def _preguntar(texto, actual):
    respuesta = input(f"  {texto} [{actual}]: ").strip()
    return respuesta if respuesta else actual


def _configurar(config):
    print("\nEnter deja el valor actual.")
    config.pin = _preguntar("PIN (igual en las dos PCs, mejor 8 caracteres o más)", config.pin)
    while True:
        try:
            config.puerto = int(_preguntar("Puerto (igual en las dos PCs)", config.puerto))
            break
        except ValueError:
            print("  Tiene que ser un número.")
    config.ip_servidor = _preguntar(
        "IP del servidor (solo hace falta en el cliente)", config.ip_servidor
    )
    while True:
        lado = _preguntar(
            "Lado de la otra pantalla (solo en el servidor: izquierda/derecha)",
            config.lado_otra_pantalla,
        ).lower()
        if lado in (IZQUIERDA, DERECHA):
            config.lado_otra_pantalla = lado
            break
        print('  Escribí "izquierda" o "derecha".')
    modulo_config.guardar(config)
    print("  Guardado en config.json")


def _ver_diagnostico(config):
    print("\nIPs de esta PC (normalmente la primera es la correcta):")
    for ip in ips_locales():
        print(f"  {ip}")
    print("\nMonitores (en píxeles reales):")
    for monitor in W.leer_pantallas().monitores:
        print(f"  {monitor.ancho}x{monitor.alto} desde ({monitor.izq}, {monitor.arriba})")
    print(f"\nAdministrador: {'sí' if W.es_administrador() else 'no'}")
    print(f"Configuración: {config}".replace(f"pin='{config.pin}'", "pin='***'"))


@dataclass
class Opcion:
    texto: str
    accion: Callable


# Sumá acá las opciones futuras (portapapeles, archivos, ...).
OPCIONES = [
    Opcion("Iniciar como SERVIDOR (esta PC tiene el mouse y el teclado)", correr_servidor),
    Opcion("Iniciar como CLIENTE (esta PC recibe el control)", correr_cliente),
    Opcion("Probar en esta sola PC (no ejecuta nada en otra)", correr_prueba),
    Opcion("Configurar (PIN, IP, puerto, lado)", _configurar),
    Opcion("Ver IP, monitores y estado", _ver_diagnostico),
]


def mostrar_menu(config):
    while True:
        print("\n=== Mouse Compartido ===")
        for numero, opcion in enumerate(OPCIONES, start=1):
            print(f"  {numero}. {opcion.texto}")
        print("  0. Salir")
        try:
            eleccion = input("Elegí una opción: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if eleccion == "0":
            return
        if eleccion.isdigit() and 1 <= int(eleccion) <= len(OPCIONES):
            try:
                OPCIONES[int(eleccion) - 1].accion(config)
            except (EOFError, KeyboardInterrupt):
                print()
        else:
            print("  Opción inválida.")
