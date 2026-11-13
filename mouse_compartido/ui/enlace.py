"""El canal de datos con la otra PC, del lado de la interfaz.

Lo comparten el portapapeles, los archivos y la carpeta sincronizada. Esta clase:
  * recibe del motor la conexión ya verificada (con sus claves de cifrado),
  * reparte cada mensaje que llega a quien corresponda,
  * y si el canal se corta pero el mouse sigue conectado, pide otro.

Dos formas de recibir:
  * `mensaje` (señal de Qt): llega en el hilo de la ventana. Para lo chico.
  * `atender_en_hilo(tipo, funcion)`: la función corre en el hilo de red, sin
    pasar por la ventana. Para los pedazos de archivos: escribir megas en el
    disco desde el hilo de la ventana la dejaría trabada.
"""

from PySide6.QtCore import QObject, QTimer, Signal

from ..red.canal_datos import CanalDatos

_REINTENTO_MS = 3000  # Si se corta el canal y el mouse sigue conectado, cuándo pedir otro.


class EnlaceDatos(QObject):
    mensaje = Signal(int, object)  # (tipo, cuerpo), en el hilo de la ventana.
    abierto = Signal()  # Hay canal nuevo (para mandar lo que haga falta al empezar).
    cerrado = Signal()  # Se cortó o se soltó el canal.
    estado_cambiado = Signal()
    _llego = Signal(int, int, object)  # (generación, tipo, cuerpo): del hilo de red a la ventana.
    _se_corto = Signal(int)

    def __init__(self, pedir_canal=None, parent=None):
        super().__init__(parent)
        self._pedir_canal = pedir_canal
        self._canal = None
        self._generacion = 0  # Cuál es el canal actual (para ignorar avisos de uno viejo).
        self._conectado = False
        self._en_hilo = {}
        self._reintento = QTimer(self)
        self._reintento.setSingleShot(True)
        self._reintento.setInterval(_REINTENTO_MS)
        self._reintento.timeout.connect(self._pedir_otro)
        self._llego.connect(self._al_llegar)
        self._se_corto.connect(self._al_cortarse)

    @property
    def listo(self):
        canal = self._canal
        return canal is not None and not canal.cerrado

    def atender_en_hilo(self, tipo, funcion):
        """`funcion(cuerpo)` se llama en el hilo de red cada vez que llegue ese tipo."""
        self._en_hilo[tipo] = funcion

    # ---- Mandar (se puede llamar desde cualquier hilo) -----------------------------------
    def enviar(self, tipo, cuerpo=b""):
        canal = self._canal
        return canal is not None and canal.enviar(tipo, cuerpo)

    def enviar_bloque(self, tipo, cuerpo, timeout=None):
        """Para pedazos de archivos: espera si hay mucho en cola. False si no hay canal."""
        canal = self._canal
        return canal is not None and canal.enviar_bloque(tipo, cuerpo, timeout)

    # ---- Conexión ------------------------------------------------------------------------
    def conexion_cambiada(self, conectado):
        """La app avisa si el mouse está conectado con la otra PC."""
        if conectado == self._conectado:
            return
        self._conectado = conectado
        if not conectado:
            self._reintento.stop()
            self.soltar()

    def usar_canal(self, paquete):
        """Empieza a usar el canal que abrió el motor: (socket, (clave envío, clave recepción))."""
        sock, claves = paquete if isinstance(paquete, tuple) else (paquete, None)
        self.soltar(avisar=False)
        self._generacion += 1
        generacion = self._generacion
        en_hilo = self._en_hilo

        def al_recibir(tipo, cuerpo):
            funcion = en_hilo.get(tipo)
            if funcion is not None:
                funcion(cuerpo)
            else:
                self._llego.emit(generacion, tipo, cuerpo)

        self._canal = CanalDatos(sock, al_recibir=al_recibir,
                                 al_cerrar=lambda: self._se_corto.emit(generacion),
                                 claves=claves)
        self._reintento.stop()
        self.estado_cambiado.emit()
        self.abierto.emit()

    def soltar(self, avisar=True):
        canal, self._canal = self._canal, None
        if canal is not None:
            canal.cerrar()
            self.cerrado.emit()
            if avisar:
                self.estado_cambiado.emit()

    # ---- Internos ------------------------------------------------------------------------
    def _al_llegar(self, generacion, tipo, cuerpo):
        if generacion == self._generacion:
            self.mensaje.emit(tipo, cuerpo)

    def _al_cortarse(self, generacion):
        if generacion != self._generacion or self._canal is None:
            return  # Aviso de un canal viejo.
        self._canal = None
        self.cerrado.emit()
        self.estado_cambiado.emit()
        if self._conectado:
            self._reintento.start()

    def _pedir_otro(self):
        if self._conectado and not self.listo and self._pedir_canal is not None:
            self._pedir_canal()
