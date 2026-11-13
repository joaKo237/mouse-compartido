# Mouse Compartido

Un mouse y un teclado para dos PCs con Windows. Llevás el cursor al borde de la
pantalla y pasás a la otra PC; volvés por el borde opuesto (o con la tecla Bloq
Despl). Además:

- **Copiar y pegar entre las PCs:** texto, imágenes y también **archivos y carpetas**
  (`Ctrl+C` en el Explorador de una, `Ctrl+V` en la otra).
- **Mandar archivos** a la otra PC con clic derecho → Enviar a → Mouse Compartido.
- **Una carpeta sincronizada:** igual en las dos PCs, sola.
- **Volumen y multimedia** sobre la PC que estás usando.

**Se emparejan una sola vez, como un auricular Bluetooth.** Después se encuentran
y se conectan solas cada vez que las prendés, **por cable o por Wi-Fi** (si están
conectadas de las dos formas, usa el cable, que es más rápido). Todo lo que viaja
entre las dos va **cifrado**.

**Atajo de emergencia: `Ctrl+Alt+Esc`** devuelve el control a la PC principal
aunque se haya cortado la red.

Es gratis y de código abierto. Vamos a llamar **PC principal** (o servidor) a la
que tiene el mouse y el teclado conectados, y **la otra PC** (o cliente) a la que
recibe el control.

## Instalación paso a paso

Hacé los pasos en **las dos PCs**.

### 1. Instalar Python

1. Abrí `instaladores/python-3.12.10-amd64.exe`. Es el instalador oficial, incluido
   en este repositorio, y sirve para Windows de 64 bits en PCs Intel o AMD. También
   funciona Python 3.10 o más nuevo bajado de <https://www.python.org/downloads/>.
2. En el instalador, **tildá "Add python.exe to PATH"** antes de darle a Install.

### 2. Copiar el programa

Copiá la carpeta `mouse-compartido` a cada PC, en un lugar fijo (por ejemplo,
`Documentos`). **Tiene que ser la misma versión en las dos**: en la lista de PCs
encontradas se avisa si la otra "tiene otra versión del programa".

### 3. Abrirlo

Abrí `iniciar.bat` con doble clic. Pide permiso de Administrador: con ese permiso
el programa puede controlar también ventanas como el Administrador de tareas y,
**la primera vez, abre solo el Firewall de Windows** para la red local (ver "Por
qué está hecho así"). Solo la primera vez instala además la interfaz gráfica
(PySide6): tarda un minuto y necesita internet.

### 4. Elegir qué hace cada PC y emparejarlas

La primera vez se abre en la página **Conexión**:

1. **¿Qué hace esta PC?** En la PC que tiene el mouse y el teclado, elegí "Tiene el
   mouse y el teclado"; en la otra, "Recibe el control". Tocá **Guardar cambios**.
   (Si te olvidás en una, al emparejar se elige sola la que falta.)
2. **Emparejar.** Con el programa abierto en las dos, en la lista **PCs encontradas
   en la red** de cualquiera de las dos aparece la otra. Tocá **Emparejar** al lado.
3. En las dos pantallas aparece **el mismo número de 6 cifras**. Si es igual, tocá
   **Coinciden** en las dos. Listo: desde ahora se conectan solas.

Por último, en la PC principal andá a **Pantallas** y arrastrá el rectángulo violeta
al lado donde está la otra PC en tu escritorio.

¿La otra PC no aparece en la lista? Abajo de la lista podés emparejar escribiendo
su IP (se ve en esa PC, en **Conexión → Avanzado**). Ver también "Si algo falla".

## Cómo se usa

**La ventana** tiene seis páginas:

- **Estado:** si está conectado, con qué PC y por dónde (cable o Wi-Fi), dónde está
  el mouse ahora y la demora de la red. Botones Iniciar, Pausar y Detener, y abajo
  la actividad reciente (lo que pasó, en palabras).
- **Pantallas:** dónde está la otra PC (izquierda, derecha, arriba o abajo). Se elige
  arrastrando el rectángulo, como en la configuración de pantallas de Windows, o
  con los botones. Se cambia desde la PC principal; la otra lo copia sola.
- **Conexión:** qué hace esta PC, la PC emparejada (con el botón **Olvidar**), las
  PCs que se ven en la red y opciones avanzadas (puerto, IP fija).
- **Atajos:** la tecla para cambiar de PC, la luz de Bloq Despl y las teclas de
  volumen.
- **Compartir:** portapapeles, archivos y carpeta sincronizada.
- **General:** iniciar con Windows, conectar al abrir y ajustes finos.

Los cambios se guardan recién al tocar **Guardar cambios**. Si el programa estaba
conectado, se reconecta solo para aplicarlos (tarda un segundo).

**Cerrar la ventana no cierra el programa:** sigue en la bandeja, al lado del reloj
(si no lo ves, está en la flechita `^`). El color del ícono dice cómo está:

| Color | Significa |
|---|---|
| Gris | Detenido |
| Naranja | Buscando a la otra PC |
| Verde | Conectado. Con una flechita blanca: el mouse está en la otra PC |
| Violeta | En pausa: sigue conectado pero el mouse no cruza |
| Rojo | Hay un problema (pasá el mouse por encima para ver cuál) |

Click izquierdo abre la ventana. Click derecho: Iniciar, Pausar, Detener, Abrir
configuración y Cerrar Mouse Compartido (este sí lo cierra del todo).

### Cambiar de PC

- **Por el borde:** llevás el cursor al borde donde está la otra PC.
- **Con una tecla:** `Bloq Despl` (Scroll Lock) te lleva a la otra PC y te trae de
  vuelta. Mientras estás en la otra, **la luz de Bloq Despl del teclado queda
  prendida**, así sabés dónde estás de un vistazo. Si tu teclado no tiene esa tecla,
  en **Atajos** podés elegir `Pausa`. Mientras las PCs están conectadas, esa tecla
  no le llega a ningún programa.
- **Emergencia:** `Ctrl+Alt+Esc` siempre vuelve a la PC principal.

**Pausa:** sirve para usar cada PC por separado un rato sin desconectar. Se puede
pausar desde cualquiera de las dos PCs, y si el mouse estaba en la otra, vuelve.

**La flechita del mouse** se esconde en la PC que no estás usando y aparece en la
que sí.

**Volumen y multimedia:** las teclas de volumen, silencio, play/pausa, siguiente y
anterior actúan sobre la PC que estás usando. Si preferís que actúen siempre sobre
la principal (por ejemplo, porque los parlantes están ahí), apagalo en **Atajos**.

### Copiar y pegar

Copiás (`Ctrl+C`) en una PC y pegás (`Ctrl+V`) en la otra, en los dos sentidos:

- **Texto e imágenes:** texto con o sin formato (negritas, links, tablas) e
  imágenes, como una captura hecha con `Win+Shift+S`. Llegan en el momento, así que
  cuando cruzás ya están listos para pegar.
- **Archivos y carpetas:** los copiás en el Explorador y los pegás en el Explorador
  (o en el escritorio) de la otra PC.
  - Si pesan **hasta 64 MB**, viajan enseguida.
  - Si pesan **más**, viajan recién cuando llevás el mouse a la otra PC: así, si
    copiaste una película para pegarla en la misma PC, no se manda al cuete.
  - Mientras pasan aparece una ventanita abajo a la derecha con el avance y un
    botón **Cancelar**. Cuando dice "Listo: ya podés pegarlo", pegá.
  - Hay un tope (4 GB, se cambia en **Compartir**) para no mandar algo enorme sin
    querer.

Lo que copia un administrador de contraseñas (KeePass, Bitwarden, etc.) no se
comparte. En **Actividad** queda anotado todo lo que pasa.

### Mandar archivos a propósito

Para mandar algo sin copiar y pegar (y sin tope de tamaño):

- **Clic derecho → Enviar a → Mouse Compartido (a la otra PC)** sobre cualquier
  archivo o carpeta. (En Windows 11, primero "Mostrar más opciones".)
- El botón **Mandar archivos a la otra PC…** en **Compartir**.
- Soltar archivos sobre la ventana del programa (esto no anda si el programa corre
  como Administrador: Windows no lo deja).

Llegan a **Descargas\Mouse Compartido** de la otra PC (se cambia en **Compartir**),
con un aviso al lado del reloj. Si ya existe un archivo con ese nombre, el nuevo se
guarda como "nombre (2)": nunca se pisa nada.

### Carpeta sincronizada

En **Compartir → Carpeta sincronizada**, elegí una carpeta en cada PC y activala en
las dos. Desde ahí se mantienen iguales: lo que agregás, cambiás o borrás en una
pasa a la otra, cada vez que estén conectadas.

- **Lo borrado va a la Papelera** de la otra PC, por si fue un error.
- Si cambiaste el mismo archivo en las dos PCs mientras estaban desconectadas, gana
  el más nuevo y el otro **no se pierde**: queda como "nombre (conflicto NOMBRE-PC
  fecha)".
- Si la carpeta de una PC aparece vacía de golpe (por ejemplo, un disco externo que
  no se conectó), por las dudas no se borra nada en la otra.

### Iniciar con Windows

En **General**. Crea una tarea en el Programador de tareas que abre el programa en
la bandeja cada vez que iniciás sesión, con permiso de Administrador y sin
preguntar. Para activarlo, el programa tiene que estar abierto con `iniciar.bat`.

## Cómo probar todo

Antes de empezar: las dos PCs con esta misma versión, abiertas con `iniciar.bat`.

**Emparejar y conectar**

1. En Conexión de cada PC, la otra aparece en **PCs encontradas en la red**, con
   "por cable" o "por Wi-Fi".
2. Emparejá desde una: el número tiene que ser el mismo en las dos. Tocá
   **Coinciden** en las dos. Se conectan solas (ícono verde y aviso "Conectado").
3. En Estado tiene que decir **Conectado con …, por cable** (o por Wi-Fi).
4. Cerrá el programa en las dos (bandeja → Cerrar) y volvé a abrirlo: se tienen que
   conectar solas, sin tocar nada.
5. **Cable y Wi-Fi:** con las dos conexiones, tiene que decir "por cable".
   Desenchufá el cable: en unos segundos se reconecta por Wi-Fi. Volvé a enchufarlo:
   cuando el mouse esté en la PC principal, se pasa solo al cable.
6. **Número que no coincide:** emparejá otra vez y tocá **No coinciden** en una: no
   se tiene que emparejar (y la conexión anterior sigue andando).

**El mouse y el teclado**

7. **Pantallas:** en la PC principal, arrastrá el rectángulo violeta a otro lado,
   soltalo y guardá. Probá cruzar por ese borde.
8. **Bloq Despl:** tocala; el mouse pasa a la otra PC y se prende la luz. Tocala
   otra vez: vuelve y se apaga la luz. Probá también elegir `Pausa` en Atajos.
9. **Volumen:** con el mouse en la otra PC, subí y bajá el volumen con el teclado:
   cambia en la otra PC. Apagalo en Atajos y probá de nuevo: cambia en la principal.
10. **Pausa, Detener e Iniciar** desde la bandeja de cualquiera de las dos.
11. Lo de siempre: escribir (con `@` y acentos), clicks, rueda, `Alt+Tab` y
    `Ctrl+Alt+Esc`.

**Copiar y pegar**

12. **Texto:** copiá en el Bloc de notas de una PC y pegá en el de la otra, en los dos
    sentidos.
13. **Imagen:** `Win+Shift+S`, recortá, cruzá y pegá en Paint o en un chat.
14. **Un archivo chico:** copiá una foto en el Explorador, cruzá y pegala en el
    escritorio de la otra PC.
15. **Algo grande** (más de 64 MB, por ejemplo un video): copialo. En Actividad dice
    que se pasa cuando lleves el mouse. Cruzá: aparece la ventanita de avance;
    cuando dice "Listo", pegá. Mientras pasa, el mouse tiene que andar normal.
16. **Cancelar:** copiá algo grande, cruzá y tocá Cancelar en la ventanita.

**Mandar archivos y carpeta**

17. **Enviar a:** clic derecho sobre un archivo → Enviar a → Mouse Compartido. En la
    otra PC aparece en Descargas\Mouse Compartido.
18. **Carpeta sincronizada:** activala en las dos con una carpeta vacía en cada una.
    Creá un archivo en una: aparece en la otra en unos segundos. Cambialo, renombralo
    y borralo (tiene que ir a la Papelera de la otra).

## Si algo falla

| Síntoma | Qué mirar |
|---|---|
| La otra PC no aparece en "PCs encontradas" | 1) Que el programa esté abierto en las dos. 2) Que estén en la misma red (el mismo router, o un cable entre las dos). 3) Que se haya abierto con `iniciar.bat` al menos una vez, para que se abra el Firewall: la Actividad dice "Firewall de Windows: se abrieron los puertos…" o por qué no pudo. 4) Algunas redes (de invitados, bares, oficinas) bloquean que las PCs se vean entre sí: probá emparejar escribiendo la IP, y si tampoco anda, la red no deja (usá un cable directo entre las dos). |
| Emparejadas, pero ícono naranja que nunca pasa a verde | En Conexión, la tarjeta "PC emparejada" dice si se la ve en la red y si hay algo raro (por ejemplo, las dos como "Tiene el mouse"). En la otra PC, en PowerShell: `Test-NetConnection IP-DE-LA-PRINCIPAL -Port 24850`. Si `TcpTestSucceeded` da `False`, es el Firewall o la red. |
| Se abrió el Firewall y sigue sin conectar | Puede haber quedado un bloqueo de una vez que se canceló el aviso del Firewall. En "Windows Defender Firewall con seguridad avanzada" → Reglas de entrada, borrá las reglas de `python` o `pythonw` marcadas con un círculo rojo. |
| "La otra PC no reconoce a esta" o "no acepta la clave de esta" | Una de las dos se emparejó con otra PC, o tocaste Olvidar en una. Emparejalas de nuevo desde Conexión. |
| Siempre va por Wi-Fi aunque haya cable | Fijate que el cable tenga IP en las dos PCs (`ipconfig` en PowerShell: tienen que aparecer en la misma red, por ejemplo 10.0.0.1 y 10.0.0.2). |
| "Tiene otra versión del programa" | Copiá la misma carpeta en las dos. |
| No instala la interfaz | `iniciar.bat` necesita internet la primera vez. A mano, en PowerShell dentro de la carpeta: `python -m pip install -r requirements.txt` |
| No se puede controlar una ventana (Administrador de tareas, por ejemplo) | Abrí el programa con `iniciar.bat`, en las dos PCs. |
| "Iniciar con Windows" da error | Cerrá el programa (bandeja → Cerrar) y abrilo con `iniciar.bat`, que tiene permiso de Administrador. |
| El cursor se pone lento o va a tirones | Mirá la Actividad de las dos PCs justo después. "La red tardó X ms" es la red o el Wi-Fi (ver la fila siguiente). "El mouse se atrasó dentro de esta PC" quiere decir que esa PC está muy ocupada: mirá el Administrador de tareas. |
| La red tarda (sobre todo con la notebook a batería) | A batería, Windows pone el Wi-Fi en ahorro de energía. En la notebook: Panel de control → Opciones de energía → Cambiar la configuración del plan → Cambiar la configuración avanzada → Configuración del adaptador inalámbrico → Modo de ahorro de energía → "Con batería": **Rendimiento máximo**. O mejor: un cable. |
| Algunos símbolos (`@`, `ñ`, `¿`) salen distintos en la otra PC | Las letras salen según la distribución de teclado de la PC que las recibe. Poné la misma en las dos: Configuración → Hora e idioma → Idioma y región → Español → Opciones de idioma → Teclados. |
| Copié algo y en la otra PC se pega lo anterior | Mirá la Actividad de la PC donde copiaste: si dice "No se pasó…", ahí está el motivo (una contraseña, demasiado grande). Con archivos grandes: ¿llevaste el mouse a la otra PC y esperaste el "Listo"? Revisá que en Compartir diga "Listo" en las dos. |
| No aparece "Mouse Compartido" en Enviar a | Se crea solo al abrir el programa, si "Archivos" está activado en Compartir. En Windows 11 está en "Mostrar más opciones". |
| La carpeta sincronizada dice "Esperando a la otra PC" | Activala también en la otra PC (cada una con su carpeta) y tocá Guardar cambios. |
| La luz de Bloq Despl queda prendida | Tocá Bloq Despl una vez con el mouse en la PC principal, o cerrá y abrí el programa: al cerrar la apaga. |
| Pasa a la otra PC sin querer | Subí "Esquinas sin paso" en Pantallas. |
| Quedó una tecla "apretada" | Cruzá a la otra PC y volvé: al cruzar se sueltan todas. |
| Se perdió el control de todo | `Ctrl+Alt+Esc`. Si tampoco responde, bandeja → Detener: al detenerse, Windows libera el mouse y el teclado. |

El menú de texto de la primera versión sigue estando: `iniciar.bat menu` (para
emparejar se usa la ventana).

## Limitaciones

- **`Ctrl+Alt+Supr` y `Win+L` siempre actúan en la PC física.** Windows no deja que
  ningún programa los intercepte.
- Las pantallas de bloqueo y los avisos de UAC de la otra PC no se pueden
  controlar: corren en un escritorio protegido. Hay que resolverlos con el teclado
  o el touchpad propios de esa PC.
- **No se puede arrastrar un archivo hasta el borde de la pantalla para pasarlo.**
  En Windows el arrastre lo maneja el programa de donde sale (el Explorador) y no
  hay forma confiable de "continuarlo" en otra PC: a veces andaría y a veces dejaría
  el arrastre trabado. Copiar y pegar hace lo mismo y siempre anda.
- Se usa posición absoluta en la otra PC, así que los juegos de disparos en primera
  persona pueden no responder bien. Los juegos que usan el cursor normal andan bien.
- Algunos juegos con anti-trampas bloquean el teclado y el mouse simulados.
- Funciona entre **dos** PCs. Para cambiar de pareja, Olvidar y emparejar la nueva.
- Las dos PCs tienen que estar en la misma red local (mismo router o cable directo).
  Por internet, de una casa a otra, no.

## Por qué está hecho así

**Dos programas en uno: el motor y la ventana.** Lo que mueve el mouse (el
"motor") corre en un proceso aparte, sin nada de interfaz gráfica. La ventana le
manda órdenes y recibe el estado por un canal de texto. Así, aunque la ventana esté
ocupada (dibujando, copiando un archivo de 2 GB), el mouse no se entera: en Python
dos hilos del mismo proceso se turnan, pero dos procesos corren de verdad en
paralelo. Y si la ventana se cierra de golpe, el motor se cierra solo y suelta el
mouse.

**Emparejar como el Bluetooth (comparación numérica).** Cada PC inventa un par de
claves y se mandan la parte pública (ECDH, curva P-256). Con eso las dos calculan
el mismo secreto sin que viaje por la red. Si alguien en la red se metiera en el
medio haciéndose pasar por cada una, el número de 6 cifras, que sale de las claves
de las dos, no coincidiría en las pantallas: por eso hay que mirarlo. Para que un
intruso no pueda probar millones de claves hasta acertar un número igual, la PC que
responde "se compromete" con su parte antes de ver la de la otra. Es el mismo método
que usan Bluetooth y muchas apps de mensajería. Reemplaza al PIN de la versión
anterior, que había que escribir igual en las dos y no protegía lo que viajaba.

**Todo va cifrado con AES-256-GCM.** Cada conexión saca claves nuevas de la clave
del emparejamiento, distintas para cada sentido. Cada mensaje lleva un sello: si
alguien lo cambiara en el camino, se nota y se corta. Se usa la criptografía que
trae Windows (la misma que usan sus propios programas), sin instalar nada: cifrar
un movimiento del mouse tarda unos 3 microsegundos.

**Se encuentran solas: avisos por la red local.** Cada 2 segundos, cada PC avisa
"acá estoy" a toda su red local (un mensaje UDP de difusión), **por cada placa de
red por separado**: si hay cable y Wi-Fi, avisa por los dos. Así cada PC sabe en qué
IPs ve a la otra y por qué camino. La otra PC queda identificada por su número de
emparejamiento, no por la IP: aunque el router le cambie la IP, la encuentra igual.

**Prefiere el cable.** De todas las IPs en que se ve a la otra PC, se prueba primero
la que va por cable. Si se conectó por Wi-Fi y después aparece el cable, se cambia
solo, pero solo cuando el mouse está en la PC principal (para no cortarte en el
medio de algo).

**El Firewall se abre solo, y solo para la red local.** Sin eso, Windows bloquea a
la otra PC. El programa agrega dos reglas ("Mouse Compartido (TCP)" para los puertos
24850 y 24851, y "(UDP)" para el 24851) que solo aceptan conexiones de tu red local,
no de internet. Necesita permiso de Administrador, por eso se abre con `iniciar.bat`.

**Python con la API de Windows directa (`ctypes`).** Medido en la PC de desarrollo,
un evento tarda unos 0,15 a 0,25 ms desde que se procesa hasta que llega a la otra
PC, con cifrado incluido. Por cable, la red suma alrededor de 1 ms o menos, y por
Wi-Fi varios milisegundos. Un lenguaje compilado ahorraría parte de esos 0,2 ms,
algo imperceptible.

**TCP con `TCP_NODELAY` para el mouse.** Cada evento sale al instante. En una LAN sin
pérdidas UDP no es más rápido, y TCP garantiza dos cosas que importan: una tecla
soltada nunca se pierde (se quedaría trabada) y un click nunca se adelanta al
movimiento anterior.

**El hilo del mouse nunca espera.** El envío no bloquea y todo se resuelve en
microsegundos: si tardara, Windows frenaría el mouse de toda la PC.

**Bloq Despl se "come".** Cuando las PCs están conectadas, el programa intercepta
esa tecla para que no le llegue a ningún programa (Excel la usa). La luz se maneja
aparte, apretando la tecla "de mentira" solo para prenderla o apagarla.

**El portapapeles y los archivos van por una segunda conexión, y la usa la
ventana.** TCP entrega todo en orden: si un archivo de 1 GB fuera por la conexión
del mouse, cada movimiento esperaría a que termine. Por eso van por otra conexión,
al mismo puerto. La abre el motor, que la verifica igual que la del mouse, y se la
pasa a la ventana (Windows permite pasar una conexión abierta de un proceso a otro).
Dentro de esa conexión, lo chico (texto copiado) pasa antes que los pedazos de los
archivos: copiar un texto no espera a que termine de pasar un video.

**Los archivos viajan en pedazos de 256 KB.** Así un archivo de 10 GB no llena la
memoria. El que recibe escribe en un archivo con nombre temporal (`.mcparcial`) y
recién al final le pone el nombre de verdad: si se corta a la mitad, no queda un
archivo roto con nombre de bueno. Las rutas que llegan se revisan: aunque la otra
PC esté emparejada, no puede escribir fuera de la carpeta que corresponde.

**La carpeta sincronizada compara tres versiones.** Para cada archivo mira cómo
está acá, cómo está en la otra PC y cómo estaba la última vez que estuvieron
iguales. Con eso sabe si algo se creó, se cambió o se borró, y de qué lado. Cada
PC solo **pide** lo que le falta (nunca se le "empuja" nada), así nunca pisa algo
que se está escribiendo.

**No rebota.** Lo que llega de la otra PC se pone en el portapapeles con una marca
invisible. Cuando Windows avisa "cambió el portapapeles", la marca dice que fue este
programa y no se devuelve.

## Estructura del proyecto

```
mouse-compartido/
├── main.py                 Punto de entrada (ventana, menú de texto, motor o "enviar")
├── iniciar.bat             Abre el programa como Administrador e instala lo que falte
├── requirements.txt        Lo único extra: PySide6 para la ventana
├── config.json             Tu configuración (se crea sola; no se sube a GitHub)
├── carpeta-estado.json     Lo que recuerda la carpeta sincronizada (se crea solo)
├── instaladores/           Instalador oficial de Python 3.12.10 (64 bits)
├── tests/                  Pruebas automáticas
└── mouse_compartido/
    ├── comun/              Lo que usan todos
    │   ├── config.py           Opciones y config.json
    │   ├── pantallas.py        Monitores, bordes y lados
    │   └── registro.py         Mensajes de actividad
    ├── red/                Comunicación entre las PCs
    │   ├── protocolo.py        Formato de los mensajes
    │   ├── conexion.py         TCP de baja latencia (mouse y teclado), cifrado
    │   ├── canal_datos.py      La segunda conexión (portapapeles y archivos)
    │   ├── seguridad.py        El saludo: verifica la PC emparejada y arma las claves
    │   ├── emparejamiento.py   Emparejar una vez, con el número de 6 cifras
    │   └── descubrimiento.py   Avisos "acá estoy" para encontrarse solas
    ├── datos/              Lo que viaja por el canal de datos
    │   ├── portapapeles.py     Formatos del portapapeles (texto, HTML, RTF, PNG)
    │   ├── transferencias.py   Archivos en pedazos, con avance y cancelación
    │   └── carpeta.py          La carpeta sincronizada
    ├── entrada/            Mouse y teclado
    │   ├── captura.py          Ganchos de Windows: captura y bloquea (PC principal)
    │   ├── logica_captura.py   Cuándo cruzar, Bloq Despl, multimedia
    │   ├── inyeccion.py        Ejecuta los eventos con SendInput (otra PC)
    │   ├── logica_cliente.py   Posición del cursor y borde de regreso
    │   └── cursor.py           Esconde la flechita en la PC que no se usa
    ├── motor/              El proceso que mueve el mouse (sin interfaz)
    │   ├── servidor.py         PC principal
    │   ├── cliente.py          La otra PC (prueba cada IP, cable primero)
    │   ├── estado.py           Arma el estado que ve la ventana
    │   ├── proceso.py          Habla con la ventana por texto (JSON)
    │   └── menu.py             Menú de texto de la primera versión
    ├── sistema/            Windows
    │   ├── win32.py            Declaraciones de la API de Windows
    │   ├── cripto.py           Cifrado y claves (con la criptografía de Windows)
    │   ├── redes.py            Placas de red: cuál es cable y cuál Wi-Fi
    │   ├── firewall.py         Abre los puertos para la red local
    │   ├── enviar_a.py         El acceso de clic derecho → Enviar a
    │   ├── papelera.py         Mandar a la Papelera
    │   ├── autoinicio.py       Iniciar con Windows (Programador de tareas)
    │   ├── portapapeles.py     Escribe en el portapapeles de Windows
    │   └── rutas.py            Dónde está el programa y con qué Python abrirlo
    └── ui/                 La ventana y la bandeja (PySide6)
        ├── app.py              Une todo: ventana, bandeja, motor, red y archivos
        ├── ventana.py          Las seis páginas
        ├── emparejar.py        Encontrar PCs y la ventanita del número
        ├── enlace.py           El canal de datos del lado de la ventana
        ├── portapapeles.py     Portapapeles compartido (lee, manda y pega)
        ├── archivos.py         Copiar y pegar archivos, mandar, carpeta
        ├── progreso.py         La ventanita de avance de los archivos
        ├── instancia.py        Una sola copia abierta (y el "Enviar a")
        ├── editor_pantallas.py Rectángulos para arrastrar
        ├── bandeja.py          Ícono al lado del reloj
        ├── control_motor.py    Arranca y controla el motor
        ├── estilo.py           Colores y tipografía (claro y oscuro)
        ├── iconos.py           Ícono de cada estado
        ├── widgets.py          Tarjetas, interruptores y demás piezas
        ├── resumen.py          Traduce el estado a textos
        └── geometria.py        Cuentas del editor de pantallas
```

Para correr las pruebas automáticas:

```
python -m unittest discover -s tests -t .
```

## Desinstalar

1. Bandeja → Cerrar Mouse Compartido. Si estaba "Iniciar con Windows", apagalo
   antes en General.
2. Borrá la carpeta del programa.
3. Borrá el acceso de Enviar a: en el Explorador escribí `shell:sendto` en la barra
   de direcciones y borrá "Mouse Compartido (a la otra PC)".
4. Las reglas del Firewall, en PowerShell como Administrador:

   ```
   netsh advfirewall firewall delete rule name="Mouse Compartido (TCP)"
   netsh advfirewall firewall delete rule name="Mouse Compartido (UDP)"
   ```

   Si habías creado a mano la regla de la versión anterior, también:
   `netsh advfirewall firewall delete rule name="Mouse Compartido"`

## Lo que falta

Empaquetarlo en un instalador (`.exe`) para que no haga falta instalar Python.
