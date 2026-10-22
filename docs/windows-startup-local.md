# Inicio del reloj al entrar en Windows

Los tres servicios del reloj están habilitados en el systemd del usuario de
Ubuntu. El usuario tiene `Linger=yes` y Ubuntu usa `systemd=true`. Esto inicia los
servicios al arrancar Ubuntu; por sí solo no inicia Ubuntu al entrar en Windows.
Además, Microsoft explica que [los servicios systemd no mantienen WSL encendido](https://devblogs.microsoft.com/commandline/systemd-support-is-now-available-in-wsl/).

La instalación privada añade únicamente `Reloj local.vbs` a la carpeta Inicio del
usuario de Windows. Su copia se guarda en `~/.config/token-tv/windows-startup.vbs`.
El lanzador ejecuta `scripts/windows_clock_host.py` mediante el Python del proyecto
en Ubuntu, en una ventana oculta. Este proceso mantiene esa conexión WSL mientras
el servicio del reloj sigue activo. Un bloqueo privado impide duplicarlo. Systemd
inicia los servicios ya habilitados durante el arranque de Ubuntu; este host solo
consulta su estado. No habilita servicios ni reactiva una parada manual, incluso
si se invoca otra vez en el mismo arranque. No administra otros programas.
Tolera brevemente un reinicio del servicio o un fallo de consulta; una parada
sostenida termina el host, sin intentar volver a iniciar el servicio.
El archivo privado `windows-host.lock` registra su PID, inicio y salida, sin
información de cuentas.

El lanzador espera a que el panel localhost responda y después abre el Arc ya
instalado por su identificador público de aplicación, si Arc todavía no está
ejecutándose. Acepta una salud degradada: esperar a que los corazones sean válidos
antes de abrir Arc impediría el propio arranque. Tiene un plazo finito (unos seis
minutos) y no sigue redirecciones. Justo después de iniciar sesión, WSL puede no
estar listo todavía y un `wsl.exe` fallido en una ventana oculta no se ve: por eso
vuelve a lanzar el anfitrión cada 30 segundos mientras el panel no responda. Repetir
el lanzamiento es inocuo, porque el bloqueo privado hace que una segunda copia
termine al instante. La espera evita abrir Arc antes de que la carpeta privada de la
extensión en Ubuntu esté disponible. No cambia el navegador predeterminado,
configuración de Arc, pestañas, trading, políticas de PowerShell, permisos de
Codex ni el arranque de Sierra o los bots.

Las cuotas semanales de Claude y Codex, sus fechas semanales y los corazones de
Codex usan los clientes oficiales locales. No necesitan páginas del navegador.
Los corazones de Claude necesitan Arc ejecutándose y con sesión en la cuenta
fijada. No hace falta dejar abiertas Uso, consola, terminal ni esta conversación.
Las sesiones suelen sobrevivir al reinicio, pero pueden caducar o ser revocadas;
en ese caso hay que iniciar sesión por el cliente oficial correspondiente.

El arranque ocurre **al entrar en la cuenta de Windows**, no antes de iniciar
sesión. Windows de este equipo no tiene inicio de sesión automático (comprobado el
2026-10-13), así que tras un reinicio o un corte de luz el reloj y la placa empiezan
a recibir datos cuando se entra en la cuenta, y unos dos minutos después tienen
cifras. Una distribución WSL pertenece a la cuenta de usuario, de modo que no hay
forma de arrancarla antes del inicio de sesión sin guardar la contraseña. El equipo, Internet y el reloj en su red deben estar disponibles. No hay
consultas durante apagado o suspensión. La primera lectura y publicación pueden
tardar alrededor de uno o dos minutos; mientras tanto los datos sin comprobar
son desconocidos. Si se cierra Arc, su saldo caduca y muestra `?`; las cuotas y
Codex continúan. Los fallos de red o proveedor no se sustituyen con cifras antiguas.

Para retirar este inicio automático, elimina exclusivamente `Reloj local.vbs` de
la carpeta Inicio de Windows. No deshabilites ni reinicies WSL entero, pues este
ordenador también ejecuta otras tareas. La parada habitual del servicio del
reloj sigue deteniendo sus dos lectores y termina también este pequeño host.
