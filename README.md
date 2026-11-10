# Mouse Compartido

Un mouse y un teclado para dos PCs con Windows en la misma red. Llevás el cursor
al borde de la pantalla y pasás a la otra PC; volvés por el borde opuesto.
**Atajo de emergencia: `Ctrl+Alt+Esc`** devuelve el control a la PC principal
aunque se haya cortado la red.

Se maneja desde una ventana y desde un ícono al lado del reloj.

Vamos a llamar **PC principal** (o servidor) a la que tiene el mouse y el teclado
conectados, y **la otra PC** (o cliente) a la que recibe el control.

## Instalación paso a paso

Hacé los pasos 1, 2 y 4 en **las dos PCs**.

### 1. Instalar Python

1. Abrí `instaladores/python-3.12.10-amd64.exe`. Es el instalador oficial, incluido
   en este repositorio, y sirve para Windows de 64 bits en PCs Intel o AMD. También
   funciona Python 3.10 o más nuevo bajado de <https://www.python.org/downloads/>.
2. En el instalador, **tildá "Add python.exe to PATH"** antes de darle a Install.

### 2. Copiar el programa

Copiá la carpeta `mouse-compartido` a cada PC, en un lugar fijo (por ejemplo,
`Documentos`). **Tiene que ser exactamente la misma versión en las dos**: si una
tiene una versión vieja, la otra avisa "La otra PC tiene otra versión del programa".

### 3. Abrir el puerto en el Firewall (solo en la PC principal)

La PC principal es la que recibe la conexión, así que es la única que lo necesita.

1. Marcá tu red como privada, porque el Firewall es más estricto en las públicas.
   En Configuración → Red e Internet → Wi-Fi o Ethernet → Propiedades → elegí
   **Red privada**.
2. Abrí PowerShell **como Administrador** (clic derecho sobre PowerShell →
   "Ejecutar como administrador") y creá la regla (si cambiaste el puerto, poné el tuyo):

   ```
   netsh advfirewall firewall add rule name="Mouse Compartido" dir=in action=allow protocol=TCP localport=24850 profile=private
   ```

La primera vez que arranque, Windows puede mostrar un aviso del Firewall para
Python: **tocá "Permitir"**. Si lo cancelás, Windows crea un bloqueo que le gana a
la regla de arriba (ver "Si algo falla").

Para sacar la regla el día de mañana:

```
netsh advfirewall firewall delete rule name="Mouse Compartido"
```

### 4. Abrir y configurar

Abrí `iniciar.bat` con doble clic. Pide permiso de Administrador (para poder
controlar también ventanas como el Administrador de tareas) y, **solo la primera
vez**, instala la interfaz gráfica (PySide6): tarda un minuto y necesita internet.

La primera vez se abre en la página **Conexión**:

| Dato | PC principal | La otra PC |
|---|---|---|
| ¿Qué hace esta PC? | Tiene el mouse y el teclado | Recibe el control |
| PIN | El que elijas (8 caracteres o más) | **El mismo** |
| Puerto | 24850 | **El mismo** |
| IP de la PC con el mouse | No se pide | La que muestra la PC principal en Estado → Esta PC |

Tocá **Guardar cambios** y arranca solo. En la PC principal, andá a **Pantallas** y
arrastrá el rectángulo violeta al lado donde está la otra PC en tu escritorio.

## Cómo se usa

**La ventana** tiene seis páginas:

- **Estado:** si está conectado, con qué PC, dónde está el mouse ahora y la latencia.
  Botones Iniciar, Pausar y Detener, y abajo la actividad reciente.
- **Pantallas:** dónde está la otra PC (izquierda, derecha, arriba o abajo). Se elige
  arrastrando el rectángulo, como en la configuración de pantallas de Windows, o
  con los botones. Se cambia desde la PC principal; la otra lo copia sola.
- **Conexión:** qué hace esta PC, PIN, puerto e IP.
- **Atajos:** el de emergencia. Bloq Despl llega en la etapa 3.
- **Compartir:** carpeta compartida (la sincronización llega en la etapa 7).
- **General:** iniciar con Windows, conectar al abrir y ajustes finos.

Los cambios se guardan en `config.json` recién al tocar **Guardar cambios**. Si el
programa estaba conectado, se reconecta solo para aplicarlos.

**Cerrar la ventana no cierra el programa:** sigue en la bandeja, al lado del reloj
(si no lo ves, está en la flechita `^`). El color del ícono dice cómo está:

| Color | Significa |
|---|---|
| Gris | Detenido |
| Naranja | Esperando o buscando a la otra PC |
| Verde | Conectado. Con una flechita blanca: el mouse está en la otra PC |
| Violeta | En pausa: sigue conectado pero el mouse no cruza |
| Rojo | Hay un problema (pasá el mouse por encima para ver cuál) |

Click izquierdo abre la ventana. Click derecho: Iniciar, Pausar, Detener, Abrir
configuración y Cerrar Mouse Compartido (este sí lo cierra del todo).

**Pausa:** sirve para usar cada PC por separado un rato sin desconectar. Se puede
pausar desde cualquiera de las dos PCs, y si el mouse estaba en la otra, vuelve.

**Iniciar con Windows** (en General) crea una tarea en el Programador de tareas que
abre el programa en la bandeja cada vez que iniciás sesión, con permiso de
Administrador y sin preguntar. Para activarlo, el programa tiene que estar abierto
con `iniciar.bat`.

**La flechita del mouse** se esconde en la PC que no estás usando y aparece en la
que sí.

## Cómo probar la etapa 1

Antes de empezar: las dos PCs con esta misma versión, abiertas con `iniciar.bat`.

1. **Primera vez:** se abre en Conexión. Configurá cada PC como en el paso 4. Al
   guardar, el ícono pasa a naranja y después a verde, con un aviso "Conectado".
2. **Estado:** en las dos tiene que decir **Conectado** con el nombre de la otra PC.
   En la PC principal se ve la latencia.
3. **Pantallas:** en la PC principal, arrastrá el rectángulo violeta a otro lado,
   soltalo (se acomoda solo) y guardá. Probá cruzar por ese borde, también arriba o
   abajo. En la otra PC, la página Pantallas tiene que mostrar el mismo lado.
4. **La flechita:** cuando el mouse está en la otra PC, en la principal no se ve.
   Cuando vuelve a la principal, en la otra PC tampoco se tiene que ver. Si en
   la otra PC tocás su propio touchpad, la flechita aparece.
5. **Pausa:** Pausar desde la bandeja de cualquiera de las dos. El ícono se pone
   violeta en las dos y el mouse no cruza. Reanudar y vuelve a cruzar.
6. **Detener e Iniciar** desde la bandeja: el ícono pasa a gris y vuelve.
7. **Cerrar la ventana** con la X: el programa sigue (ícono en la bandeja). Abrir
   `iniciar.bat` otra vez trae la misma ventana, no abre otro programa.
8. **Inicio con Windows:** activalo en General, cerrá sesión y volvé a entrar. A
   los pocos segundos aparece el ícono, sin ventana, y se conecta solo.
9. Lo de siempre sigue andando: escribir (con `@` y acentos), clicks, rueda,
   `Alt+Tab` y `Ctrl+Alt+Esc`.

## Si algo falla

| Síntoma | Qué mirar |
|---|---|
| Ícono naranja que nunca pasa a verde | En la otra PC, corré en PowerShell `Test-NetConnection IP-DE-LA-PRINCIPAL -Port 24850`. Si `TcpTestSucceeded` da `False`: la principal no está iniciada, la IP está mal, el Firewall, o el Wi-Fi tiene "aislamiento de clientes" (típico de redes de invitados). |
| Abriste la regla y sigue sin conectar | Puede haber quedado un bloqueo para Python. En "Windows Defender Firewall con seguridad avanzada" → Reglas de entrada, borrá las reglas de `python` o `pythonw` marcadas con un círculo rojo. |
| Ícono rojo "PIN incorrecto" | Tiene que ser idéntico en las dos PCs, mayúsculas incluidas. |
| "La otra PC tiene otra versión del programa" | Copiá la misma carpeta en las dos. |
| No instala la interfaz | `iniciar.bat` necesita internet la primera vez. A mano, en PowerShell dentro de la carpeta: `python -m pip install -r requirements.txt` |
| No se puede controlar una ventana (Administrador de tareas, por ejemplo) | Abrí el programa con `iniciar.bat`, en las dos PCs. |
| "Iniciar con Windows" da error | Cerrá el programa (bandeja → Cerrar) y abrilo con `iniciar.bat`, que tiene permiso de Administrador. |
| El cursor se pone lento o va a tirones | Mirá la Actividad de las dos PCs justo después. "La red tardó X ms" quiere decir que es la red o el Wi-Fi (ver la fila siguiente). "El mouse se atrasó dentro de esta PC" o "esta PC tardó en mover el cursor" quiere decir que esa PC está muy ocupada: mirá el Administrador de tareas. En Estado, "Demora de la red" muestra el último tirón de los 30 segundos anteriores. |
| La red tarda (sobre todo con la notebook a batería) | A batería, Windows pone el Wi-Fi en ahorro de energía y los paquetes se demoran. En la notebook: Panel de control → Opciones de energía → Cambiar la configuración del plan → Cambiar la configuración avanzada → Configuración del adaptador inalámbrico → Modo de ahorro de energía → "Con batería": **Rendimiento máximo**. Si podés, usá cable en la PC principal. |
| Algunos símbolos (`@`, `ñ`, `¿`) salen distintos en la otra PC | Las letras salen según la distribución de teclado configurada en la PC que las recibe. Poné la misma en las dos: Configuración → Hora e idioma → Idioma y región → Español → Opciones de idioma → Teclados (por ejemplo, "Español" o "Latinoamericano", según lo que diga tu teclado). |
| Pasa a la otra PC sin querer | Subí "Esquinas sin paso" en Pantallas. |
| Quedó una tecla "apretada" | Cruzá a la otra PC y volvé: al cruzar se sueltan todas. |
| Se perdió el control de todo | `Ctrl+Alt+Esc`. Si tampoco responde, bandeja → Detener: al detenerse, Windows libera el mouse y el teclado. |

El menú de texto de la primera versión sigue estando: `iniciar.bat menu`.

## Limitaciones

- **`Ctrl+Alt+Supr` y `Win+L` siempre actúan en la PC física.** Windows no deja que
  ningún programa los intercepte.
- Las pantallas de bloqueo y los avisos de UAC de la otra PC no se pueden
  controlar: corren en un escritorio protegido. Hay que resolverlos con el teclado
  o el touchpad propios de esa PC.
- Se usa posición absoluta en la otra PC, así que los juegos de disparos en primera
  persona pueden no responder bien. Los juegos que usan el cursor normal (estrategia,
  rol, juegos 2D) andan bien, y si cambian la resolución de la pantalla el programa
  se adapta solo en un segundo.
- Algunos juegos con anti-trampas bloquean el teclado y el mouse simulados.
- **El tráfico todavía no va cifrado.** El PIN impide que otro se conecte, pero
  alguien en tu misma red con las herramientas adecuadas podría leer lo que tipeás.
  Usalo solo en una red de confianza. El cifrado está previsto para la etapa 2.

## Por qué está hecho así

**Dos programas en uno: el motor y la ventana.** Lo que mueve el mouse (el
"motor") corre en un proceso aparte, sin nada de interfaz gráfica. La ventana le
manda órdenes (pausar, detener) y recibe el estado por un canal de texto. Así,
aunque la ventana esté ocupada dibujando, el mouse no se entera: en Python dos
hilos del mismo proceso se turnan, pero dos procesos corren de verdad en paralelo.
Y si la ventana se cuelga o se cierra de golpe, el motor se cierra solo y suelta
el mouse.

**PySide6 para la interfaz.** Es la versión oficial de Qt para Python, gratuita
(licencia LGPL). Se eligió frente a CustomTkinter porque trae todo lo que pide este
proyecto sin librerías extra: ícono de bandeja con menú y avisos, un "lienzo" para
arrastrar los rectángulos de las pantallas con animación, modo oscuro que sigue a
Windows, y una forma de detectar que el programa ya está abierto. CustomTkinter es
más simple, pero para la bandeja hace falta otra librería con su propio hilo, y
para el editor de pantallas habría que dibujar todo a mano. Se instala solo
`PySide6-Essentials`, la parte básica de Qt, que pesa mucho menos que el paquete
completo.

**Python con la API de Windows directa (`ctypes`).** Medido en la PC de desarrollo,
un evento tarda unos 0,15 ms desde que se procesa hasta que llega a la otra PC, por
TCP real dentro de la misma máquina. Por cable, la red suma alrededor de 1 ms o
menos, y por Wi-Fi varios milisegundos. Un lenguaje compilado ahorraría parte de
esos 0,15 ms, algo imperceptible.

**TCP con `TCP_NODELAY`, una sola conexión.** Nagle (que junta mensajes chicos y los
demora) queda apagado, así que cada evento sale al instante. En una LAN sin pérdidas
UDP no es más rápido, y TCP garantiza dos cosas que importan: una tecla soltada nunca
se pierde (se quedaría trabada) y un click nunca se adelanta al movimiento anterior.

**Mensajes mínimos y relativos.** Un movimiento ocupa 7 bytes y solo dice cuánto se
movió el mouse, así que no importa si las pantallas tienen distinta resolución.

**El hilo del mouse nunca espera.** El envío no bloquea y todo se resuelve en
microsegundos: si tardara, Windows frenaría el mouse de toda la PC. También se limitan
los mensajes a 500 por segundo para no saturar el Wi-Fi con mouses de 1000 Hz.

**La flechita se esconde con una ventana invisible.** Una ventanita casi
transparente con un cursor vacío se pone debajo de la flechita. Es más seguro que
cambiar los cursores de Windows: si el programa se cierra de golpe, la ventana
desaparece y la flechita vuelve sola.

## Estructura del proyecto

```
mouse-compartido/
├── main.py                 Punto de entrada (ventana, menú de texto o motor)
├── iniciar.bat             Abre el programa como Administrador e instala lo que falte
├── requirements.txt        Lo único extra: PySide6 para la ventana
├── config.json             Tu configuración (se crea al guardar; no se sube a GitHub)
├── instaladores/           Instalador oficial de Python 3.12.10 (64 bits)
├── tests/                  Pruebas automáticas
└── mouse_compartido/
    ├── comun/              Lo que usan todos
    │   ├── config.py           Opciones y config.json
    │   ├── pantallas.py        Monitores, bordes y lados
    │   └── registro.py         Mensajes de actividad
    ├── red/                Comunicación entre las PCs
    │   ├── protocolo.py        Formato de los mensajes
    │   ├── conexion.py         TCP de baja latencia
    │   └── seguridad.py        Verificación del PIN
    ├── entrada/            Mouse y teclado
    │   ├── captura.py          Ganchos de Windows: captura y bloquea (PC principal)
    │   ├── logica_captura.py   Cuándo cruzar y qué mandar
    │   ├── inyeccion.py        Ejecuta los eventos con SendInput (otra PC)
    │   ├── logica_cliente.py   Posición del cursor y borde de regreso
    │   └── cursor.py           Esconde la flechita en la PC que no se usa
    ├── motor/              El proceso que mueve el mouse (sin interfaz)
    │   ├── servidor.py         PC principal
    │   ├── cliente.py          La otra PC
    │   ├── estado.py           Arma el estado que ve la ventana
    │   ├── proceso.py          Habla con la ventana por texto (JSON)
    │   └── menu.py             Menú de texto de la primera versión
    ├── sistema/            Windows
    │   ├── win32.py            Declaraciones de la API de Windows
    │   ├── autoinicio.py       Iniciar con Windows (Programador de tareas)
    │   └── rutas.py            Dónde está el programa y con qué Python abrirlo
    ├── ui/                 La ventana y la bandeja (PySide6)
    │   ├── app.py              Une ventana, bandeja y motor
    │   ├── ventana.py          Las seis páginas
    │   ├── editor_pantallas.py Rectángulos para arrastrar
    │   ├── bandeja.py          Ícono al lado del reloj
    │   ├── control_motor.py    Arranca y controla el motor
    │   ├── estilo.py           Colores y tipografía (claro y oscuro)
    │   ├── iconos.py           Ícono de cada estado
    │   ├── widgets.py          Tarjetas, interruptores y demás piezas
    │   ├── resumen.py          Traduce el estado a textos
    │   └── geometria.py        Cuentas del editor de pantallas
    └── funciones/          Lugar para lo que viene (portapapeles, archivos...)
```

Para correr las pruebas automáticas:

```
python -m unittest discover -s tests -t .
```

## Próximas etapas

En este orden, probando cada una antes de seguir:

1. ~~Interfaz, bandeja e inicio con Windows~~ (esta)
2. Las PCs se encuentran solas en la red, se reconectan solas y el tráfico va cifrado
3. Bloq Despl para cambiar de PC, con la luz del teclado como indicador
4. Portapapeles compartido (texto y después imágenes)
5. Volumen y teclas multimedia en la PC que estás usando
6. Arrastrar archivos de una PC a la otra
7. Carpeta compartida sincronizada

Al final: empaquetarlo en un `.exe` para instalarlo fácil.
