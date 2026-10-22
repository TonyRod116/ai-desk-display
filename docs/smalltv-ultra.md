# SmallTV Ultra y diseños de cuota restante

Esta adaptación añade el firmware original **SmallTV-Ultra Ultra-V9.0.50**.
Se comprobó en una unidad real: dos subidas de imagen, descarga con el mismo
contenido, selección del álbum y restauración del tema anterior.
No necesita instalar otro firmware.

El monitor lee los datos locales de cuota y envía las imágenes al reloj si han
cambiado. Lectores separados consultan las cuotas de Codex y Claude aproximadamente
cada minuto con sus clientes oficiales, según la autorización de the user.
El monitor no consulta proveedores ni abre credenciales.
Debe permanecer encendido y conectado a la misma red para actualizar la imagen.

## Diseños

- **Game Boy verde:** verde oliva y verde oscuro, el diseño inicial.
- **Game Boy gris:** la variante Pocket en dos tonos grises.
- **Terminal Ámbar:** pantalla ámbar con tipografía de terminal y barras de reserva.
- **Orbit:** medidores circulares, con un color para cada proveedor.
- Los seis diseños originales, incluido **Pixel Retro**, siguen disponibles.

En el reloj se muestra Codex primero y Claude después. Los diseños Game Boy de
dos cuentas usan un contador de reinicio de 16 píxeles para facilitar su lectura.

Las cinco pantallas personales muestran corazones pequeños que cuentan **resets
guardados disponibles**: uno lleno significa un reset listo para usar. No llevan
un número detrás. Tres corazones llenos con `+` indican más de tres; `?` significa
saldo desconocido. La barra representa cuota restante, independiente de los
corazones. Una renovación normal de cuota no añade resets guardados.

Game Boy y Pocket conservan su barra inferior. Pixel Retro mantiene los paisajes
del repo, muestra reserva restante y agranda el contador. Terminal Ámbar y Orbit
son dos diseños propios. Todos mantienen Codex primero y Claude después.

Las cinco pantallas personales muestran **porcentaje semanal restante** de Claude
y Codex. El porcentaje, la barra y la cuenta atrás usan siempre la misma ventana
semanal: si has consumido el 95 % del límite de cinco horas y el 20 % del semanal,
se muestra **80 % restante del semanal**, junto con su reinicio semanal. El límite
corto se conserva en el desplegable del panel. Una semana ausente queda desconocida;
no se sustituye por el porcentaje o la fecha del límite de cinco horas.

**Líneas de la sesión de 5 horas (Claude).** La semana puede sobrar mientras la
sesión de 5 horas está casi agotada, y la sesión es la que corta el trabajo
primero. Por eso, bajo la barra semanal de Claude hay **dos barras pegadas**, más
pequeñas que la semanal (3 px cada una), con las 5 horas de la sesión en **5
tramos de una hora**:

- **Barra de arriba: la cuota que te queda.** Toda la línea es el 100 %, como la
  barra semanal de arriba. Se mueve en pasos de 5 %.
- **Barra de abajo: el tiempo que queda** hasta que se renueve la sesión. Si
  termina a la mitad del segundo tramo, quedan unas **1 h 30**. Se mueve en
  cuartos de hora, así la imagen cambia como mucho cuatro veces por hora y no se
  reescribe la memoria del reloj cada minuto.
- **Comparación:** si la barra de abajo es **más larga** que la de arriba, la
  cuota se acabará antes de que la sesión se renueve.

Son dos filas separadas y nunca se dibujan una encima de otra: una primera versión
con una marca de tiempo dentro de la barra se camuflaba justo cuando sobraba cuota.

El número grande sigue siendo el semanal y no cambia nada más. Las barras solo se
dibujan con una lectura oficial fresca y con fecha de renovación futura: con la
sesión desconocida, caducada o antigua **no hay barras** (nunca se confunde con
"vacía") y no aparecen para Codex. Van bajo la barra semanal en Game Boy y Ámbar,
bajo la tarjeta en "Pixel Retro" y bajo el texto en Orbit. Tamaños: juzgarlos en
el aparato, no ampliados; las versiones anteriores (puntos de 2 px y una raya de
1 px) no se veían bien en la pantalla real de 1,5 pulgadas.
No es una estimación de mensajes disponibles. Las cuotas pueden cambiar según el
proveedor. Un dato ausente es `--`. Las lecturas oficiales de ambos proveedores
caducan a los tres minutos: desaparecen porcentaje y cuenta atrás hasta recibir
una observación nueva. El panel aplica esa caducidad también a su última respuesta;
si pierde el servidor o la petición se queda colgada, oculta las cifras oficiales
hasta recuperar la lectura. Las peticiones de cuota local tienen un plazo de cuatro
segundos. Las otras
fuentes antiguas conservan la marca `OLD` mientras sus límites sigan vigentes.

El selector **Aspecto del panel** incluye los cinco diseños personales, con los
mismos nombres y porcentaje **restante** que el reloj. Los otros aspectos web y
los diseños originales salvo Pixel Retro muestran porcentaje **consumido**.
En el panel puedes desplegar las otras ventanas. Para cambiar la imagen física,
abre **Diseños del reloj**, pulsa **Previsualizar** y después **Aplicar al reloj**.
Cambiar solo el aspecto de la web conserva el diseño elegido para el reloj.

El **álbum del reloj** es otra página: su dirección acaba en `/image.html`.
Con `display_album_faces: true` se publican allí `Game Boy verde.jpg`,
`Game Boy gris.jpg`, `Pixel Retro.jpg`, `Terminal Ambar.jpg` y `Orbit.jpg`.
Usa **Set** junto al archivo para verlo. Los nombres se mantienen en ASCII para
compatibilidad con el firmware. Se actualizan con datos reales igual que la imagen
principal; no son muestras estáticas. Las fotos anteriores se conservan.
Los refrescos normales no fuerzan otra selección. Aplicar un diseño desde el panel
del ordenador sí lo selecciona; el arranque del servicio selecciona el configurado.

Claude web no escribe los metadatos del capturador de Claude Code. Por eso la
instalación usa ahora un lector oficial separado para su cuota, también cuando
the user trabaja solo en la web. Un dato ausente sigue siendo `--`; una lectura
anterior nunca se presenta como un reset o una cuota renovada.

## Actualización automática de la imagen

El servicio local dibuja un JPG de 240 × 240 con Pillow: coloca nombres, números,
barras y corazones según los datos disponibles. No necesita una conversación
abierta, generar imágenes con IA ni tener el navegador abierto.

La cuota y los resets guardados de Codex se leen juntos cada **60 segundos**;
Claude se consulta también aproximadamente cada **60 segundos**. Cada observación oficial solicita una
actualización de las cinco imágenes, aunque los corazones no cambien. El monitor
lee además las cachés cada minuto por si se pierde ese aviso. Elegir otro diseño
o guardar un saldo manual también actualiza la imagen.
Se compara el contenido antes de enviarlo: una imagen idéntica no vuelve a
escribirse en el reloj. Cada subida Ultra se verifica descargando el JPG almacenado;
si no coincide o falla la conexión, no se registra éxito y se reintenta en otro ciclo.
El ordenador y el servicio deben seguir funcionando.

El panel pide el estado del reloj cada **5 segundos** cuando la vista previa está
abierta, y refresca esa imagen como máximo cada 30 segundos salvo cambios de diseño.
Esto no implica una subida al reloj cada cinco segundos. Si apagas el ordenador,
el reloj mantiene la última imagen recibida y su alternancia nativa con la hora.

## Conexión y restauración

La instalación alterna cada **30 segundos** entre la imagen de cuotas y el tema
original de hora y tiempo. Es la rotación nativa del reloj: funciona incluso si
el ordenador se apaga, aunque en ese caso las cuotas dejan de actualizarse.
Cambiar el diseño en el panel mantiene la alternancia.

El ajuste local `display_rotation_seconds` controla la duración de cada pantalla:
`0` deja únicamente las cuotas y un entero entre `10` y `3600` activa la rotación.
Se aplica al reiniciar Token TV. La copia de la configuración original se conserva
para restaurar los ajustes exactos anteriores a la instalación.

La API Ultra usa `/v.json`, `/app.json`, `/album.json`, `/theme_list.json`,
`/doUpload?dir=/image/` y `/set`. Se detecta después del 404 de la API SD_PRO.
Solo se admite la identidad `SmallTV-Ultra`; no se supone que otro modelo funcione.

Antes del primer envío se guardan el tema, los ajustes de reproducción y la
rotación de temas en el directorio local de estado de Token TV. Si el reloj ya
está en modo álbum, la primera captura se rechaza porque este firmware no informa
de la foto seleccionada: elige primero un tema de reloj en su web.
No se borran fotos para hacer espacio. Token TV reserva `tokentv.jpg`, `tokentv.gif`
y los cinco nombres del álbum indicados arriba para sus imágenes.

Para volver al tema original, detén primero el proceso que actualiza la pantalla:

```bash
systemctl --user stop token-tv
.venv/bin/token-tv run --restore-display
```

Para volver a actualizarla:

```bash
systemctl --user start token-tv
```

El panel escucha solo en `http://127.0.0.1:8787`. La configuración y las lecturas
reales viven fuera del repositorio, en `~/.config/token-tv/`. No se incluyen
sesiones, correos de proveedores, IP del reloj ni lecturas reales en commits.

Si hay varias cuentas, el campo privado `email` fija cuál debe aparecer. Los dos
lectores lo comparan con la sesión oficial en cada observación; Codex vuelve a
comprobarlo después de consultar y Claude comprueba también la identidad del dato
guardado por su cliente. Las cachés y los corazones se vinculan al directorio y a
esa identidad mediante un resumen SHA256, sin incluir el correo en las lecturas.
Cambiar de cuenta no reutiliza porcentajes ni saldos anteriores. Una caché previa
sin identidad fijada se rechaza hasta recibir una lectura nueva. Un saldo manual
antiguo tampoco se asigna automáticamente a la nueva identidad: queda en `?`.

El código, el servicio y su historial Git permanecen en este ordenador. El panel
rechaza dominios ajenos y no puede incrustarse en otras webs; las peticiones de
imagen al reloj rechazan redirecciones y proxies. No hay hosting ni telemetría
añadida por esta adaptación. `local_only: true` evita consultas de cuota y
activa una protección del programa que rechaza conexiones exteriores, ejecución
de procesos y apertura de los archivos de credenciales conocidos. No es un sandbox
general del ordenador. Los CLI oficiales conservan su propio comportamiento de red
cuando the user utiliza sus IAs.

## Cuota oficial de Codex y recuperación

Con `automatic_codex_resets: true`, el lector de Codex usa una sola consulta oficial
[`account/rateLimits/read`](https://learn.chatgpt.com/docs/app-server#rate-limits)
para obtener la cuota y el saldo de resets. Revalida el acceso de suscripción y la
identidad antes y después de cada consulta, sin mensajes al modelo, compras ni canjes. Exporta únicamente
fechas, ventanas de cuota y permiso de uso a `offline/codex-official.json`, ligado
al directorio y a la identidad fijada. El monitor nunca inicia ese cliente ni abre credenciales.

Se elige el bucket `codex`, no los límites de otro modelo. La respuesta debe autorizar
el uso incluido (`ordinaryUsageAllowed: true`); un bloqueo se muestra como `BLOQ`,
y un permiso ausente, ventanas inválidas o una consulta fallida dejan la cuota en
`--`. No se deduce una recuperación porque un contador llegue a cero o pase un reset.
El permiso de uso del proveedor se respeta aunque quede cuota semanal. La cifra
principal representa solo la semana; no garantiza que el límite de cinco horas
permita una petición. El panel conserva ese límite corto como ventana adicional.

La caché oficial de más de **180 segundos**, o con un reset ya pasado, pierde su
porcentaje tanto en el panel como en las nuevas imágenes. No se recuperan cifras
antiguas desde conversaciones. La lectura funciona aunque no haya ninguna sesión
de Codex abierta. Tras un fallo, el lector reconstruye su cliente y vuelve a intentar
la consulta; systemd reinicia el servicio si termina inesperadamente.

`/health` devuelve 503 si alguna cuota no está disponible o todavía no se ha confirmado
la publicación al reloj; devuelve 200 cuando las lecturas y la entrega son correctas.
Una avería de red del reloj impide cambiar su última imagen física mientras dure;
el monitor conserva el diagnóstico y reintenta automáticamente al recuperar la conexión.
No necesita que the user mantenga abierto este chat ni compruebe manualmente la cuota.

## Cuota oficial de Claude

Con `automatic_claude_usage: true`, `token-tv-claude-usage.service` consulta
[`/usage` del cliente oficial](https://code.claude.com/docs/en/costs#using-the-usage-command)
aproximadamente cada minuto. Verifica `authMethod=claude.ai` y `apiProvider=firstParty` con
una suscripción; no acepta API keys o proveedores alternativos. El lector usa un
directorio propio, modo seguro, modo restringido, ninguna herramienta, MCP vacío
y sugerencias de prompts desactivadas. No envía mensajes al modelo, compra ni
canjea resets. Telemetría, informe de errores y actualizaciones están desactivados.

El comando actualiza la caché de cuota que mantiene el propio cliente. El lector
exporta solo porcentajes y reinicios, comprueba que su identificador de cuenta
coincide con el actual y conserva `fetchedAtMs` como fecha de la observación. No
abre `.credentials.json` ni `auth.json`, ni imprime identidad o pantalla cruda.

Esto importa porque el CLI puede devolver una caché de hasta una hora ante un
fallo de red. Una fecha anterior no se sustituye por la hora de consulta: el dato
desaparece del panel y de las nuevas imágenes cuando el refresco falla, cuando
supera **180 segundos** o cuando caduca el límite semanal. El límite de 5 horas
se renueva cada 5 h (a las `:50` en esta cuenta): al renovarse se descarta él
solo, queda desconocido hasta la siguiente lectura y no arrastra a la semana.
Antes lo arrastraba, y cada renovación dejaba la pantalla de Claude en blanco
entre 1 y 5 minutos. Esto solo afecta a Claude; Codex conserva su regla. Tampoco se
recuperan porcentajes anteriores desde memoria o el capturador de Claude Code. El
lector reconoce la interfaz comprobada de la serie 2.1 de Claude Code (sus
versiones de parche, que se instalan solas, comparten la misma pantalla segura) y
además exige en pantalla modo seguro, personalizaciones desactivadas, su carpeta de
trabajo y el prompt. Una serie nueva (2.2, 3.x) no recibe ningún comando: el
registro del servicio dice `unsupported_client_version` y hay que revisar la
pantalla del cliente antes de ampliar `SERIES` en `token_tv/claude_usage.py`. Cada
fallo del lector deja en el registro su código fijo, nunca el texto del cliente.
El monitor recibe un aviso de archivo local actualizado y redibuja las cinco
imágenes inmediatamente.

El servicio de Claude está asociado al principal, igual que el lector de resets
de Codex. Parar el panel también detiene ambos lectores. Usa prioridad baja para
favorecer Sierra y los bots. `automatic_claude_usage: false` impide consultas al
arrancar y se revisa antes de cada ciclo; tras cambiar configuración, reinicia
el servicio principal. No hace falta mantener abierto el navegador o este chat.

## Resets guardados

the user autorizó expresamente consultar estos saldos después de aclarar la diferencia
entre corazones y cuota. Codex se consulta cada 60 segundos mediante su cliente
oficial: la misma lectura de cuota devuelve `rateLimitResetCredits.availableCount`.
El lector usa un destino de primera parte fijado, analytics/proxy/MCP desactivados
y solo RPCs de cuenta en lectura. No compra, usa ni canjea resets, ni inicia modelos.
Un fallo muestra saldo desconocido y se notifica también al reloj. Una lectura
automática de más de tres minutos no se presenta como actual.
El formulario del panel aplica la misma caducidad que los corazones. Las consultas
locales de cuota y de estado del reloj tienen un plazo de cuatro segundos: si no
responden, dejan de presentar cifras oficiales antiguas. La caducidad se comprueba
también cada cinco segundos sin depender de una respuesta nueva. Los saldos
confirmados manualmente se conservan con su fuente y fecha de confirmación.

El lector corre en `token-tv-codex-resets.service`, asociado al servicio principal.
Parar o deshabilitar el principal también impide su arranque. Con
`automatic_codex_resets: false` sale antes de consultar, y lo revisa cada ciclo.
Las unidades usan prioridad baja para favorecer Sierra y los bots de este PC.
El worker remoto de MTM se reserva para sus campañas pesadas ya autorizadas.

Claude consulta ahora los resets guardados mediante la extensión privada de Arc,
con la cuenta y organización comprobadas antes y después de cada lectura. Arc
debe estar abierto y conservar la sesión; no hace falta una pestaña de Uso ni
mantener abierto este chat. La cuota semanal sigue usando su lector oficial
independiente del navegador. Un dato ausente o caducado muestra `?`, nunca cero.
Con la lectura automática activada, el formulario no admite un saldo manual.
El contrato y los permisos se describen en [el lector local de Claude](claude-bank-local.md).
La [documentación oficial de Claude](https://support.claude.com/en/articles/17007452-what-is-a-limit-reset)
sitúa la oferta de resets en la web y en la aplicación de escritorio; actualmente
el botón no existe en Claude Code. El saldo de créditos de uso adicional no es un
saldo de resets. Gastar un reset tampoco cambia el día y la hora del reinicio semanal.

El [inicio local de Windows](windows-startup-local.md) inicia Ubuntu y el reloj
en segundo plano al entrar en Windows, y abre Arc cuando el panel está disponible.
No cambia los lanzadores de Sierra ni los bots.

## Lecturas locales de cuota

Cuando el lector oficial de Codex está desactivado, puede leer porcentajes y reinicios
en eventos `token_count` de los archivos de sesión. Conserva solo esos campos; no
exporta conversaciones ni créditos. Esta fuente no se usa como sustituto de una
consulta oficial fallida cuando `automatic_codex_resets` está activado.
Claude Code entrega `rate_limits` al script de su barra de estado, según su
[documentación oficial](https://code.claude.com/docs/en/statusline). El capturador
guarda únicamente porcentajes, fechas y marcadores derivados, y mantiene la salida
del formateador existente. No abre ni copia archivos de autenticación.

Las cachés privadas viven en `~/.config/token-tv/offline/`. Se permite una fuente
Claude y una Codex; se rechazan cachés de otro directorio de cuenta. En modo local
la configuración no necesita correos ni verifica la identidad mediante la red.
Una lectura local de Claude o Codex sin ventana semanal también queda desconocida;
el diagnóstico no declara éxito aunque incluya una ventana corta válida.
Al cambiar de cuenta dentro del mismo directorio, borra su caché y espera datos
nuevos de esa cuenta; los registros Codex también deben corresponder a ella.

Para Claude, el primer dato de una sesión solo establece una referencia. Sus cuotas
se publican después de observar avances del tiempo de API y de la respuesta, durante
el uso normal de Claude Code. Esto impide que una sesión antigua simule cuota renovada.
Sin el lector oficial, usar solo las webs deja el capturador local sin datos
nuevos. Una lectura de más de 15 minutos lleva `OLD`; si ha
caducado cualquiera de sus límites, la reserva conjunta queda desconocida.
No pegues claves ni tokens en el panel ni en la configuración.

`token-tv doctor` también comprueba solo archivos locales en este modo, incluso
si recibe `--live`. Respeta las mismas fuentes oficiales que el monitor y devuelve
error si alguna lectura requerida no está disponible, reciente o autorizada.
El monitor no inicia los CLI para renovar sesiones.

El reloj utiliza HTTP en la red local: transporta imágenes de cuota, nunca
credenciales. Mantén su interfaz dentro de tu red doméstica, sin abrir puertos
del router hacia Internet.

## Pruebas

```bash
.venv/bin/python -B -m unittest discover -s tests
.venv/bin/token-tv demo --out /tmp/ai-desk-display-preview
```

La suite cubre el contrato Ultra, restauración tras reinicio, falta de espacio,
modelo desconocido, verificación de los JPG almacenados, cuota restante, ausencia
de datos y paleta bicolor. Las pruebas de Codex usan respuestas sintéticas y cubren
fuente oficial sin conversaciones, cuotas cortas agotadas, bloqueo del proveedor,
caducidad en memoria, avisos perdidos, recuperación del lector y diagnóstico de salud.
Las regresiones compartidas comprueban que las cinco imágenes y el panel mantienen
porcentaje y fecha semanales aunque el límite corto esté más consumido. Claude
tiene además pruebas de respuesta parcial inválida, fallo de consulta y recuperación.
