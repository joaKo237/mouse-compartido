"""Geometría de los monitores: bordes, conversión de alturas y límites.

Con varios monitores, Windows arma un "escritorio virtual". El borde que importa
es el del extremo de ese escritorio. Este módulo no llama a Windows, solo hace
cuentas, y por eso se puede probar fácilmente.
"""

from dataclasses import dataclass

IZQUIERDA = "izquierda"
DERECHA = "derecha"

# Al entrar a una pantalla el cursor queda unos píxeles adentro del borde,
# para que no cuente como "tocar el borde" y rebote.
MARGEN_ENTRADA = 2


def lado_opuesto(lado):
    return IZQUIERDA if lado == DERECHA else DERECHA


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
        self._rangos = {IZQUIERDA: self._rango(IZQUIERDA), DERECHA: self._rango(DERECHA)}

    def _rango(self, lado):
        if lado == DERECHA:
            tocan = [m for m in self.monitores if m.der == self.der]
        else:
            tocan = [m for m in self.monitores if m.izq == self.izq]
        return min(m.arriba for m in tocan), max(m.abajo for m in tocan)

    def rango_borde(self, lado):
        """Devuelve (arriba, abajo) de la parte del escritorio que toca ese borde."""
        return self._rangos[lado]

    def ratio_en_borde(self, lado, y):
        """Convierte una altura en píxeles a una altura relativa (0..65535).

        Se manda relativa para que las pantallas de distinta resolución se
        correspondan: la mitad de una es la mitad de la otra.
        """
        arriba, abajo = self._rangos[lado]
        recorrido = max(1, abajo - arriba - 1)
        return (max(arriba, min(y, abajo - 1)) - arriba) * 65535 // recorrido

    def y_desde_ratio(self, lado, ratio):
        arriba, abajo = self._rangos[lado]
        return arriba + ratio * max(0, abajo - arriba - 1) // 65535

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
