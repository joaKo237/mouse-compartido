"""Ícono en la bandeja del sistema (al lado del reloj) con su menú de click derecho.

El color del ícono muestra el estado de un vistazo:
    gris = detenido · naranja = buscando a la otra PC · verde = conectado
    violeta = en pausa · rojo = hay un problema
Con una flechita blanca, el mouse está manejando la otra PC.
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import iconos
from .resumen import CONECTADO, ERROR, donde_esta_el_mouse, resumir


class Bandeja(QObject):
    iniciar_pedido = Signal()
    pausa_pedida = Signal()
    detener_pedido = Signal()
    abrir_pedido = Signal()
    cerrar_pedido = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.icono = QSystemTrayIcon(iconos.icono_estado("detenido"), self)
        self.menu = QMenu()  # Se guarda en un atributo: si no, Python lo borraría.
        self.accion_iniciar = self.menu.addAction("Iniciar", self.iniciar_pedido)
        self.accion_pausar = self.menu.addAction("Pausar", self.pausa_pedida)
        self.accion_detener = self.menu.addAction("Detener", self.detener_pedido)
        self.menu.addSeparator()
        self.accion_abrir = self.menu.addAction("Abrir configuración", self.abrir_pedido)
        self.menu.addSeparator()
        self.menu.addAction("Cerrar Mouse Compartido", self.cerrar_pedido)
        fuente = self.accion_abrir.font()
        fuente.setBold(True)  # La acción del doble click, en negrita como en Windows.
        self.accion_abrir.setFont(fuente)
        self.icono.setContextMenu(self.menu)
        self.icono.activated.connect(self._al_activar)
        self._clave_anterior = None
        self._otra_anterior = ""

    def mostrar(self):
        self.icono.show()

    def esconder(self):
        self.icono.hide()

    def _al_activar(self, motivo):
        # Click o doble click con el botón izquierdo: abre la ventana.
        if motivo in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.abrir_pedido.emit()

    def mostrar_estado(self, activo, datos, error):
        datos = datos or {}
        resumen = resumir(activo, datos, error)
        en_la_otra = datos.get("estado") == "conectado" and not datos.get("mouse_aca", True)
        self.icono.setIcon(iconos.icono_estado(resumen.clave, en_la_otra))
        texto = f"Mouse Compartido: {resumen.titulo}"
        if resumen.clave == CONECTADO:
            texto += f"\nEl mouse está: {donde_esta_el_mouse(datos).lower()}"
        self.icono.setToolTip(texto[:120])

        self.accion_iniciar.setEnabled(not activo)
        self.accion_pausar.setEnabled(activo)
        self.accion_pausar.setText("Reanudar" if datos.get("pausa_local") else "Pausar")
        self.accion_detener.setEnabled(activo)

        # Avisos (los globitos de Windows) solo en los cambios importantes.
        otra = ((datos.get("otra_pc") or {}).get("nombre")) or ""
        if resumen.clave != self._clave_anterior or (resumen.clave == CONECTADO and otra != self._otra_anterior):
            if resumen.clave == CONECTADO and otra:
                self.avisar("Conectado", resumen.detalle)
            elif resumen.clave == ERROR:
                self.avisar("Hay un problema", resumen.detalle, error=True)
            self._clave_anterior = resumen.clave
            self._otra_anterior = otra

    def avisar(self, titulo, texto, error=False):
        if self.icono.isVisible() and self.icono.supportsMessages():
            tipo = QSystemTrayIcon.Warning if error else QSystemTrayIcon.Information
            self.icono.showMessage(titulo, texto, tipo, 4000)
