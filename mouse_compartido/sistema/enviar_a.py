"""El acceso "Mouse Compartido (a la otra PC)" del menú clic derecho → Enviar a.

Windows arma ese menú con los accesos directos de la carpeta SendTo del usuario.
Al elegirlo, Windows ejecuta el acceso agregándole las rutas de lo que tenías
seleccionado: el programa (modo "enviar") se las pasa a la ventana abierta.

Los accesos directos (.lnk) se crean con PowerShell, que trae lo necesario.
"""

import os
import subprocess
from pathlib import Path

from .rutas import comando

_SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW


def ruta_acceso():
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "SendTo" / "Mouse Compartido (a la otra PC).lnk"


def _texto_ps(texto):
    """Un texto entre comillas simples para PowerShell (las comillas se duplican)."""
    return "'" + str(texto).replace("'", "''") + "'"


def crear():
    """Crea (o rehace) el acceso. Devuelve "" si salió bien o el motivo si no."""
    acceso = ruta_acceso()
    programa, argumentos = comando("enviar")
    linea = " ".join(f'"{a}"' if " " in a else a for a in argumentos)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_texto_ps(acceso)}); "
        f"$s.TargetPath = {_texto_ps(programa)}; "
        f"$s.Arguments = {_texto_ps(linea)}; "
        f"$s.WorkingDirectory = {_texto_ps(Path(programa).parent)}; "
        f"$s.Description = 'Manda lo seleccionado a la otra PC'; "
        "$s.Save()"
    )
    try:
        acceso.parent.mkdir(parents=True, exist_ok=True)
        resultado = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30, creationflags=_SIN_VENTANA)
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    if resultado.returncode != 0 or not acceso.exists():
        return (resultado.stderr or resultado.stdout or "error desconocido").strip()[:300]
    return ""


def quitar():
    try:
        ruta_acceso().unlink(missing_ok=True)
    except OSError:
        pass


def existe():
    return ruta_acceso().exists()
