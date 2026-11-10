"""Punto de extensión para las próximas etapas (portapapeles, archivos, etc.).

Para sumar una función:
  1. Creá un módulo en esta carpeta con una clase que herede de `Funcion`.
  2. En `al_conectar`, usá `sesion.registrar(Tipo.PORTAPAPELES, self.recibir)` para
     escuchar mensajes y `sesion.enviar(Tipo.PORTAPAPELES, datos)` para mandarlos.
  3. Agregala a la lista que devuelve `crear_funciones`.

Los tipos de mensaje ya están reservados en protocolo.py. Para archivos o contenidos
grandes hay que abrir una segunda conexión con `CANAL_DATOS`: por la de entrada
cada marco mide como máximo 64 KB y mandar mucho volumen demoraría el mouse.
"""


class Funcion:
    """Base de una función extra. Servidor y cliente crean una instancia por sesión."""

    def al_conectar(self, sesion):
        """Se llama cuando la conexión quedó autenticada."""

    def al_desconectar(self):
        """Se llama cuando la conexión se cortó."""


def crear_funciones(config):
    """Devuelve las funciones activas. Por ahora ninguna: primero probamos lo principal."""
    return []
