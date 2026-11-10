"""Ventana principal: estado, pantallas, conexión, atajos, compartir y opciones generales.

Todo lo que se edita acá va a config.json al tocar "Guardar". Si el motor está
andando, se reinicia solo para aplicar los cambios (tarda un segundo).
"""

import os
import socket
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..comun.config import CLIENTE, SERVIDOR
from ..comun.pantallas import ABAJO, ARRIBA, DERECHA, IZQUIERDA, desde_lista
from ..red.conexion import ips_locales
from ..sistema import win32 as W
from ..sistema.rutas import RAIZ
from . import estilo, iconos
from .editor_pantallas import EditorPantallas
from .resumen import NOMBRES_LADO, donde_esta_el_mouse, resumir, texto_latencia
from .widgets import (
    FilaOpcion,
    Interruptor,
    Tarjeta,
    Tecla,
    etiqueta,
    glifo,
    pixmap_glifo,
    separador,
)

PAGINAS = [
    ("estado", "Estado"),
    ("pantallas", "Pantallas"),
    ("conexion", "Conexión"),
    ("atajos", "Atajos"),
    ("compartir", "Compartir"),
    ("general", "General"),
]


class OpcionRol(QFrame):
    """Tarjeta elegible para el rol de la PC (funciona como un botón de opción)."""

    elegida = Signal(str)

    def __init__(self, rol, clave_glifo, titulo, descripcion):
        super().__init__()
        self.rol = rol
        self.setObjectName("OpcionRol")
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("elegida", False)
        fila = QHBoxLayout(self)
        fila.setContentsMargins(16, 14, 16, 14)
        fila.setSpacing(14)
        icono = glifo(clave_glifo, 20, estilo.tema_actual()["acento"])
        icono.setFixedWidth(30)
        fila.addWidget(icono)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        nombre = etiqueta(titulo)
        nombre.setStyleSheet("font-weight: 600;")
        textos.addWidget(nombre)
        textos.addWidget(etiqueta(descripcion, "Suave", ajustar=True))
        fila.addLayout(textos, 1)

    def marcar(self, valor):
        self.setProperty("elegida", valor)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, evento):
        if evento.button() == Qt.LeftButton:
            self.elegida.emit(self.rol)
        super().mousePressEvent(evento)


class VentanaPrincipal(QMainWindow):
    iniciar_pedido = Signal()
    pausa_pedida = Signal()  # Alterna entre pausar y reanudar.
    detener_pedido = Signal()
    config_guardada = Signal(object)
    autoinicio_pedido = Signal(bool)
    escondida = Signal()

    def __init__(self, config):
        super().__init__()
        self.config = config  # La última guardada en disco.
        self._cargando = False
        self._rol = config.rol
        self._lado = config.lado_otra_pantalla
        self._datos = {}
        self._activo = False
        self._error = ""
        self._clave_estado = None
        self._otra_pantallas = desde_lista(config.monitores_otra_pc)

        self.setWindowTitle("Mouse Compartido")
        self.resize(1000, 700)
        self.setMinimumSize(860, 600)

        fondo = QWidget()
        fondo.setObjectName("Fondo")
        principal = QHBoxLayout(fondo)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(0)
        principal.addWidget(self._crear_barra_lateral())

        derecha = QVBoxLayout()
        derecha.setContentsMargins(0, 0, 0, 0)
        derecha.setSpacing(0)
        self.paginas = QStackedWidget()
        self.paginas.setObjectName("Contenido")
        for constructor in (
            self._pagina_estado, self._pagina_pantallas, self._pagina_conexion,
            self._pagina_atajos, self._pagina_compartir, self._pagina_general,
        ):
            self.paginas.addWidget(constructor())
        derecha.addWidget(self.paginas, 1)
        derecha.addWidget(self._crear_barra_guardar())
        principal.addLayout(derecha, 1)
        self.setCentralWidget(fondo)

        self.navegacion.currentRowChanged.connect(self.paginas.setCurrentIndex)
        self.navegacion.setCurrentRow(0)
        self.cargar_formulario(config)
        self.mostrar_estado(False, {}, "")

    # =================================================================================
    # Armado
    # =================================================================================
    def _crear_barra_lateral(self):
        barra = QFrame()
        barra.setObjectName("BarraLateral")
        barra.setFixedWidth(232)
        columna = QVBoxLayout(barra)
        columna.setContentsMargins(0, 22, 0, 16)
        columna.setSpacing(6)

        marca = QHBoxLayout()
        marca.setContentsMargins(20, 0, 16, 14)
        marca.setSpacing(12)
        self.logo = QLabel()
        self.logo.setPixmap(iconos.pixmap_estado("detenido", 36))
        marca.addWidget(self.logo)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(etiqueta("Mouse Compartido", "Marca"))
        textos.addWidget(etiqueta("Un mouse, dos PCs", "MarcaSub"))
        marca.addLayout(textos, 1)
        columna.addLayout(marca)

        self.navegacion = QListWidget()
        self.navegacion.setObjectName("Navegacion")
        self.navegacion.setIconSize(QSize(20, 20))
        self.navegacion.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for clave, nombre in PAGINAS:
            item = QListWidgetItem(nombre)
            item.setData(Qt.UserRole, clave)
            item.setSizeHint(QSize(0, 40))
            self.navegacion.addItem(item)
        self._pintar_iconos_navegacion()
        columna.addWidget(self.navegacion, 1)

        pie = QHBoxLayout()
        pie.setContentsMargins(22, 0, 16, 0)
        pie.setSpacing(8)
        self.punto_mini = QLabel()
        self.punto_mini.setFixedSize(10, 10)
        pie.addWidget(self.punto_mini)
        self.texto_mini = etiqueta("Detenido", "EstadoMini")
        pie.addWidget(self.texto_mini, 1)
        columna.addLayout(pie)
        return barra

    def _pintar_iconos_navegacion(self):
        color = estilo.tema_actual()["suave"]
        for fila in range(self.navegacion.count()):
            item = self.navegacion.item(fila)
            item.setIcon(QIcon(pixmap_glifo(item.data(Qt.UserRole), color, 40)))

    def _crear_pagina(self, titulo, subtitulo):
        """Página con título, subtítulo y lugar para tarjetas. Se puede desplazar."""
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        contenido = QWidget()
        columna = QVBoxLayout(contenido)
        columna.setContentsMargins(36, 30, 36, 30)
        columna.setSpacing(16)
        columna.addWidget(etiqueta(titulo, "TituloPagina"))
        sub = etiqueta(subtitulo, "Subtitulo", ajustar=True)
        columna.addWidget(sub)
        columna.addSpacing(4)
        desplazable.setWidget(contenido)
        return desplazable, columna

    def _crear_barra_guardar(self):
        self.barra_guardar = QFrame()
        self.barra_guardar.setObjectName("BarraGuardar")
        fila = QHBoxLayout(self.barra_guardar)
        fila.setContentsMargins(36, 12, 36, 12)
        fila.addWidget(etiqueta("Tenés cambios sin guardar.", "Suave"))
        fila.addStretch()
        descartar = QPushButton("Descartar")
        descartar.clicked.connect(lambda: self.cargar_formulario(self.config))
        fila.addWidget(descartar)
        guardar = QPushButton("Guardar cambios")
        guardar.setObjectName("Primario")
        guardar.clicked.connect(self._guardar)
        fila.addWidget(guardar)
        self.barra_guardar.setVisible(False)
        return self.barra_guardar

    # ---- Página: Estado -------------------------------------------------------------
    def _pagina_estado(self):
        pagina, columna = self._crear_pagina(
            "Estado", "Cómo está la conexión ahora y qué PC está usando el mouse."
        )
        heroe = Tarjeta()
        heroe.cuerpo.setContentsMargins(24, 22, 24, 22)
        fila = QHBoxLayout()
        fila.setSpacing(18)
        self.icono_estado = QLabel()
        self.icono_estado.setFixedSize(64, 64)
        fila.addWidget(self.icono_estado, 0, Qt.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(4)
        self.titulo_estado = etiqueta("Detenido", "TituloEstado")
        textos.addWidget(self.titulo_estado)
        self.detalle_estado = etiqueta("", "Suave", ajustar=True)
        textos.addWidget(self.detalle_estado)
        textos.addStretch()
        fila.addLayout(textos, 1)
        heroe.agregar(fila)
        botones = QHBoxLayout()
        botones.setSpacing(10)
        self.boton_iniciar = QPushButton("  Iniciar")
        self.boton_iniciar.setObjectName("Primario")
        self.boton_iniciar.clicked.connect(self.iniciar_pedido)
        self.boton_pausar = QPushButton("  Pausar")
        self.boton_pausar.clicked.connect(self.pausa_pedida)
        self.boton_detener = QPushButton("  Detener")
        self.boton_detener.clicked.connect(self.detener_pedido)
        for boton in (self.boton_iniciar, self.boton_pausar, self.boton_detener):
            boton.setMinimumWidth(110)
            botones.addWidget(boton)
        botones.addStretch()
        heroe.agregar(botones)
        columna.addWidget(heroe)

        grilla = QGridLayout()
        grilla.setSpacing(16)
        esta = Tarjeta("Esta PC")
        self.dato_nombre = self._dato(esta, "Nombre", socket.gethostname())
        self.dato_rol = self._dato(esta, "Función", "")
        self.dato_ip = self._dato(esta, "IP en la red", "")
        otra = Tarjeta("La otra PC")
        self.dato_otra_nombre = self._dato(otra, "Nombre", "—")
        self.dato_otra_ip = self._dato(otra, "IP", "—")
        self.dato_otra_lado = self._dato(otra, "Ubicación", "—")
        ahora = Tarjeta("Ahora")
        self.dato_mouse = self._dato(ahora, "El mouse está", "En esta PC")
        self.dato_latencia = self._dato(ahora, "Demora de la red (ida y vuelta)", "—")
        for i, tarjeta in enumerate((esta, otra, ahora)):
            tarjeta.cuerpo.addStretch()  # Que los títulos queden alineados arriba.
            grilla.addWidget(tarjeta, 0, i)
        for i in range(3):
            grilla.setColumnStretch(i, 1)
        columna.addLayout(grilla)

        actividad = Tarjeta("Actividad")
        self.registro = QPlainTextEdit()
        self.registro.setObjectName("Registro")
        self.registro.setReadOnly(True)
        self.registro.setMaximumBlockCount(500)
        self.registro.setMinimumHeight(170)
        actividad.agregar(self.registro)
        columna.addWidget(actividad, 1)
        return pagina

    def _dato(self, tarjeta, titulo, valor):
        bloque = QVBoxLayout()
        bloque.setSpacing(1)
        bloque.addWidget(etiqueta(titulo, "DatoTitulo"))
        valor_label = etiqueta(valor, "DatoValor", ajustar=True)
        bloque.addWidget(valor_label)
        tarjeta.agregar(bloque)
        return valor_label

    # ---- Página: Pantallas ------------------------------------------------------------
    def _pagina_pantallas(self):
        pagina, columna = self._crear_pagina(
            "Pantallas",
            "Ubicá la otra PC respecto de esta, como están en tu escritorio. "
            "El cursor pasa a la otra PC por ese borde y vuelve por el opuesto.",
        )
        tarjeta = Tarjeta(
            "Ubicación de la otra PC",
            "Arrastrá el rectángulo violeta hasta el lado que corresponda y soltalo: "
            "se acomoda solo.",
        )
        self.editor = EditorPantallas()
        self.editor.setFixedHeight(300)
        self.editor.lado_cambiado.connect(self._al_elegir_lado)
        tarjeta.agregar(self.editor)
        fila = QHBoxLayout()
        fila.setSpacing(8)
        fila.addWidget(etiqueta("La otra PC está:", "Suave"))
        self.grupo_lado = QButtonGroup(self)
        self.grupo_lado.setExclusive(True)
        self.botones_lado = {}
        for lado, texto in (
            (IZQUIERDA, "A la izquierda"), (ARRIBA, "Arriba"), (ABAJO, "Abajo"),
            (DERECHA, "A la derecha"),
        ):
            boton = QPushButton(texto)
            boton.setObjectName("Lado")
            boton.setCheckable(True)
            boton.clicked.connect(lambda _=False, l=lado: self._al_elegir_lado(l, desde_boton=True))
            self.grupo_lado.addButton(boton)
            self.botones_lado[lado] = boton
            fila.addWidget(boton)
        fila.addStretch()
        tarjeta.agregar(fila)
        self.aviso_lado_cliente = etiqueta(
            "Esta PC recibe el control: la ubicación se elige en la PC que tiene el mouse. "
            "Acá ves cómo quedó configurada allá.", "Aviso", ajustar=True,
        )
        tarjeta.agregar(self.aviso_lado_cliente)
        columna.addWidget(tarjeta)

        esquinas = Tarjeta()
        self.spin_esquinas = self._spin(0, 500, " px")
        esquinas.agregar(FilaOpcion(
            "Esquinas sin paso",
            "Píxeles de cada punta del borde que no pasan a la otra PC. Sirven para llegar "
            "a la X de una ventana maximizada sin cambiar de PC.",
            self.spin_esquinas,
        ))
        columna.addWidget(esquinas)
        columna.addStretch()
        return pagina

    # ---- Página: Conexión ---------------------------------------------------------------
    def _pagina_conexion(self):
        pagina, columna = self._crear_pagina(
            "Conexión", "Qué hace esta PC y cómo se encuentra con la otra."
        )
        self.aviso_primera_vez = etiqueta(
            "Bienvenido. Empezá por acá: elegí qué hace esta PC, poné un PIN y tocá "
            "Guardar cambios. Hacé lo mismo en la otra PC con el mismo PIN.", "Aviso", ajustar=True,
        )
        columna.addWidget(self.aviso_primera_vez)

        roles = Tarjeta("¿Qué hace esta PC?")
        fila = QHBoxLayout()
        fila.setSpacing(12)
        self.opciones_rol = {
            SERVIDOR: OpcionRol(SERVIDOR, "mouse", "Tiene el mouse y el teclado",
                                "Es la PC principal (servidor)."),
            CLIENTE: OpcionRol(CLIENTE, "pantallas", "Recibe el control",
                               "La maneja el mouse de la otra PC (cliente)."),
        }
        for opcion in self.opciones_rol.values():
            opcion.elegida.connect(self._al_elegir_rol)
            fila.addWidget(opcion, 1)
        roles.agregar(fila)
        columna.addWidget(roles)

        emparejar = Tarjeta(
            "Emparejamiento",
            "El PIN tiene que ser exactamente igual en las dos PCs (mayúsculas incluidas). "
            "Así nadie más de la red puede conectarse.",
        )
        caja_pin = QWidget()
        fila_pin = QHBoxLayout(caja_pin)
        fila_pin.setContentsMargins(0, 0, 0, 0)
        fila_pin.setSpacing(4)
        self.campo_pin = QLineEdit()
        self.campo_pin.setEchoMode(QLineEdit.Password)
        self.campo_pin.setPlaceholderText("Mínimo 4 caracteres")
        self.campo_pin.setFixedWidth(220)
        self.campo_pin.textChanged.connect(self._marcar_cambios)
        ojo = QToolButton()
        ojo.setObjectName("Ojo")
        ojo.setText(estilo.GLIFOS["ojo"])
        fuente = estilo.fuente_iconos(12)
        if fuente:
            ojo.setStyleSheet(f'font-family: "{fuente.family()}"; font-size: 12pt;')
        ojo.setCheckable(True)
        ojo.setCursor(Qt.PointingHandCursor)
        ojo.setToolTip("Mostrar u ocultar el PIN")
        ojo.toggled.connect(lambda ver: self.campo_pin.setEchoMode(
            QLineEdit.Normal if ver else QLineEdit.Password))
        fila_pin.addWidget(self.campo_pin)
        fila_pin.addWidget(ojo)
        emparejar.agregar(FilaOpcion("PIN", "Mejor 8 caracteres o más.", caja_pin))
        emparejar.agregar(separador())
        self.spin_puerto = self._spin(1, 65535, "")
        self.spin_puerto.setFixedWidth(120)
        emparejar.agregar(FilaOpcion(
            "Puerto", "El mismo en las dos PCs. Cambialo solo si otro programa usa el 24850.",
            self.spin_puerto,
        ))
        columna.addWidget(emparejar)

        self.tarjeta_ip_servidor = Tarjeta("Dónde está la PC principal")
        self.campo_ip = QLineEdit()
        self.campo_ip.setPlaceholderText("Por ejemplo 192.168.1.28")
        self.campo_ip.setFixedWidth(220)
        self.campo_ip.textChanged.connect(self._marcar_cambios)
        self.tarjeta_ip_servidor.agregar(FilaOpcion(
            "IP de la PC con el mouse",
            "La ves en esa PC, en la página Estado → Esta PC → IP en la red.",
            self.campo_ip,
        ))
        columna.addWidget(self.tarjeta_ip_servidor)

        self.tarjeta_ip_propia = Tarjeta("IP de esta PC")
        self.texto_ip_propia = etiqueta("", "DatoValor", ajustar=True)
        self.tarjeta_ip_propia.agregar(self.texto_ip_propia)
        self.tarjeta_ip_propia.agregar(etiqueta(
            "Escribila en la otra PC, en Conexión → IP de la PC con el mouse.", "Suave", ajustar=True))
        columna.addWidget(self.tarjeta_ip_propia)

        columna.addWidget(etiqueta(
            "Próximamente (etapa 2): las PCs se van a encontrar solas en la red, sin escribir "
            "la IP, y se van a reconectar solas si se corta la red.", "Tenue", ajustar=True,
        ))
        columna.addStretch()
        return pagina

    # ---- Página: Atajos -------------------------------------------------------------------
    def _pagina_atajos(self):
        pagina, columna = self._crear_pagina(
            "Atajos", "Teclas para cambiar de PC rápido. El cambio por borde sigue andando siempre."
        )
        emergencia = Tarjeta(
            "Volver a esta PC (emergencia)",
            "Devuelve el mouse y el teclado a la PC principal al instante, aunque se haya "
            "cortado la red. Funciona siempre y no se puede desactivar.",
        )
        teclas = QHBoxLayout()
        teclas.setSpacing(6)
        for i, texto in enumerate(("Ctrl", "Alt", "Esc")):
            if i:
                teclas.addWidget(etiqueta("+", "Suave"))
            teclas.addWidget(Tecla(texto))
        teclas.addStretch()
        emergencia.agregar(teclas)
        columna.addWidget(emergencia)

        cambio = Tarjeta(
            "Cambiar de PC con una tecla",
            "Bloq Despl va a alternar entre las PCs, y su luz del teclado te va a indicar "
            "cuándo estás en la otra. Vas a poder elegir otra tecla.",
            insignia="Llega en la etapa 3",
        )
        interruptor = Interruptor()
        interruptor.setEnabled(False)
        cambio.agregar(FilaOpcion("Tecla para cambiar de PC", "", Tecla("Bloq Despl")))
        cambio.agregar(FilaOpcion("Activado", "", interruptor))
        columna.addWidget(cambio)

        multimedia = Tarjeta(
            "Volumen y multimedia",
            "Las teclas de volumen, silencio, play/pausa, siguiente y anterior van a actuar "
            "sobre la PC que estás usando.",
            insignia="Llega en la etapa 5",
        )
        columna.addWidget(multimedia)
        columna.addStretch()
        return pagina

    # ---- Página: Compartir -------------------------------------------------------------------
    def _pagina_compartir(self):
        pagina, columna = self._crear_pagina(
            "Compartir", "Portapapeles, archivos y una carpeta igual en las dos PCs. "
            "Van por un canal aparte para no demorar el mouse.",
        )
        portapapeles = Tarjeta(
            "Portapapeles compartido",
            "Copiás en una PC y pegás en la otra: primero texto, después imágenes.",
            insignia="Llega en la etapa 4",
        )
        columna.addWidget(portapapeles)
        archivos = Tarjeta(
            "Arrastrar archivos",
            "Arrastrás un archivo hasta el borde, pasás a la otra PC y se copia ahí, "
            "mostrando el progreso.",
            insignia="Llega en la etapa 6",
        )
        columna.addWidget(archivos)
        carpeta = Tarjeta(
            "Carpeta compartida",
            "Una carpeta en cada PC que se mantiene igual en las dos. Podés elegirla ya: "
            "la sincronización se activa en la etapa 7.",
            insignia="Sincroniza en la etapa 7",
        )
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.campo_carpeta = QLineEdit()
        self.campo_carpeta.setPlaceholderText("Ninguna elegida")
        self.campo_carpeta.textChanged.connect(self._marcar_cambios)
        fila.addWidget(self.campo_carpeta, 1)
        elegir = QPushButton("Elegir…")
        elegir.clicked.connect(self._elegir_carpeta)
        fila.addWidget(elegir)
        carpeta.agregar(fila)
        columna.addWidget(carpeta)
        columna.addStretch()
        return pagina

    # ---- Página: General ---------------------------------------------------------------------
    def _pagina_general(self):
        pagina, columna = self._crear_pagina("General", "Arranque y ajustes finos.")
        arranque = Tarjeta("Arranque")
        self.int_autoinicio = Interruptor()
        self.int_autoinicio.clicked.connect(self._al_tocar_autoinicio)
        arranque.agregar(FilaOpcion(
            "Iniciar con Windows",
            "Se abre solo al iniciar sesión, minimizado en la bandeja (al lado del reloj). "
            "Se aplica al instante.",
            self.int_autoinicio,
        ))
        arranque.agregar(separador())
        self.int_conectar = Interruptor()
        self.int_conectar.toggled.connect(self._marcar_cambios)
        arranque.agregar(FilaOpcion(
            "Conectar al abrir",
            "Empieza a compartir el mouse apenas se abre el programa.",
            self.int_conectar,
        ))
        columna.addWidget(arranque)

        avanzado = Tarjeta("Avanzado", "Valores finos. Si no sabés para qué son, dejalos como están.")
        self.spin_enfriamiento = self._spin(0, 2000, " ms")
        avanzado.agregar(FilaOpcion(
            "Espera después de cruzar",
            "Tiempo en el que no se puede volver a cruzar. Evita que el cursor rebote.",
            self.spin_enfriamiento,
        ))
        avanzado.agregar(separador())
        self.spin_hz = self._spin(0, 2000, " por seg.")
        avanzado.agregar(FilaOpcion(
            "Tope de mensajes del mouse",
            "0 = sin tope. 500 alcanza para cualquier mouse y no satura el Wi-Fi.",
            self.spin_hz,
        ))
        columna.addWidget(avanzado)

        archivos = Tarjeta("Archivos del programa")
        abrir_carpeta = QPushButton("Abrir carpeta")
        abrir_carpeta.clicked.connect(lambda: os.startfile(RAIZ))
        archivos.agregar(FilaOpcion("Carpeta del programa", str(RAIZ), abrir_carpeta))
        columna.addWidget(archivos)
        aviso_admin = "" if W.es_administrador() else (
            " · Sin permisos de Administrador: abrilo con iniciar.bat para controlar "
            "ventanas elevadas y activar el inicio con Windows."
        )
        columna.addWidget(etiqueta(
            f"Mouse Compartido · etapa 1 · protocolo v2{aviso_admin}", "Tenue", ajustar=True))
        columna.addStretch()
        return pagina

    def _spin(self, minimo, maximo, sufijo):
        spin = QSpinBox()
        spin.setRange(minimo, maximo)
        spin.setSuffix(sufijo)
        spin.setFixedWidth(140)
        spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        spin.valueChanged.connect(self._marcar_cambios)
        return spin

    # =================================================================================
    # Formulario <-> configuración
    # =================================================================================
    def cargar_formulario(self, config):
        """Llena todos los campos con `config` (sin marcar cambios)."""
        self._cargando = True
        try:
            self.config = config
            self._rol = config.rol
            self._lado = config.lado_otra_pantalla
            self.campo_pin.setText(config.pin)
            self.spin_puerto.setValue(config.puerto)
            self.campo_ip.setText(config.ip_servidor)
            self.spin_esquinas.setValue(config.esquinas_muertas_px)
            self.spin_enfriamiento.setValue(config.enfriamiento_ms)
            self.spin_hz.setValue(config.max_envios_mouse_hz)
            self.int_conectar.setChecked(config.conectar_al_abrir)
            self.int_autoinicio.setChecked(config.iniciar_con_windows)
            self.campo_carpeta.setText(config.carpeta_compartida)
            self._otra_pantallas = desde_lista(config.monitores_otra_pc) or self._otra_pantallas
            self._refrescar_rol()
            self._refrescar_editor()
        finally:
            self._cargando = False
        self.barra_guardar.setVisible(False)

    def _leer_formulario(self):
        return replace(
            self.config,
            rol=self._rol,
            pin=self.campo_pin.text(),
            puerto=self.spin_puerto.value(),
            ip_servidor=self.campo_ip.text().strip(),
            lado_otra_pantalla=self._lado,
            esquinas_muertas_px=self.spin_esquinas.value(),
            enfriamiento_ms=self.spin_enfriamiento.value(),
            max_envios_mouse_hz=self.spin_hz.value(),
            conectar_al_abrir=self.int_conectar.isChecked(),
            carpeta_compartida=self.campo_carpeta.text().strip(),
        )

    def _marcar_cambios(self, *_):
        if not self._cargando:
            self.barra_guardar.setVisible(self._leer_formulario() != self.config)

    def _guardar(self):
        nueva = self._leer_formulario()
        problemas = nueva.errores()
        self.config_guardada.emit(nueva)
        self.barra_guardar.setVisible(False)
        if problemas:
            QMessageBox.information(
                self, "Guardado, pero falta algo",
                "Se guardó. Para poder conectar todavía falta:\n\n• " + "\n• ".join(problemas),
            )

    def _al_elegir_rol(self, rol):
        self._rol = rol
        self._refrescar_rol()
        self._refrescar_editor()
        self._marcar_cambios()

    def _al_elegir_lado(self, lado, desde_boton=False):
        self._lado = lado
        if desde_boton:
            self.editor.poner_lado(lado)
        self.botones_lado[lado].setChecked(True)
        self._marcar_cambios()

    def _elegir_carpeta(self):
        actual = self.campo_carpeta.text() or os.path.expanduser("~")
        carpeta = QFileDialog.getExistingDirectory(self, "Elegí la carpeta compartida", actual)
        if carpeta:
            self.campo_carpeta.setText(os.path.normpath(carpeta))

    def _al_tocar_autoinicio(self, prendido):
        self.autoinicio_pedido.emit(prendido)

    def poner_autoinicio(self, prendido):
        """La app confirma cómo quedó (si Windows no dejó, vuelve a apagarse)."""
        self.int_autoinicio.setChecked(prendido)
        self.config = replace(self.config, iniciar_con_windows=prendido)

    def _refrescar_rol(self):
        rol = self._rol
        for clave, opcion in self.opciones_rol.items():
            opcion.marcar(clave == rol)
        self.tarjeta_ip_servidor.setVisible(rol == CLIENTE)
        self.tarjeta_ip_propia.setVisible(rol == SERVIDOR)
        self.aviso_primera_vez.setVisible(not self.config.rol)
        es_cliente = rol == CLIENTE
        self.aviso_lado_cliente.setVisible(es_cliente)
        for boton in self.botones_lado.values():
            boton.setEnabled(not es_cliente)
        self.texto_ip_propia.setText(", ".join(ips_locales()) or "No se encontró ninguna red")
        nombres = {SERVIDOR: "Tiene el mouse (servidor)", CLIENTE: "Recibe el control (cliente)"}
        self.dato_rol.setText(nombres.get(self.config.rol, "Sin elegir"))

    def _refrescar_editor(self):
        lado = self._lado
        if self._rol == CLIENTE and self._datos.get("lado"):
            lado = self._datos["lado"]  # Lo que dijo la PC principal al conectar.
        nombre_otra = self.config.nombre_otra_pc or "Otra PC"
        otra = self._datos.get("otra_pc") or {}
        if otra.get("nombre"):
            nombre_otra = otra["nombre"]
        self.editor.configurar(
            W.leer_pantallas(), self._otra_pantallas, socket.gethostname(), nombre_otra,
            lado, editable=self._rol != CLIENTE,
        )
        if lado in self.botones_lado:
            self.botones_lado[lado].setChecked(True)

    def actualizar_otra_pc(self, nombre, monitores, lado=None):
        """La app avisa que se conoce mejor a la otra PC (nombre, monitores y, en el cliente, lado)."""
        nuevas = desde_lista(monitores)
        if nuevas is not None:
            self._otra_pantallas = nuevas
        cambios = {"nombre_otra_pc": nombre,
                   "monitores_otra_pc": monitores or self.config.monitores_otra_pc}
        if lado:
            cambios["lado_otra_pantalla"] = lado
            self._lado = lado
        self.config = replace(self.config, **cambios)
        self._refrescar_editor()

    # =================================================================================
    # Estado
    # =================================================================================
    def mostrar_estado(self, activo, datos, error):
        anterior_lado = self._datos.get("lado")
        self._activo = activo
        self._datos = datos or {}
        self._error = error
        resumen = resumir(activo, self._datos, error)
        color = estilo.COLOR_ESTADO[resumen.clave]

        if resumen.clave != self._clave_estado:
            self._clave_estado = resumen.clave
            self.icono_estado.setPixmap(iconos.pixmap_estado(resumen.clave, 64))
            self.logo.setPixmap(iconos.pixmap_estado(resumen.clave, 36))
            self.setWindowIcon(iconos.icono_estado(resumen.clave))
            self.punto_mini.setStyleSheet(f"background: {color}; border-radius: 5px;")
        self.titulo_estado.setText(resumen.titulo)
        self.detalle_estado.setText(resumen.detalle)
        self.texto_mini.setText(resumen.titulo)

        pausado = bool(self._datos.get("pausa_local"))
        self.boton_iniciar.setEnabled(not activo)
        self.boton_pausar.setEnabled(activo)
        self.boton_pausar.setText("  Reanudar" if pausado else "  Pausar")
        self.boton_detener.setEnabled(activo)

        self.dato_ip.setText(", ".join(self._datos.get("ips") or ips_locales()) or "—")
        otra = self._datos.get("otra_pc") or {}
        conectado = self._datos.get("estado") == "conectado"
        self.dato_otra_nombre.setText(otra.get("nombre") or (
            self.config.nombre_otra_pc if not conectado and self.config.nombre_otra_pc else "—"))
        self.dato_otra_ip.setText(otra.get("ip") or (self.config.ip_servidor or "—"))
        lado = self._datos.get("lado") or self.config.lado_otra_pantalla
        self.dato_otra_lado.setText(NOMBRES_LADO.get(lado, "—").capitalize())
        self.dato_mouse.setText(donde_esta_el_mouse(self._datos))
        self.dato_latencia.setText(texto_latencia(self._datos))
        if self._datos.get("lado") != anterior_lado and self._rol == CLIENTE:
            self._refrescar_editor()

    def agregar_registro(self, linea):
        self.registro.appendPlainText(linea)

    # =================================================================================
    # Ventana
    # =================================================================================
    def mostrar_pagina(self, clave):
        for fila, (nombre, _) in enumerate(PAGINAS):
            if nombre == clave:
                self.navegacion.setCurrentRow(fila)

    def traer_al_frente(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def al_cambiar_tema(self):
        self._pintar_iconos_navegacion()
        self._clave_estado = None
        self.mostrar_estado(self._activo, self._datos, self._error)
        self._refrescar_editor()

    def closeEvent(self, evento):
        # La X no cierra el programa: lo deja en la bandeja (para cerrar: menú de la bandeja).
        evento.ignore()
        self.hide()
        self.escondida.emit()
