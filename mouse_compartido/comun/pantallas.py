"""Geometría de los monitores: bordes, conversión de posiciones y límites.

Con varios monitores, Windows arma un "escritorio virtual". El borde que importa
es el del extremo de ese escritorio. Este módulo no llama a Windows, solo hace
cuentas, y por eso se puede probar fácilmente.

La otra PC puede estar en cualquiera de los cuatro lados. Para no repetir cada
cuenta cuatro veces, se habla de la posición "a lo largo del borde": la altura
(y) en los bordes izquierdo y derecho, y la posición horizontal (x) en los de
arriba y abajo.
"""

from dataclasses import dataclass

IZQUIERDA = "izquierda"
DERECHA = "derecha"
ARRIBA = "arriba"
ABAJO = "abajo"
LADOS = (IZQUIERDA, DERECHA, ARRIBA, ABAJO)

_OPUESTO = {IZQUIERDA: DERECHA, DERECHA: IZQUIERDA, ARRIBA: ABAJO, ABAJO: ARRIBA}

# Al entrar a una pantalla el cursor queda unos píxeles adentro del borde,
# para que no cuente como "tocar el borde" y rebote.
MARGEN_ENTRADA = 2


def lado_opuesto(lado):
    return _OPUESTO[lado]


def es_lateral(lado):
    """True para izquierda y derecha, donde lo que importa es la altura del cursor."""
    return lado == IZQUIERDA or lado == DERECHA


@dataclass(frozen=True)
class Monitor:
    """Un rectángulo en píxeles. `der` y `abajo` son la primera posición fuera."""

    izq: int
    arriba: int
    der: int
    abajo: int

    @property
    def ancho(self):
        return self.der - self.izq

    @property
    def alto(self):
        return self.abajo - self.arriba

    @property
    def centro(self):
        return (self.izq + self.der) // 2, (self.arriba + self.abajo) // 2

    def acercar(self, x, y):
        """Devuelve el punto de este monitor más cercano a (x, y)."""
        return max(self.izq, min(x, self.der - 1)), max(self.arriba, min(y, self.abajo - 1))

    def como_lista(self):
        return [self.izq, self.arriba, self.der, self.abajo]


class Pantallas:
    def __init__(self, monitores):
        if not monitores:
            raise ValueError("Windows no informó ningún monitor")
        self.monitores = tuple(monitores)
        self.izq = min(m.izq for m in self.monitores)
        self.der = max(m.der for m in self.monitores)
        self.arriba = min(m.arriba for m in self.monitores)
        self.abajo = max(m.abajo for m in self.monitores)
        self.ancho = self.der - self.izq
        self.alto = self.abajo - self.arriba
        self._ultimo = self.monitores[0]
        self._rangos = {lado: self._rango(lado) for lado in LADOS}

    def _rango(self, lado):
        """Desde dónde hasta dónde llega el borde, contando solo los monitores que lo tocan."""
        if lado == DERECHA:
            tocan = [m for m in self.monitores if m.der == self.der]
        elif lado == IZQUIERDA:
            tocan = [m for m in self.monitores if m.izq == self.izq]
        elif lado == ARRIBA:
            tocan = [m for m in self.monitores if m.arriba == self.arriba]
        else:
            tocan = [m for m in self.monitores if m.abajo == self.abajo]
        if es_lateral(lado):
            return min(m.arriba for m in tocan), max(m.abajo for m in tocan)
        return min(m.izq for m in tocan), max(m.der for m in tocan)

    def rango_borde(self, lado):
        """Devuelve (desde, hasta) del tramo del escritorio que toca ese borde."""
        return self._rangos[lado]

    def toca_borde(self, lado, x, y, margen=0):
        """¿El cursor (que Windows nunca deja salir del escritorio) llegó a ese borde?

        `margen` deja sin efecto las puntas del borde (las "esquinas muertas"),
        para poder llegar a la X de una ventana maximizada sin pasar a la otra PC.
        """
        if lado == DERECHA:
            if x < self.der - 1:
                return False
            a_lo_largo = y
        elif lado == IZQUIERDA:
            if x > self.izq:
                return False
            a_lo_largo = y
        elif lado == ARRIBA:
            if y > self.arriba:
                return False
            a_lo_largo = x
        else:
            if y < self.abajo - 1:
                return False
            a_lo_largo = x
        desde, hasta = self._rangos[lado]
        return desde + margen <= a_lo_largo < hasta - margen

    def sale_por(self, lado, x, y):
        """¿El punto calculado quedó del otro lado de ese borde? (lo usa la PC controlada)."""
        if lado == IZQUIERDA:
            return x < self.izq
        if lado == DERECHA:
            return x >= self.der
        if lado == ARRIBA:
            return y < self.arriba
        return y >= self.abajo

    def ratio_en_borde(self, lado, x, y):
        """Convierte la posición a lo largo del borde en un valor relativo (0..65535).

        Se manda relativa para que las pantallas de distinta resolución se
        correspondan: la mitad de una es la mitad de la otra.
        """
        posicion = y if es_lateral(lado) else x
        desde, hasta = self._rangos[lado]
        recorrido = max(1, hasta - desde - 1)
        return (max(desde, min(posicion, hasta - 1)) - desde) * 65535 // recorrido

    def posicion_desde_ratio(self, lado, ratio):
        """Lo inverso de `ratio_en_borde`: la posición a lo largo del borde, en píxeles."""
        desde, hasta = self._rangos[lado]
        return desde + ratio * max(0, hasta - desde - 1) // 65535

    def punto_en_borde(self, lado, ratio):
        """Dónde aparece el cursor al entrar por ese borde: apenas adentro de la pantalla."""
        posicion = self.posicion_desde_ratio(lado, ratio)
        if lado == IZQUIERDA:
            punto = (self.izq + MARGEN_ENTRADA, posicion)
        elif lado == DERECHA:
            punto = (self.der - 1 - MARGEN_ENTRADA, posicion)
        elif lado == ARRIBA:
            punto = (posicion, self.arriba + MARGEN_ENTRADA)
        else:
            punto = (posicion, self.abajo - 1 - MARGEN_ENTRADA)
        return self.limitar(*punto)

    def monitor_de(self, x, y):
        """Devuelve el monitor que contiene el punto, o el más cercano."""
        ultimo = self._ultimo
        if ultimo.izq <= x < ultimo.der and ultimo.arriba <= y < ultimo.abajo:
            return ultimo
        mejor = None
        mejor_distancia = None
        for monitor in self.monitores:
            cx, cy = monitor.acercar(x, y)
            distancia = (cx - x) ** 2 + (cy - y) ** 2
            if mejor_distancia is None or distancia < mejor_distancia:
                mejor, mejor_distancia = monitor, distancia
        self._ultimo = mejor
        return mejor

    def limitar(self, x, y):
        """Ajusta un punto para que caiga dentro de algún monitor real."""
        return self.monitor_de(x, y).acercar(x, y)

    def como_lista(self):
        """Los monitores como listas simples, para mandarlos por la red o guardarlos."""
        return [m.como_lista() for m in self.monitores]


def desde_lista(lista):
    """Reconstruye Pantallas a partir de `como_lista()`. Devuelve None si no sirve."""
    try:
        monitores = [Monitor(*(int(v) for v in m)) for m in lista]
        if not monitores or any(m.ancho <= 0 or m.alto <= 0 for m in monitores):
            return None
        return Pantallas(monitores)
    except (TypeError, ValueError):
        return None
