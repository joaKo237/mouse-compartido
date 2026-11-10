"""Cuentas del editor de pantallas: dónde quedó la otra PC al soltarla.

Sin Qt, para poder probarlas solas. Las cajas son tuplas (x, y, ancho, alto).
"""

from ..comun.pantallas import ABAJO, ARRIBA, DERECHA, IZQUIERDA


def lado_mas_cercano(caja_esta, centro_otra, tam_otra):
    """¿De qué lado de esta PC quedó la otra? Se decide por su centro.

    Las distancias se miden en "medias cajas": así un rectángulo ancho no
    queda siempre a los costados solo por ser ancho.
    """
    x, y, ancho, alto = caja_esta
    ancho_otra, alto_otra = tam_otra
    dx = (centro_otra[0] - (x + ancho / 2)) / max(1.0, (ancho + ancho_otra) / 2)
    dy = (centro_otra[1] - (y + alto / 2)) / max(1.0, (alto + alto_otra) / 2)
    if abs(dx) >= abs(dy):
        return DERECHA if dx > 0 else IZQUIERDA
    return ABAJO if dy > 0 else ARRIBA


def posicion_pegada(caja_esta, tam_otra, lado, separacion=0):
    """Esquina superior izquierda de la otra PC, pegada y centrada sobre ese lado."""
    x, y, ancho, alto = caja_esta
    ancho_otra, alto_otra = tam_otra
    if lado == DERECHA:
        return x + ancho + separacion, y + (alto - alto_otra) / 2
    if lado == IZQUIERDA:
        return x - separacion - ancho_otra, y + (alto - alto_otra) / 2
    if lado == ARRIBA:
        return x + (ancho - ancho_otra) / 2, y - separacion - alto_otra
    return x + (ancho - ancho_otra) / 2, y + alto + separacion


def escala_para(tam_vista, tam_esta, tam_otra, margen):
    """Escala que deja lugar para la otra PC en cualquiera de los cuatro lados."""
    ancho_vista, alto_vista = tam_vista
    ancho = tam_esta[0] + 2 * tam_otra[0]
    alto = tam_esta[1] + 2 * tam_otra[1]
    return max(0.01, min((ancho_vista - 2 * margen) / ancho, (alto_vista - 2 * margen) / alto))
