"""Abrir el Firewall de Windows para que la otra PC pueda encontrar y conectarse a esta.

Sin esto, Windows bloquea las conexiones que llegan: la otra PC no aparece en la
lista ni se puede conectar. Se agregan dos reglas, solo para la red local:
    TCP 24850-24851  el mouse y el teclado (24850) y el emparejamiento (24851)
    UDP 24851        los avisos de "acá estoy" para encontrarse solas

Hace falta ser Administrador para tocar el firewall. Si el programa no lo es, no
se hace nada (y la ventana lo avisa).

Un detalle: si alguna vez apareció el cartel del firewall de Windows y se tocó
"Cancelar", Windows crea una regla que BLOQUEA al programa, y esa le gana a
cualquier permiso. Con el programa instalado (.exe) también se borran esas.
"""

import subprocess
import sys

from . import win32 as W

NOMBRE_TCP = "Mouse Compartido (TCP)"
NOMBRE_UDP = "Mouse Compartido (UDP)"
_SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW


def _correr(argumentos, timeout=30):
    try:
        resultado = subprocess.run(argumentos, capture_output=True, text=True, timeout=timeout,
                                   creationflags=_SIN_VENTANA, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    return resultado.returncode, (resultado.stdout or "") + (resultado.stderr or "")


def reglas(puerto):
    """[(nombre, protocolo, puertos)] para ese puerto (el del mouse)."""
    return [(NOMBRE_TCP, "TCP", f"{puerto}-{puerto + 1}"), (NOMBRE_UDP, "UDP", str(puerto + 1))]


def _regla_al_dia(nombre, puertos):
    codigo, salida = _correr(["netsh", "advfirewall", "firewall", "show", "rule",
                              f"name={nombre}"])
    # La salida viene en el idioma de Windows: solo se busca el número de puerto.
    return codigo == 0 and any(linea.split()[-1:] == [puertos]
                               for linea in salida.splitlines())


def asegurar(puerto):
    """Deja las reglas como corresponden. Devuelve (cambió_algo, mensaje de error o "")."""
    if not W.es_administrador():
        return False, "sin permisos"
    cambio = False
    for nombre, protocolo, puertos in reglas(puerto):
        if _regla_al_dia(nombre, puertos):
            continue
        _correr(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={nombre}"])
        codigo, salida = _correr([
            "netsh", "advfirewall", "firewall", "add", "rule", f"name={nombre}", "dir=in",
            "action=allow", f"protocol={protocolo}", f"localport={puertos}",
            "remoteip=localsubnet", "profile=any",
        ])
        if codigo != 0:
            return cambio, salida.strip()[:300] or "netsh falló"
        cambio = True
    if getattr(sys, "frozen", False):
        cambio = _quitar_bloqueos(sys.executable) or cambio
    return cambio, ""


def _quitar_bloqueos(programa):
    """Borra las reglas que bloquean a este .exe (las que deja el "Cancelar" del cartel)."""
    ruta = str(programa).replace("'", "''")
    script = (
        f"$r = Get-NetFirewallApplicationFilter -Program '{ruta}' -ErrorAction SilentlyContinue "
        "| Get-NetFirewallRule | Where-Object { $_.Action -eq 'Block' }; "
        "if ($r) { $r | Remove-NetFirewallRule; 'borradas' }"
    )
    codigo, salida = _correr(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             timeout=60)
    return codigo == 0 and "borradas" in salida


def quitar():
    """Borra las reglas (para desinstalar)."""
    for nombre, _, _ in reglas(0):
        _correr(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={nombre}"])
