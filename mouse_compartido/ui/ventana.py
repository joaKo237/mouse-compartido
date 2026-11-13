"""Ventana principal: estado, pantallas, conexión, atajos, compartir y opciones generales.

Todo lo que se edita acá va a config.json al tocar "Guardar". Si el motor está
andando, se reinicia solo para aplicar los cambios (tarda un segundo).

Lo que no pasa por "Guardar" (emparejar, olvidar, mandar archivos) sale como
señal y lo resuelve la app (ui/app.py).
"""

import os
import socket
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
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
    QVBoxLayout,
    QWidget,
)

from .. import VERSION
from ..comun import config as modulo_config
from ..comun.config import CLIENTE, SERVIDOR
from ..comun.pantallas import ABAJO, ARRIBA, DERECHA, IZQUIERDA, desde_lista
from ..red import protocolo as P
from ..red.conexion import ips_locales
from ..sistema import win32 as W
from ..sistema.redes import NOMBRES_RUTA
from ..sistema.rutas import RAIZ, empaquetado
from . import estilo, iconos
from .archivos import carpeta_recibidos
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

NOMBRES_ROL = {SERVIDOR: "tiene el mouse", CLIENTE: "recibe el control"}


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
    emparejar_pedido = Signal(str)  # IP de la PC con la que emparejar.
    olvidar_pedido = Signal()
    archivos_soltados = Signal(list)  # Rutas para mandar a la otra PC.

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
        self._pcs = []  # Las PCs que se ven en la red (las pasa la app).
        self._pareja_vista = None
        self._aviso_pareja = ""

        self.setWindowTitle("Mouse Compartido")
        self.setAcceptDrops(True)  # Soltar archivos en la ventana los manda a la otra PC.
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
            "Conexión", "Qué hace esta PC y con qué PC comparte el mouse."
        )
        self.aviso_primera_vez = etiqueta(
            "Bienvenido. Son dos pasos y se hacen una sola vez: elegí qué hace esta PC (y tocá "
            "Guardar cambios) y emparejala con la otra, que tiene que tener el programa abierto. "
            "Después se encuentran y se conectan solas, por cable o por Wi-Fi.",
            "Aviso", ajustar=True,
        )
        columna.addWidget(self.aviso_primera_vez)

        roles = Tarjeta("1. ¿Qué hace esta PC?")
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

        self.tarjeta_pareja = Tarjeta("2. PC emparejada")
        fila = QHBoxLayout()
        fila.setSpacing(14)
        self.icono_pareja = glifo("pantallas", 20, estilo.tema_actual()["otra_pc"])
        self.icono_pareja.setFixedWidth(30)
        fila.addWidget(self.icono_pareja, 0, Qt.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        self.nombre_pareja = etiqueta("", "DatoValor", ajustar=True)
        textos.addWidget(self.nombre_pareja)
        self.estado_pareja = etiqueta("", "Suave", ajustar=True)
        textos.addWidget(self.estado_pareja)
        fila.addLayout(textos, 1)
        self.boton_olvidar = QPushButton("Olvidar")
        self.boton_olvidar.setToolTip("Dejar de conectarse con esa PC (se puede volver a emparejar)")
        self.boton_olvidar.clicked.connect(self.olvidar_pedido)
        fila.addWidget(self.boton_olvidar, 0, Qt.AlignVCenter)
        self.tarjeta_pareja.agregar(fila)
        self.aviso_pareja = etiqueta("", "Aviso", ajustar=True)
        self.aviso_pareja.setVisible(False)
        self.tarjeta_pareja.agregar(self.aviso_pareja)
        columna.addWidget(self.tarjeta_pareja)

        cercanas = Tarjeta(
            "PCs encontradas en la red",
            "Las que tienen Mouse Compartido abierto, por cable o por Wi-Fi. Tocá Emparejar y "
            "confirmá que el número de 6 cifras sea el mismo en las dos.",
        )
        self.lista_pcs = QVBoxLayout()
        self.lista_pcs.setSpacing(8)
        cercanas.agregar(self.lista_pcs)
        cercanas.agregar(separador())
        manual = QHBoxLayout()
        manual.setSpacing(8)
        manual.addWidget(etiqueta("¿No aparece? Emparejá con su IP:", "Suave"))
        self.campo_ip_emparejar = QLineEdit()
        self.campo_ip_emparejar.setPlaceholderText("Por ejemplo 192.168.1.28")
        self.campo_ip_emparejar.setFixedWidth(200)
        self.campo_ip_emparejar.returnPressed.connect(self._emparejar_por_ip)
        manual.addWidget(self.campo_ip_emparejar)
        boton_ip = QPushButton("Emparejar")
        boton_ip.clicked.connect(self._emparejar_por_ip)
        manual.addWidget(boton_ip)
        manual.addStretch()
        cercanas.agregar(manual)
        columna.addWidget(cercanas)

        avanzado = Tarjeta("Avanzado", "Solo si algo no anda. Si no sabés para qué son, "
                                       "dejalos como están.")
        self.spin_puerto = self._spin(1, 65534, "")
        self.spin_puerto.setFixedWidth(120)
        avanzado.agregar(FilaOpcion(
            "Puerto", "El mismo en las dos PCs. Se usan este y el siguiente. Cambialo solo si "
            "otro programa usa el 24850.", self.spin_puerto,
        ))
        self.separador_ip_fija = separador()
        avanzado.agregar(self.separador_ip_fija)
        self.campo_ip = QLineEdit()
        self.campo_ip.setPlaceholderText("Vacía = la busca sola")
        self.campo_ip.setFixedWidth(220)
        self.campo_ip.textChanged.connect(self._marcar_cambios)
        self.fila_ip_fija = FilaOpcion(
            "IP fija de la PC con el mouse",
            "Solo si no se encuentran solas (algunas redes de oficinas o bares lo bloquean). "
            "Se ve en esa PC, en Estado → Esta PC.", self.campo_ip,
        )
        avanzado.agregar(self.fila_ip_fija)
        self.texto_ip_propia = etiqueta("", "Tenue", ajustar=True)
        avanzado.agregar(self.texto_ip_propia)
        columna.addWidget(avanzado)
        columna.addStretch()
        self.mostrar_red([], None)
        return pagina

    def _emparejar_por_ip(self):
        ip = self.campo_ip_emparejar.text().strip()
        if ip:
            self.emparejar_pedido.emit(ip)

    # ---- Página: Atajos -------------------------------------------------------------------
    def _pagina_atajos(self):
        pagina, columna = self._crear_pagina(
            "Atajos", "Teclas para cambiar de PC rápido. El cambio por borde sigue andando siempre."
        )
        self.aviso_atajos_cliente = etiqueta(
            "Esta PC recibe el control: los atajos se configuran en la PC que tiene el mouse "
            "y el teclado.", "Aviso", ajustar=True,
        )
        columna.addWidget(self.aviso_atajos_cliente)
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
            "La tocás y el mouse y el teclado pasan a la otra PC; la volvés a tocar y vuelven. "
            "Mientras las PCs están conectadas, esa tecla no le llega a ningún programa.",
        )
        self.int_atajo = Interruptor()
        self.int_atajo.toggled.connect(self._marcar_cambios)
        cambio.agregar(FilaOpcion("Activado", "", self.int_atajo))
        cambio.agregar(separador())
        self.combo_tecla = QComboBox()
        self.combo_tecla.addItem("Bloq Despl (Scroll Lock)", "bloq_despl")
        self.combo_tecla.addItem("Pausa", "pausa")
        self.combo_tecla.setFixedWidth(220)
        self.combo_tecla.currentIndexChanged.connect(self._marcar_cambios)
        cambio.agregar(FilaOpcion(
            "Tecla", "Casi ningún programa las usa. Si tu teclado no tiene Bloq Despl, elegí "
            "Pausa.", self.combo_tecla,
        ))
        cambio.agregar(separador())
        self.int_luz = Interruptor()
        self.int_luz.toggled.connect(self._marcar_cambios)
        cambio.agregar(FilaOpcion(
            "Luz de Bloq Despl = estás en la otra PC",
            "La luz del teclado se prende mientras manejás la otra PC, para saber dónde estás "
            "de un vistazo (si tu teclado tiene esa luz).", self.int_luz,
        ))
        columna.addWidget(cambio)

        multimedia = Tarjeta("Volumen y multimedia")
        self.int_multimedia = Interruptor()
        self.int_multimedia.toggled.connect(self._marcar_cambios)
        multimedia.agregar(FilaOpcion(
            "Actúan sobre la PC que estás usando",
            "Volumen, silencio, play/pausa, siguiente y anterior. Apagado: siempre actúan "
            "sobre esta PC (útil si los parlantes están conectados acá).", self.int_multimedia,
        ))
        columna.addWidget(multimedia)
        columna.addStretch()
        return pagina

    # ---- Página: Compartir -------------------------------------------------------------------
    def _pagina_compartir(self):
        pagina, columna = self._crear_pagina(
            "Compartir", "Portapapeles, archivos y una carpeta igual en las dos PCs. "
            "Van por un canal aparte y cifrado, para no demorar el mouse.",
        )
        portapapeles = Tarjeta(
            "Portapapeles compartido",
            "Copiás en una PC y pegás en la otra: texto (con o sin formato) e imágenes. "
            "Lo que copia un administrador de contraseñas no se comparte.",
        )
        self.int_portapapeles = Interruptor()
        self.int_portapapeles.toggled.connect(self._marcar_cambios)
        portapapeles.agregar(FilaOpcion(
            "Activado", "Tiene que estar prendido en las dos PCs.", self.int_portapapeles,
        ))
        portapapeles.agregar(separador())
        self.spin_portapapeles = self._spin(1, 200, " MB")
        portapapeles.agregar(FilaOpcion(
            "Tope por copia",
            "Lo que pese más no se pasa. Una captura de pantalla pesa 1 o 2 MB.",
            self.spin_portapapeles,
        ))
        self.estado_portapapeles = etiqueta("", "Suave", ajustar=True)
        portapapeles.agregar(self.estado_portapapeles)
        columna.addWidget(portapapeles)

        archivos = Tarjeta(
            "Archivos",
            "Copiás archivos o carpetas en el Explorador (Ctrl+C), pasás a la otra PC y pegás "
            "(Ctrl+V). Para mandarlos a propósito: el botón de abajo o clic derecho → Enviar a "
            "→ Mouse Compartido.",
        )
        self.int_archivos = Interruptor()
        self.int_archivos.toggled.connect(self._marcar_cambios)
        archivos.agregar(FilaOpcion(
            "Activado", "Tiene que estar prendido en las dos PCs.", self.int_archivos,
        ))
        archivos.agregar(separador())
        self.spin_archivos = self._spin(1, 102400, " MB")
        archivos.agregar(FilaOpcion(
            "Tope para copiar y pegar",
            "Hasta 64 MB viaja enseguida; si pesa más, cuando llevás el mouse a la otra PC. "
            "Mandar a propósito no tiene tope.", self.spin_archivos,
        ))
        archivos.agregar(separador())
        fila = QHBoxLayout()
        fila.setSpacing(8)
        fila.addWidget(etiqueta("Los que te mandan llegan a:", "Suave"))
        self.campo_recibidos = QLineEdit()
        self.campo_recibidos.textChanged.connect(self._marcar_cambios)
        fila.addWidget(self.campo_recibidos, 1)
        elegir = QPushButton("Elegir…")
        elegir.clicked.connect(lambda: self._elegir_carpeta_en(
            self.campo_recibidos, "Dónde guardar lo que llega de la otra PC"))
        fila.addWidget(elegir)
        archivos.agregar(fila)
        botones = QHBoxLayout()
        mandar = QPushButton("Mandar archivos a la otra PC…")
        mandar.clicked.connect(self._elegir_archivos_para_mandar)
        botones.addWidget(mandar)
        botones.addStretch()
        archivos.agregar(botones)
        archivos.agregar(etiqueta(
            "¿Y arrastrarlos hasta el borde de la pantalla? En Windows el arrastre lo maneja el "
            "programa de origen y no se puede continuar en otra PC sin fallas; copiar y pegar "
            "hace lo mismo y siempre anda. Soltarlos sobre esta ventana también los manda "
            "(salvo con el programa como Administrador: Windows no deja).", "Tenue", ajustar=True,
        ))
        columna.addWidget(archivos)

        carpeta = Tarjeta(
            "Carpeta sincronizada",
            "Una carpeta en cada PC que se mantiene igual en las dos: lo que agregás, cambiás "
            "o borrás en una pasa a la otra. Lo borrado va a la Papelera, por las dudas.",
        )
        self.int_carpeta = Interruptor()
        self.int_carpeta.toggled.connect(self._marcar_cambios)
        carpeta.agregar(FilaOpcion(
            "Activada", "Activala en las dos PCs, cada una con su carpeta.", self.int_carpeta,
        ))
        carpeta.agregar(separador())
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.campo_carpeta = QLineEdit()
        self.campo_carpeta.setPlaceholderText("Ninguna elegida")
        self.campo_carpeta.textChanged.connect(self._marcar_cambios)
        fila.addWidget(self.campo_carpeta, 1)
        elegir = QPushButton("Elegir…")
        elegir.clicked.connect(lambda: self._elegir_carpeta_en(
            self.campo_carpeta, "Elegí la carpeta compartida"))
        fila.addWidget(elegir)
        carpeta.agregar(fila)
        self.estado_carpeta = etiqueta("", "Suave", ajustar=True)
        carpeta.agregar(self.estado_carpeta)
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
        carpeta_config = modulo_config.RUTA_POR_DEFECTO.parent
        if carpeta_config != RAIZ:
            archivos.agregar(separador())
            abrir_config = QPushButton("Abrir carpeta")
            abrir_config.clicked.connect(lambda: os.startfile(carpeta_config))
            archivos.agregar(FilaOpcion("Configuración (config.json)", str(carpeta_config),
                                        abrir_config))
        columna.addWidget(archivos)
        como_abrir = "abrilo con clic derecho → Ejecutar como administrador" if empaquetado() \
            else "abrilo con iniciar.bat"
        aviso_admin = "" if W.es_administrador() else (
            f" · Sin permisos de Administrador: {como_abrir} para controlar ventanas elevadas, "
            "abrir el firewall y activar el inicio con Windows."
        )
        columna.addWidget(etiqueta(
            f"Mouse Compartido {VERSION} · protocolo v{P.VERSION}{aviso_admin}", "Tenue",
            ajustar=True))
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
            self.spin_puerto.setValue(config.puerto)
            self.campo_ip.setText(config.ip_servidor)
            self.spin_esquinas.setValue(config.esquinas_muertas_px)
            self.spin_enfriamiento.setValue(config.enfriamiento_ms)
            self.spin_hz.setValue(config.max_envios_mouse_hz)
            self.int_conectar.setChecked(config.conectar_al_abrir)
            self.int_autoinicio.setChecked(config.iniciar_con_windows)
            self.campo_carpeta.setText(config.carpeta_compartida)
            self.int_portapapeles.setChecked(config.compartir_portapapeles)
            self.spin_portapapeles.setValue(config.portapapeles_max_mb)
            self.int_atajo.setChecked(config.atajo_cambiar)
            self.combo_tecla.setCurrentIndex(max(0, self.combo_tecla.findData(config.tecla_cambiar)))
            self.int_luz.setChecked(config.luz_otra_pc)
            self.int_multimedia.setChecked(config.multimedia_pc_activa)
            self.int_archivos.setChecked(config.compartir_archivos)
            self.spin_archivos.setValue(config.archivos_max_mb)
            self.campo_recibidos.setText(config.carpeta_recibidos)
            self.campo_recibidos.setPlaceholderText(str(carpeta_recibidos(
                replace(config, carpeta_recibidos=""))))
            self.int_carpeta.setChecked(config.sincronizar_carpeta)
            self._refrescar_pareja()
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
            puerto=self.spin_puerto.value(),
            ip_servidor=self.campo_ip.text().strip(),
            lado_otra_pantalla=self._lado,
            esquinas_muertas_px=self.spin_esquinas.value(),
            enfriamiento_ms=self.spin_enfriamiento.value(),
            max_envios_mouse_hz=self.spin_hz.value(),
            conectar_al_abrir=self.int_conectar.isChecked(),
            carpeta_compartida=self.campo_carpeta.text().strip(),
            compartir_portapapeles=self.int_portapapeles.isChecked(),
            portapapeles_max_mb=self.spin_portapapeles.value(),
            atajo_cambiar=self.int_atajo.isChecked(),
            tecla_cambiar=self.combo_tecla.currentData() or "bloq_despl",
            luz_otra_pc=self.int_luz.isChecked(),
            multimedia_pc_activa=self.int_multimedia.isChecked(),
            compartir_archivos=self.int_archivos.isChecked(),
            archivos_max_mb=self.spin_archivos.value(),
            carpeta_recibidos=self.campo_recibidos.text().strip(),
            sincronizar_carpeta=self.int_carpeta.isChecked(),
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

    def _elegir_carpeta_en(self, campo, titulo):
        actual = campo.text() or campo.placeholderText() or os.path.expanduser("~")
        if not os.path.isdir(actual):
            actual = os.path.expanduser("~")
        carpeta = QFileDialog.getExistingDirectory(self, titulo, actual)
        if carpeta:
            campo.setText(os.path.normpath(carpeta))

    def _elegir_archivos_para_mandar(self):
        rutas, _ = QFileDialog.getOpenFileNames(self, "Elegí qué mandar a la otra PC",
                                                os.path.expanduser("~"))
        if rutas:
            self.archivos_soltados.emit([os.path.normpath(r) for r in rutas])

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
        es_cliente = rol == CLIENTE
        self.fila_ip_fija.setVisible(es_cliente)
        self.separador_ip_fija.setVisible(es_cliente)
        self.aviso_primera_vez.setVisible(not self.config.rol or not self.config.emparejada)
        self.aviso_lado_cliente.setVisible(es_cliente)
        self.aviso_atajos_cliente.setVisible(es_cliente)
        for boton in self.botones_lado.values():
            boton.setEnabled(not es_cliente)
        ips = ", ".join(ips_locales()) or "no se encontró ninguna red"
        self.texto_ip_propia.setText(f"IP de esta PC: {ips}.")
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
        guardado = self.config.emparejado_nombre or self.config.nombre_otra_pc
        self.dato_otra_nombre.setText(otra.get("nombre") or (
            guardado if not conectado and guardado else "—"))
        self.dato_otra_ip.setText(otra.get("ip") or self.config.ultima_ip_otra_pc or "—")
        lado = self._datos.get("lado") or self.config.lado_otra_pantalla
        self.dato_otra_lado.setText(NOMBRES_LADO.get(lado, "—").capitalize())
        self.dato_mouse.setText(donde_esta_el_mouse(self._datos))
        self.dato_latencia.setText(texto_latencia(self._datos))
        if self._datos.get("lado") != anterior_lado and self._rol == CLIENTE:
            self._refrescar_editor()

    def mostrar_portapapeles(self, activo, listo, conectado):
        """El renglón de estado de la tarjeta del portapapeles (página Compartir)."""
        if not activo:
            texto = "Apagado en esta PC."
        elif listo:
            texto = "● Listo: lo que copies en una PC se puede pegar en la otra."
        elif conectado:
            texto = ("Conectando el portapapeles… Si no pasa a «Listo», revisá que la otra PC "
                     "tenga esta misma versión.")
        else:
            texto = "Se activa cuando las dos PCs estén conectadas."
        self.estado_portapapeles.setText(texto)

    def mostrar_carpeta(self, texto):
        """El renglón de estado de la carpeta sincronizada (página Compartir)."""
        if self.estado_carpeta.text() != texto:
            self.estado_carpeta.setText(texto)

    def agregar_registro(self, linea):
        self.registro.appendPlainText(linea)

    # =================================================================================
    # Red y emparejamiento
    # =================================================================================
    def mostrar_red(self, pcs, pareja, aviso=""):
        """La app avisa qué PCs se ven en la red (PcVista), si entre ellas está la
        emparejada y si hay algo que advertir sobre ella."""
        self._pcs = list(pcs)
        self._pareja_vista = pareja
        self._aviso_pareja = aviso
        self._refrescar_pareja()
        while self.lista_pcs.count():
            widget = self.lista_pcs.takeAt(0).widget()
            if widget is not None:
                # Se esconde ya: si solo se borrara "más tarde", quedaría a la vista un rato.
                widget.hide()
                widget.deleteLater()
        if not self._pcs:
            self.lista_pcs.addWidget(etiqueta(
                "Buscando… Abrí Mouse Compartido en la otra PC. Tienen que estar en la misma "
                "red: el mismo router (por cable o Wi-Fi) o un cable entre las dos.",
                "Suave", ajustar=True))
            return
        for pc in self._pcs:
            self.lista_pcs.addWidget(self._fila_pc(pc))

    def _fila_pc(self, pc):
        fila = QFrame()
        fila.setObjectName("FilaPc")
        caja = QHBoxLayout(fila)
        caja.setContentsMargins(14, 10, 14, 10)
        caja.setSpacing(12)
        textos = QVBoxLayout()
        textos.setSpacing(1)
        nombre = etiqueta(pc.nombre or pc.ip)
        nombre.setStyleSheet("font-weight: 600;")
        textos.addWidget(nombre)
        partes = [f"{pc.ip} · por {NOMBRES_RUTA.get(pc.mejor_prioridad, 'red')}"]
        if pc.rol in NOMBRES_ROL:
            partes.append(NOMBRES_ROL[pc.rol])
        if pc.emparejado_con and pc.emparejado_con != self.config.id_pc:
            partes.append("emparejada con otra PC")
        if pc.version and pc.version != P.VERSION:
            partes.append("tiene otra versión del programa")
        textos.addWidget(etiqueta(" · ".join(partes), "Suave", ajustar=True))
        caja.addLayout(textos, 1)
        if self.config.emparejada and pc.id == self.config.emparejado_id:
            caja.addWidget(etiqueta("Emparejada ✓", "Suave"), 0, Qt.AlignVCenter)
        else:
            boton = QPushButton("Emparejar")
            if not self.config.emparejada:
                boton.setObjectName("Primario")
            boton.clicked.connect(lambda _=False, ip=pc.ip: self.emparejar_pedido.emit(ip))
            caja.addWidget(boton, 0, Qt.AlignVCenter)
        return fila

    def _refrescar_pareja(self):
        config = self.config
        if not config.emparejada:
            self.nombre_pareja.setText("Todavía ninguna")
            self.estado_pareja.setText("Elegí la otra PC en la lista de abajo y tocá Emparejar.")
            self.boton_olvidar.setVisible(False)
            self.aviso_pareja.setVisible(False)
            return
        self.boton_olvidar.setVisible(True)
        self.nombre_pareja.setText(config.emparejado_nombre or "La otra PC")
        pareja = self._pareja_vista
        if pareja is not None and pareja.ip:
            ruta = NOMBRES_RUTA.get(pareja.mejor_prioridad, "red")
            self.estado_pareja.setText(f"En la red ahora, por {ruta} ({pareja.ip}).")
        else:
            self.estado_pareja.setText(
                "No se la ve en la red ahora. ¿Está prendida y con el programa abierto?")
        self.aviso_pareja.setText(self._aviso_pareja)
        self.aviso_pareja.setVisible(bool(self._aviso_pareja))

    def aplicar_campos(self, cambios):
        """La app cambió algunos campos por su cuenta (al emparejar u olvidar). Si no
        estás editando nada, se recarga todo; si sí, se respeta lo que estás editando."""
        nueva = replace(self.config, **cambios)
        if not self.barra_guardar.isVisible():
            self.cargar_formulario(nueva)
            return
        self.config = nueva
        if "rol" in cambios and not self._rol:
            self._rol = cambios["rol"]
        self._refrescar_rol()
        self._refrescar_pareja()
        self.mostrar_red(self._pcs, self._pareja_vista, self._aviso_pareja)
        self._marcar_cambios()

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
        self.mostrar_red(self._pcs, self._pareja_vista, self._aviso_pareja)
        self._clave_estado = None
        self.mostrar_estado(self._activo, self._datos, self._error)
        self._refrescar_editor()

    def dragEnterEvent(self, evento):
        mime = evento.mimeData()
        if mime.hasUrls() and any(url.isLocalFile() for url in mime.urls()):
            evento.acceptProposedAction()

    def dropEvent(self, evento):
        rutas = [os.path.normpath(url.toLocalFile()) for url in evento.mimeData().urls()
                 if url.isLocalFile()]
        if rutas:
            evento.acceptProposedAction()
            self.archivos_soltados.emit(rutas)

    def closeEvent(self, evento):
        # La X no cierra el programa: lo deja en la bandeja (para cerrar: menú de la bandeja).
        evento.ignore()
        self.hide()
        self.escondida.emit()
