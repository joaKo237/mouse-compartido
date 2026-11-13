"""Punto de extensión para las próximas etapas (portapapeles, archivos, etc.).

Para sumar una función:
  1. Creá un módulo en esta carpeta con una clase que herede de `Funcion`.
  2. En `al_conectar`, usá `sesion.registrar(Tipo.PORTAPAPELES, self.recibir)` para
     escuchar mensajes y `sesion.enviar(Tipo.PORTAPAPELES, datos)` para mandarlos.
  3. Agregala a la lista que devuelve `crear_funciones`.

Esto es para mensajes chicos que tenga que manejar el motor. Lo que pesa (el
portapapeles, y en la etapa 6 los archivos) va por el canal de datos, que usa la
interfaz: ver red/canal_datos.py y ui/portapapeles.py. Por la conexión del mouse
cada marco mide como máximo 64 KB y mandar mucho volumen demoraría el cursor.
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
