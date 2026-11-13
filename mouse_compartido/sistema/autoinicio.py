"""Inicio automático con Windows, usando el Programador de tareas.

¿Por qué una tarea programada y no la carpeta "Inicio" o el registro? Porque el
programa necesita permisos de Administrador (para controlar ventanas elevadas)
y lo que arranca desde la carpeta Inicio NO puede pedirlos sin mostrar el
cartel de UAC en cada arranque. Una tarea con "privilegios más altos" arranca
elevada y sin preguntar.

La tarea se arma con un XML para poder corregir tres valores por defecto que
arruinarían el programa en una notebook:
  * "Iniciar solo con corriente alterna": con batería no arrancaría.
  * "Detener si dura más de 3 días": lo cerraría solo a los 3 días.
  * Prioridad 7 (baja): le quitaría velocidad. Se usa 4 (normal).
"""

import os
import re
import subprocess
import tempfile
from xml.sax.saxutils import escape, unescape

from .rutas import RAIZ, comando

NOMBRE_TAREA = "Mouse Compartido"
_SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW: que no parpadee una consola.


def _usuario_actual():
    dominio = os.environ.get("USERDOMAIN", "")
    usuario = os.environ.get("USERNAME", "")
    return f"{dominio}\\{usuario}" if dominio else usuario


def _citar(argumento):
    return f'"{argumento}"' if " " in argumento else argumento


def xml_tarea(programa, argumentos, carpeta, usuario, elevada=True):
    """Arma la definición de la tarea. Separada para poder probarla sin tocar Windows."""
    linea = " ".join(_citar(a) for a in argumentos)
    nivel = "HighestAvailable" if elevada else "LeastPrivilege"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Abre Mouse Compartido en la bandeja al iniciar sesión.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(usuario)}</UserId>
      <Delay>PT5S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(usuario)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>{nivel}</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>4</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(programa))}</Command>
      <Arguments>{escape(linea)}</Arguments>
      <WorkingDirectory>{escape(str(carpeta))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _schtasks(*argumentos):
    resultado = subprocess.run(
        ["schtasks", *argumentos], capture_output=True, creationflags=_SIN_VENTANA,
        text=True, encoding="oem", errors="replace",  # schtasks escribe en la página OEM.
    )
    mensaje = (resultado.stdout + resultado.stderr).strip()
    return resultado.returncode == 0, mensaje


def esta_activo(nombre=NOMBRE_TAREA):
    ok, _ = _schtasks("/Query", "/TN", nombre)
    return ok


def carpeta_de_la_tarea(nombre=NOMBRE_TAREA):
    """Carpeta desde la que arranca la tarea, o None si no existe o no se pudo leer."""
    ok, texto = _schtasks("/Query", "/TN", nombre, "/XML")
    if not ok:
        return None
    encontrado = re.search(r"<WorkingDirectory>(.*?)</WorkingDirectory>", texto, re.S)
    return unescape(encontrado.group(1).strip()) if encontrado else None


def apunta_a_otra_copia(nombre=NOMBRE_TAREA):
    """¿La tarea existe pero abre OTRA copia del programa?

    Pasa al instalar una versión nueva en otra carpeta (o al mover la carpeta): la tarea
    sigue apuntando a la vieja y al iniciar sesión abriría la versión vieja, o nada si se
    borró. Windows no distingue mayúsculas en las rutas, así que acá tampoco.
    """
    carpeta = carpeta_de_la_tarea(nombre)
    if carpeta is None:
        return False

    def normal(ruta):
        return os.path.normcase(os.path.normpath(str(ruta)))

    return normal(carpeta) != normal(RAIZ)


def activar(nombre=NOMBRE_TAREA, elevada=True):
    """Crea (o reemplaza) la tarea. Devuelve (ok, mensaje para mostrar)."""
    programa, argumentos = comando("--bandeja")  # Abre la interfaz minimizada.
    contenido = xml_tarea(programa, argumentos, RAIZ, _usuario_actual(), elevada)
    archivo = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16")
    try:
        with archivo:
            archivo.write(contenido)
        ok, mensaje = _schtasks("/Create", "/TN", nombre, "/XML", archivo.name, "/F")
    finally:
        os.unlink(archivo.name)
    if ok:
        return True, "Listo: se va a abrir solo, en la bandeja, cada vez que inicies sesión."
    if "acceso" in mensaje.lower() or "access" in mensaje.lower():
        return False, ("Windows no dejó crear el inicio automático. Abrí el programa con "
                       "iniciar.bat (pide permiso de Administrador) y probá de nuevo.")
    return False, f"No se pudo activar el inicio automático: {mensaje}"


def desactivar(nombre=NOMBRE_TAREA):
    if not esta_activo(nombre):
        return True, "El inicio automático ya estaba apagado."
    ok, mensaje = _schtasks("/Delete", "/TN", nombre, "/F")
    if ok:
        return True, "Listo: ya no se abre solo al iniciar sesión."
    return False, f"No se pudo desactivar el inicio automático: {mensaje}"
