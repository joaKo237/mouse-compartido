"""Punto de entrada.

    python main.py              abre la interfaz gráfica (lo normal)
    python main.py --bandeja    abre la interfaz minimizada en la bandeja
    python main.py menu         abre el menú de texto de la primera versión
    python main.py servidor     arranca directo como servidor, en la consola
    python main.py cliente      arranca directo como cliente, en la consola
    python main.py prueba       prueba la captura en una sola PC
    python main.py motor        (lo usa la interfaz: no hace falta escribirlo a mano)
"""

import argparse
import os
import sys

from mouse_compartido.comun import config as modulo_config
from mouse_compartido.comun import registro
from mouse_compartido.sistema import win32 as W

MODOS = ["app", "menu", "servidor", "cliente", "prueba", "motor"]


def _analizar_argumentos():
    analizador = argparse.ArgumentParser(description="Comparte mouse y teclado entre dos PCs.")
    analizador.add_argument("modo", nargs="?", default="app", choices=MODOS)
    analizador.add_argument(
        "--bandeja", action="store_true", help="abre la interfaz minimizada en la bandeja"
    )
    analizador.add_argument(
        "--simular", action="store_true", help="el cliente muestra los eventos en vez de ejecutarlos"
    )
    analizador.add_argument("--config", default=None, help="ruta de otro config.json (pruebas)")
    return analizador.parse_args()


def _avisar_en_ventana(texto):
    """Sin consola (pythonw) un print no se ve: se muestra un cartel de Windows."""
    W.user32.MessageBoxW(None, texto, "Mouse Compartido", 0x10)


def _correr_app(argumentos, ruta):
    try:
        from mouse_compartido.ui.app import correr_app  # Qt se importa solo en este modo.
    except ImportError as error:
        texto = (
            f"Falta instalar la interfaz gráfica ({error.name}).\n\n"
            "Abrí iniciar.bat: la instala sola. O en PowerShell, dentro de esta carpeta:\n"
            "python -m pip install -r requirements.txt\n\n"
            "Mientras tanto podés usar el menú de texto: python main.py menu"
        )
        if sys.stdout:
            print(texto)
        else:
            _avisar_en_ventana(texto)
        return 1
    return correr_app(ruta, en_bandeja=argumentos.bandeja)


def main():
    argumentos = _analizar_argumentos()
    ruta = argumentos.config or modulo_config.RUTA_POR_DEFECTO

    if argumentos.modo == "app":
        return _correr_app(argumentos, ruta)

    # De acá en adelante corre el motor (con o sin consola): ajustes de velocidad.
    W.preparar_proceso()
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    registro.iniciar()

    try:
        config = modulo_config.cargar(ruta)
    except (ValueError, TypeError) as error:
        print(f"config.json tiene un error: {error}")
        return 1

    from mouse_compartido.motor import menu

    if argumentos.modo == "motor":
        from mouse_compartido.motor.proceso import correr_motor

        codigo = correr_motor(config)
        registro.vaciar()
        sys.stdout.flush()
        # Salida inmediata: el hilo que lee órdenes puede seguir esperando una
        # línea, y Python a veces se traba al cerrar con un hilo así.
        os._exit(codigo)

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
