# Instalar AI Desk Display

Empieza por la [demo sin cuentas](../README.md#try-it-without-a-display-or-an-account). El paquete público conserva el comando `token-tv`, pero se instala desde **este repositorio**, no desde PyPI ni desde el proyecto upstream.

## Crear tu configuración privada

Necesitas tus propios clientes oficiales de Claude/Codex instalados y con sesión iniciada. No compartas sus archivos de autenticación.

```bash
token-tv setup
token-tv doctor
```

`setup` crea una configuración privada y pregunta por tus cuentas y dispositivo; no sobrescribe una configuración existente. `doctor` revisa la instalación sin consultar cuotas reales. `doctor --live` sí consulta los proveedores: ejecútalo solo si quieres hacer esa comprobación.

Para una placa ESP32 ya preparada, añade la dirección que muestra su pantalla:

```bash
token-tv board --url http://192.168.0.60
token-tv board --check
```

La IP es un ejemplo; utiliza la tuya. No publiques el token de emparejamiento. El firmware se prepara por separado: [guía de hardware](hardware.md).

## Modo local y lectores actuales

La instalación de referencia usa un monitor en modo `local_only` y dos lectores independientes. El monitor consume cachés locales; los lectores consultan los servicios oficiales. Para las escenas semanales se recomienda **una cuenta de Codex y una de Claude**.

En tu configuración privada puedes habilitar `local_only: true`, `automatic_codex_resets: true` y `automatic_claude_usage: true`. Si solo utilizas la placa táctil, `display_enabled: false` evita enviar fotos a un reloj GeekMagic. Conserva las cuentas creadas por setup y no copies configuraciones de otra persona.

Desde el checkout y con el entorno virtual activado, en procesos separados:

```bash
token-tv run
python scripts/codex_reset_collector.py --config ~/.config/token-tv/config.json
python scripts/claude_usage_collector.py --config ~/.config/token-tv/config.json
```

El panel está en `http://127.0.0.1:8787`. Estos lectores son dependientes de versiones y de la información que entregue cada proveedor; pueden requerir adaptar la integración. Un error de lectura no debe convertirse en un porcentaje inventado.

Los resets guardados de Claude necesitan además la [extensión local emparejada](claude-bank-local.md). No basta con cargar su carpeta fuente: faltan deliberadamente los datos privados de emparejamiento. No actives `automatic_claude_resets` antes de prepararla.

## Inicio automático

Puedes gestionar monitor y lectores con servicios de usuario de tu sistema. Este repositorio **no instala automáticamente** servicios, tareas de Windows ni launchers personales. La guía de [inicio en Windows/WSL](windows-startup-local.md) describe el diseño de referencia; adapta rutas y servicios a tu instalación.

El ordenador debe permanecer activo para obtener lecturas nuevas. La placa conserva las escenas y anima localmente, pero oculta cifras obsoletas cuando deja de recibir el heartbeat.

## Otros relojes

Para un GeekMagic SmallTV Ultra, consulta [su guía](smalltv-ultra.md). No tiene la misma capacidad ni firmware que la placa táctil. No uses un binario de ESP32-2432S028R en un dispositivo distinto.
