"""Aspecto visual: colores, tipografía e íconos.

Sigue el modo claro u oscuro de Windows (Configuración → Personalización →
Colores) y cambia solo si lo cambiás con el programa abierto.

Los colores están todos acá, con nombre, para cambiarlos en un solo lugar.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette

from .resumen import CONECTADO, DETENIDO, ERROR, ESPERANDO, PAUSADO

CLARO = {
    "fondo": "#f3f4f7",
    "lateral": "#eceef3",
    "tarjeta": "#ffffff",
    "campo": "#f7f8fa",
    "borde": "#e0e3ea",
    "borde_fuerte": "#c9ced8",
    "texto": "#1d2027",
    "suave": "#5f6673",
    "tenue": "#9aa1ad",
    "hover": "#e2e5ec",
    "seleccion": "#dde7fd",
    "acento": "#2f6fec",
    "acento_hover": "#4a82f0",
    "acento_texto": "#ffffff",
    "otra_pc": "#7c5cf0",
    "insignia_fondo": "#eceef3",
    "insignia_texto": "#5f6673",
    "peligro": "#d93025",
}

OSCURO = {
    "fondo": "#16181d",
    "lateral": "#1c1f25",
    "tarjeta": "#21252c",
    "campo": "#1a1d23",
    "borde": "#2e333c",
    "borde_fuerte": "#3d434e",
    "texto": "#e9ebef",
    "suave": "#a1a7b3",
    "tenue": "#6c7380",
    "hover": "#292d35",
    "seleccion": "#25324a",
    "acento": "#5b8def",
    "acento_hover": "#76a0f2",
    "acento_texto": "#ffffff",
    "otra_pc": "#9b82f5",
    "insignia_fondo": "#2a2f38",
    "insignia_texto": "#a1a7b3",
    "peligro": "#ff6b5e",
}

# Color de cada estado: el mismo en la ventana y en el ícono de la bandeja.
COLOR_ESTADO = {
    DETENIDO: "#8e8e93",  # Gris: apagado.
    ESPERANDO: "#ff9f0a",  # Naranja: buscando a la otra PC.
    CONECTADO: "#30c158",  # Verde: todo bien.
    PAUSADO: "#a35cf0",  # Violeta: conectado pero sin cambiar de PC.
    ERROR: "#ff453a",  # Rojo: algo falló (puerto ocupado, PC no emparejada...).
}

# Íconos de la fuente de Windows (Segoe Fluent Icons en Windows 11, MDL2 en Windows 10).
GLIFOS = {
    "estado": "",  # Casa
    "pantallas": "",  # Monitor
    "conexion": "",  # Wi-Fi
    "atajos": "",  # Teclado
    "compartir": "",  # Carpeta
    "general": "",  # Engranaje
    "iniciar": "",  # Play
    "pausar": "",  # Pausa
    "detener": "",  # Stop
    "mouse": "",  # Mouse
    "ojo": "",  # Ver
    "carpeta": "",  # Abrir carpeta
}


def es_oscuro():
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def tema_actual():
    return OSCURO if es_oscuro() else CLARO


def _familia(*preferidas):
    disponibles = set(QFontDatabase.families())
    for familia in preferidas:
        if familia in disponibles:
            return familia
    return ""


def fuente_iconos(puntos=12):
    familia = _familia("Segoe Fluent Icons", "Segoe MDL2 Assets")
    if not familia:
        return None
    fuente = QFont(familia)
    fuente.setPointSizeF(puntos)
    return fuente


def familia_texto():
    return _familia("Segoe UI Variable Text", "Segoe UI") or QFont().family()


def familia_mono():
    return _familia("Cascadia Mono", "Consolas") or "monospace"


def _paleta(t):
    """Colores base de Qt, para que los diálogos estándar combinen con el resto."""
    p = QPalette()
    for rol, color in (
        (QPalette.Window, t["fondo"]), (QPalette.WindowText, t["texto"]),
        (QPalette.Base, t["campo"]), (QPalette.AlternateBase, t["tarjeta"]),
        (QPalette.Text, t["texto"]), (QPalette.Button, t["tarjeta"]),
        (QPalette.ButtonText, t["texto"]), (QPalette.Highlight, t["acento"]),
        (QPalette.HighlightedText, t["acento_texto"]), (QPalette.ToolTipBase, t["tarjeta"]),
        (QPalette.ToolTipText, t["texto"]), (QPalette.PlaceholderText, t["tenue"]),
        (QPalette.Link, t["acento"]),
    ):
        p.setColor(rol, QColor(color))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(t["tenue"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["tenue"]))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(t["tenue"]))
    return p


def hoja_de_estilo(t):
    texto = familia_texto()
    mono = familia_mono()
    return f"""
    * {{ font-family: "{texto}"; font-size: 10pt; }}
    QWidget {{ color: {t['texto']}; }}
    QMainWindow, #Fondo, #Contenido {{ background: {t['fondo']}; }}
    QToolTip {{ background: {t['tarjeta']}; color: {t['texto']}; border: 1px solid {t['borde']};
               padding: 6px 8px; border-radius: 6px; }}

    #BarraLateral {{ background: {t['lateral']}; border-right: 1px solid {t['borde']}; }}
    #Marca {{ font-size: 11.5pt; font-weight: 600; }}
    #MarcaSub {{ color: {t['suave']}; font-size: 9pt; }}
    QListWidget#Navegacion {{ background: transparent; border: none; outline: 0; }}
    QListWidget#Navegacion::item {{ padding: 9px 10px; margin: 2px 10px; border-radius: 8px;
                                    color: {t['suave']}; }}
    QListWidget#Navegacion::item:hover {{ background: {t['hover']}; color: {t['texto']}; }}
    QListWidget#Navegacion::item:selected {{ background: {t['seleccion']}; color: {t['texto']}; }}
    #EstadoMini {{ color: {t['suave']}; font-size: 9pt; }}

    #TituloPagina {{ font-size: 19pt; font-weight: 600; }}
    #Subtitulo {{ color: {t['suave']}; }}
    #Tarjeta {{ background: {t['tarjeta']}; border: 1px solid {t['borde']}; border-radius: 12px; }}
    #TituloTarjeta {{ font-size: 11pt; font-weight: 600; }}
    #Suave {{ color: {t['suave']}; }}
    #Tenue {{ color: {t['tenue']}; font-size: 9pt; }}
    #TituloEstado {{ font-size: 17pt; font-weight: 600; }}
    #DatoTitulo {{ color: {t['suave']}; font-size: 9pt; }}
    #DatoValor {{ font-size: 10.5pt; font-weight: 600; }}
    #Aviso {{ background: {t['seleccion']}; border-radius: 10px; padding: 10px 14px; }}
    #Separador {{ background: {t['borde']}; max-height: 1px; min-height: 1px; border: none; }}

    #Insignia {{ background: {t['insignia_fondo']}; color: {t['insignia_texto']};
                 border-radius: 9px; padding: 2px 9px; font-size: 8.5pt; font-weight: 600; }}
    #Tecla {{ background: {t['campo']}; border: 1px solid {t['borde_fuerte']};
              border-bottom: 3px solid {t['borde_fuerte']}; border-radius: 6px;
              padding: 3px 10px; font-weight: 600; }}

    QPushButton {{ background: {t['tarjeta']}; border: 1px solid {t['borde_fuerte']};
                   border-radius: 8px; padding: 7px 16px; }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QPushButton:pressed {{ background: {t['borde']}; }}
    QPushButton:disabled {{ color: {t['tenue']}; border-color: {t['borde']}; }}
    QPushButton#Primario {{ background: {t['acento']}; color: {t['acento_texto']};
                            border: 1px solid {t['acento']}; font-weight: 600; }}
    QPushButton#Primario:hover {{ background: {t['acento_hover']}; border-color: {t['acento_hover']}; }}
    QPushButton#Primario:disabled {{ background: {t['borde']}; border-color: {t['borde']};
                                     color: {t['tenue']}; }}
    QPushButton#Lado {{ padding: 6px 12px; border-radius: 7px; }}
    QPushButton#Lado:checked {{ background: {t['seleccion']}; border: 1px solid {t['acento']};
                                color: {t['acento']}; }}
    QToolButton#Ojo {{ border: none; background: transparent; padding: 0 6px; color: {t['suave']}; }}

    QLineEdit, QSpinBox {{ background: {t['campo']}; border: 1px solid {t['borde_fuerte']};
                           border-radius: 8px; padding: 6px 10px; min-height: 20px;
                           selection-background-color: {t['acento']};
                           selection-color: {t['acento_texto']}; }}
    QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {t['acento']}; }}
    QLineEdit:disabled, QSpinBox:disabled {{ color: {t['tenue']}; border-color: {t['borde']}; }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}

    QPlainTextEdit#Registro {{ background: {t['campo']}; border: 1px solid {t['borde']};
                               border-radius: 8px; padding: 6px; font-family: "{mono}";
                               font-size: 8.8pt; color: {t['suave']}; }}

    #OpcionRol {{ background: {t['campo']}; border: 1px solid {t['borde']}; border-radius: 10px; }}
    #OpcionRol:hover {{ border-color: {t['borde_fuerte']}; }}
    #OpcionRol[elegida="true"] {{ background: {t['seleccion']}; border: 2px solid {t['acento']}; }}

    #BarraGuardar {{ background: {t['tarjeta']}; border-top: 1px solid {t['borde']}; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['borde_fuerte']}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

    QMenu {{ background: {t['tarjeta']}; border: 1px solid {t['borde']}; border-radius: 8px; padding: 5px; }}
    QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {t['seleccion']}; }}
    QMenu::item:disabled {{ color: {t['tenue']}; }}
    QMenu::separator {{ height: 1px; background: {t['borde']}; margin: 5px 8px; }}

    QMessageBox, QDialog {{ background: {t['tarjeta']}; }}

    QComboBox {{ background: {t['campo']}; border: 1px solid {t['borde_fuerte']}; border-radius: 8px;
                 padding: 6px 10px; min-height: 20px; }}
    QComboBox:focus {{ border: 1px solid {t['acento']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{ background: {t['tarjeta']}; border: 1px solid {t['borde']};
                                   selection-background-color: {t['seleccion']};
                                   selection-color: {t['texto']}; outline: 0; padding: 4px; }}
    QProgressBar {{ background: {t['borde']}; border: none; border-radius: 3px; }}
    QProgressBar::chunk {{ background: {t['acento']}; border-radius: 3px; }}
    #FilaPc, #FilaEnvio {{ background: {t['campo']}; border: 1px solid {t['borde']};
                           border-radius: 10px; }}
    #Codigo {{ font-size: 30pt; font-weight: 700; color: {t['acento']}; padding: 12px;
               background: {t['seleccion']}; border-radius: 12px; }}
    """


def aplicar(app):
    """Aplica el tema que corresponda al modo de Windows. Devuelve los colores usados."""
    tema = tema_actual()
    app.setStyle("Fusion")  # Base neutra: el resto lo dibuja la hoja de estilo.
    app.setPalette(_paleta(tema))
    app.setStyleSheet(hoja_de_estilo(tema))
    return tema
