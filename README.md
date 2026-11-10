# Mouse Compartido

Un mouse y un teclado para dos PCs con Windows en la misma red. Llevás el cursor
al borde de la pantalla y pasás a la otra PC; volvés por el borde opuesto.
**Atajo de emergencia: `Ctrl+Alt+Esc`** devuelve el control a la PC principal
aunque se haya cortado la red.

No necesita instalar librerías: solo Python.

## Instalación paso a paso

Hacé los pasos 1 y 2 en **las dos PCs**. Vamos a llamar **servidor** a la PC que
tiene el mouse y el teclado, y **cliente** a la otra.

### 1. Instalar Python

1. Abrí `instaladores/python-3.12.10-amd64.exe`. Es el instalador oficial, incluido
   en este repositorio, y sirve para Windows de 64 bits en PCs Intel o AMD. También
   funciona Python 3.10 o más nuevo bajado de <https://www.python.org/downloads/>.
2. En el instalador, **tildá "Add python.exe to PATH"** antes de darle a Install.
3. Abrí PowerShell (tecla Windows, escribí `powershell`, Enter) y verificá:

   ```
   python --version
   ```

### 2. Copiar el programa

Copiá la carpeta `mouse-compartido` a cada PC, en un lugar fijo (por ejemplo,
`Documentos`). Tiene que ser exactamente la misma versión en las dos.

### 3. Averiguar la IP del servidor

En el **servidor**, en PowerShell:

```
ipconfig
```

Buscá el adaptador que estés usando ("Wi-Fi" o "Ethernet") y anotá la
**Dirección IPv4**: suele tener la forma `192.168.x.y`. Ignorá los adaptadores
`vEthernet`, `VirtualBox` o `VMware`.

También la podés ver con la opción "Ver IP, monitores y estado" del menú.

La IP puede cambiar al reiniciar el router. Si te pasa seguido, reservá una IP
fija para esa PC en la configuración del router.

### 4. Abrir el puerto en el Firewall

Solo hace falta en el **servidor**, que es el que recibe la conexión.

1. Abrí PowerShell **como Administrador** (clic derecho sobre PowerShell →
   "Ejecutar como administrador").
2. Marcá tu red como privada, porque el Firewall es más estricto en las públicas.
   En Configuración → Red e Internet → Wi-Fi o Ethernet → Propiedades → elegí
   **Red privada**.
3. Creá la regla (si cambiaste el puerto, poné el tuyo):

   ```
   netsh advfirewall firewall add rule name="Mouse Compartido" dir=in action=allow protocol=TCP localport=24850 profile=private
   ```

La primera vez que arranques el servidor, Windows puede mostrar un aviso del
Firewall para Python: **tocá "Permitir"**. Si lo cancelás, Windows crea un bloqueo
para Python que le gana a la regla de arriba (ver "Si algo falla").

Para sacar la regla el día de mañana:

```
netsh advfirewall firewall delete rule name="Mouse Compartido"
```

### 5. Configurar

Abrí `iniciar.bat` con doble clic (te va a pedir permiso de Administrador). En el
menú elegí **Configurar**:

| Dato | Servidor | Cliente |
|---|---|---|
| PIN | El que elijas (8 caracteres o más) | **El mismo** |
| Puerto | 24850 | **El mismo** |
| IP del servidor | Dejalo vacío | La IP del paso 3 |
| Lado de la otra pantalla | Donde esté físicamente el cliente | No se usa |

### 6. Primera prueba, en una sola PC

En el servidor, elegí **Probar en esta sola PC**. Llevá el cursor al borde que
configuraste. Deberías ver que:

- El cursor desaparece y queda bloqueado, y no se escribe nada en esta PC.
- La ventana muestra `[simulado]` con lo que hacés.
- Recuperás el control moviendo el mouse hacia el lado opuesto hasta el final de
  la pantalla simulada, o con `Ctrl+Alt+Esc`. Por seguridad, a los 30 segundos
  vuelve solo.

### 7. Usarlo con las dos PCs

1. En el **servidor**: `iniciar.bat` → **Iniciar como SERVIDOR**.
2. En el **cliente**: `iniciar.bat` → **Iniciar como CLIENTE**.
3. Cuando aparezca "Cliente conectado", llevá el cursor al borde.

Lista de cosas para probar: mover, click izquierdo y derecho, rueda, arrastrar,
escribir (incluí `@` y acentos), `Ctrl+C` / `Ctrl+V`, `Alt+Tab`, la tecla Windows,
volver por el borde y `Ctrl+Alt+Esc`.

Cada 10 segundos el servidor muestra la latencia de red medida.

## Si algo falla

| Síntoma | Qué mirar |
|---|---|
| El cliente repite "no puedo conectar" | En el cliente, corré `Test-NetConnection IP-DEL-SERVIDOR -Port 24850`. Si `TcpTestSucceeded` da `False`: servidor sin arrancar, IP equivocada, Firewall, o el Wi-Fi tiene "aislamiento de clientes" (típico de redes de invitados). |
| Abriste la regla y sigue sin conectar | Puede haber quedado un bloqueo para Python. En "Windows Defender Firewall con seguridad avanzada" → Reglas de entrada, borrá las reglas de `python` marcadas con un círculo rojo. |
| "PIN incorrecto" | Tiene que ser idéntico en las dos PCs, mayúsculas incluidas. |
| No se puede controlar una ventana (Administrador de tareas, por ejemplo) | Arrancá con `iniciar.bat`, en las dos PCs. |
| El cursor salta o va a tirones por Wi-Fi | Probá con cable. En la notebook, enchufala y poné el adaptador Wi-Fi en máximo rendimiento: el ahorro de energía del Wi-Fi puede demorar los paquetes decenas de milisegundos. |
| Pasa a la otra PC sin querer | Subí `esquinas_muertas_px` en `config.json`. |
| Quedó una tecla "apretada" | Cruzá a la otra PC y volvé: al cruzar se sueltan todas. |
| Se perdió el control de todo | `Ctrl+Alt+Esc`. Si tampoco responde, cerrá la ventana del programa: al cerrarse, Windows libera el mouse y el teclado. |

## Limitaciones de esta etapa

- **`Ctrl+Alt+Supr` y `Win+L` siempre actúan en la PC física.** Windows no deja que
  ningún programa los intercepte.
- Las pantallas de bloqueo y los avisos de UAC del cliente no se pueden controlar:
  corren en un escritorio protegido. Hay que resolverlos con el teclado o el
  touchpad propios de esa PC.
- Se usa posición absoluta en el cliente, así que los juegos de disparos en primera
  persona pueden no responder bien.
- **El tráfico no va cifrado.** El PIN impide que otro se conecte, pero alguien
  con acceso a tu misma red y las herramientas adecuadas podría leer lo que tipeás.
  Usalo solo en una red de confianza, no en Wi-Fi públicos.

## Por qué está hecho así

**Python con la API de Windows directa (`ctypes`).** Medido en la PC de desarrollo,
un evento tarda unos 0,14 ms desde que se procesa hasta que llega al cliente, por
TCP real dentro de la misma máquina. Por cable, la red suma alrededor de 1 ms o
menos, y por Wi-Fi varios milisegundos. Un lenguaje compilado ahorraría parte de
esos 0,14 ms, algo imperceptible. No usa `pynput` porque hacía falta controlar
exactamente qué se bloquea, y con `ctypes` no hay nada extra para instalar en cada PC.
Si alguna vez hiciera falta más velocidad, solo habría que reescribir la captura.

**TCP con `TCP_NODELAY`, una sola conexión.** Nagle (que junta mensajes chicos y los
demora) queda apagado, así que cada evento sale al instante. En una LAN sin pérdidas
UDP no es más rápido, y TCP garantiza dos cosas que importan: una tecla soltada nunca
se pierde (se quedaría trabada) y un click nunca se adelanta al movimiento anterior.

**Mensajes mínimos y relativos.** Un movimiento ocupa 7 bytes y solo dice cuánto se
movió el mouse, así que no importa si las pantallas tienen distinta resolución. El
cliente calcula la posición y la aplica en absoluto, para no sumar la aceleración de
Windows dos veces.

**El hilo del mouse nunca espera.** El envío no bloquea y todo se resuelve en
microsegundos: si tardara, Windows frenaría el mouse de toda la PC. También se limitan
los mensajes a 500 por segundo para no saturar el Wi-Fi con mouses de 1000 Hz.

## Estructura del proyecto

```
mouse-compartido/
├── main.py                  Punto de entrada
├── iniciar.bat              Abre el programa como Administrador
├── config.json              Tu configuración (se crea al guardar)
├── instaladores/            Instalador oficial de Python 3.12.10 (64 bits)
├── tests/                   Pruebas automáticas
└── mouse_compartido/
    ├── menu.py              Menú y arranque de cada modo
    ├── config.py            Lectura y guardado de opciones
    ├── servidor.py          Espera al cliente y atiende la red
    ├── captura.py           Ganchos de Windows: captura y bloquea
    ├── logica_captura.py    Cuándo cruzar y qué mandar
    ├── cliente.py           Se conecta y recibe eventos
    ├── logica_cliente.py    Posición del cursor y borde de regreso
    ├── inyeccion.py         Ejecuta los eventos (SendInput)
    ├── protocolo.py         Formato de los mensajes
    ├── conexion.py          TCP de baja latencia
    ├── seguridad.py         Verificación del PIN
    ├── pantallas.py         Geometría de los monitores
    ├── win32.py             Declaraciones de la API de Windows
    ├── registro.py          Mensajes por consola
    └── funciones/           Punto de extensión para lo que venga
```

Para correr las pruebas automáticas:

```
python -m unittest discover -s tests -t .
```

## Próximas etapas

El código ya quedó preparado para:

- **Portapapeles:** el tipo de mensaje está reservado en `protocolo.py`. Se crea una
  clase en `funciones/` (ahí mismo está explicado cómo).
- **Archivos:** tipos reservados y un `CANAL_DATOS` previsto en el saludo, para que
  una transferencia vaya por otra conexión y no demore el mouse.
- **Más opciones de menú:** alcanza con una línea en la lista `OPCIONES` de `menu.py`.
