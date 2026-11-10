"""Punto de entrada.

    python main.py            abre el menú
    python main.py servidor   arranca directo como servidor
    python main.py cliente    arranca directo como cliente
    python main.py prueba     prueba la captura en una sola PC
"""

import argparse
import sys

from mouse_compartido import win32 as W  # Primero: ajusta el DPI antes de usar ventanas.
from mouse_compartido import config as modulo_config
from mouse_compartido import menu, registro


def main():
    W.preparar_proceso()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    registro.iniciar()

    analizador = argparse.ArgumentParser(description="Comparte mouse y teclado entre dos PCs.")
    analizador.add_argument(
        "modo", nargs="?", default="menu", choices=["menu", "servidor", "cliente", "prueba"]
    )
    analizador.add_argument(
        "--simular", action="store_true", help="el cliente muestra los eventos en vez de ejecutarlos"
    )
    argumentos = analizador.parse_args()

    try:
        config = modulo_config.cargar()
    except (ValueError, TypeError) as error:
        print(f"config.json tiene un error: {error}")
        return 1

    try:
        if argumentos.modo == "servidor":
            menu.correr_servidor(config)
        elif argumentos.modo == "cliente":
            menu.correr_cliente(config, simular=argumentos.simular)
        elif argumentos.modo == "prueba":
            menu.correr_prueba(config)
        else:
            menu.mostrar_menu(config)
    finally:
        registro.vaciar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
