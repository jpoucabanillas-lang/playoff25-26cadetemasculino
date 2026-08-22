# toyota-gps

Script CLI para leer la ubicación GPS de un Toyota C-HR (2019, híbrido, mercado
europeo) desde Toyota Connected Services, sin pasar por la app MyToyota.

## Contexto

El propietario tiene el coche vinculado a MyToyota con servicios conectados
activos (bloqueo/desbloqueo remoto funciona). El problema que originó esto: la
app muestra posiciones desactualizadas porque **el coche solo reporta al apagar
el motor**. La pantalla "Hybrid Coach → Viajes" no sirve para localizar: es un
histórico de conducción que solo registra viajes ya terminados, con retraso de
horas.

## Arquitectura

Un único fichero, `toyota_gps.py`, sobre [pytoyoda](https://github.com/pytoyoda/pytoyoda)
5.2.0 — cliente no oficial del backend europeo `ctpa-oneapi` (el mismo que usa
la app nueva). Toda la API de pytoyoda es **async**; el script envuelve todo en
un `asyncio.run`.

Flujo: `MyT(user, pass)` → `login()` → `get_vehicles()` → `vehicle.update()` →
leer `vehicle.location`.

## Conocimiento de la API que costó averiguar

Documentación pobre y `pytoyoda.github.io` bloqueado por el proxy de egress;
todo esto salió de introspección con `inspect.getsource`. Verifícalo antes de
fiarte si se actualiza la librería.

- **`vehicle.refresh_status()`** es la pieza clave. Emite
  `POST /v1/remote/status`, que **despierta el módulo telemático** y le pide
  reportar ahora, en vez de esperar al apagado del motor. Devuelve
  `payload.return_code == "000000"` si el gateway acepta el despertar. Ojo: eso
  significa "aceptado", **no** "el coche ya ha contestado" — hay que sondear
  después comparando `location.timestamp`. Si el código no es `000000`, el
  vehículo no lo soporta y no hay que reintentar.
- Consume batería de 12V y datos de la SIM del coche. Nunca en bucle cerrado.
- **`vehicle.update(only=[...])`** acepta nombres de endpoint:
  `location`, `status`, `telemetry`, `health_status`, `electric_status`,
  `notifications`, `service_history`, `climate_settings`, `climate_status`,
  `trip_history`. Los pide en serie a propósito: el gateway de Toyota devuelve
  429 si le llegan ~10 peticiones en el mismo tick del event loop.
- **`vehicle.location`** → `.latitude`, `.longitude`, `.timestamp`, `.state`.
  Todos pueden ser `None` aunque el coche exista: usa siempre `getattr`.
- **`vehicle.lock_status.doors` NO es un booleano.** Devuelve un objeto `Doors`
  con `driver_seat`, `passenger_seat`, `driver_rear_seat`,
  `passenger_rear_seat`, `trunk`, cada uno un `Door` con `.closed` y `.locked`
  tri-estado (`True`/`False`/`None`). Tratarlo como bool da siempre "cerrado";
  el script lo agrega en `doors_locked()`.
- **`post_command(CommandType.X)`** admite, entre otros: `FIND_VEHICLE`
  (luces + claxon), `DOOR_LOCK`, `DOOR_UNLOCK`, `ENGINE_START`, `HAZARD_ON`,
  `SOUND_HORN`. **Solo se ha cableado `FIND_VEHICLE`** — este script es de
  lectura; no añadas comandos de apertura sin que el propietario lo pida.
- Excepciones en `pytoyoda.exceptions`: `ToyotaLoginError`,
  `ToyotaInvalidUsernameError`, `ToyotaApiError`, `ToyotaRegionNotSupportedError`.
  Los errores de red suben como `httpx.HTTPError`.
- pytoyoda usa **loguru** y escupe DEBUG por defecto; el script hace
  `logger.remove()` salvo con `--debug`.

## Comandos

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export TOYOTA_USER='...' TOYOTA_PASS='...'
python toyota_gps.py          # última posición conocida
python toyota_gps.py --wake   # despierta el coche y espera reporte fresco
python toyota_gps.py --honk   # find-vehicle
python toyota_gps.py --json --open --debug
```

## Restricciones

- **Nunca pidas ni aceptes las credenciales de MyToyota en una sesión de
  Claude Code**, y menos en este entorno remoto: esa cuenta abre y cierra el
  coche. El propietario las pone en su máquina.
- **El sandbox remoto bloquea el dominio de Toyota** (`403 Forbidden` del proxy
  de egress). No se puede probar la conexión real desde aquí; solo compila,
  introspección de la librería y pruebas de camino con credenciales falsas.
- **No hay seguimiento en vivo por ninguna vía.** Ni app, ni API: posiciones
  puntuales, no traza continua. Para tiempo real en caso de robo, el canal es
  Toyota + denuncia policial.
- Si `latitude`/`longitude` vienen vacíos, el problema suele ser de cuenta y no
  de código: consentimiento de datos de ubicación desactivado en MyToyota, o
  suscripción Connected Services caducada.
- **El repositorio que aloja esto es PÚBLICO.** No metas credenciales, VIN,
  coordenadas ni logs de ejecución en commits, y no montes GitHub Actions aquí
  — los logs serían públicos. Para automatizar, repo privado aparte.
- En iOS no se puede ejecutar: pytoyoda arrastra pydantic v2, cuyo
  `pydantic-core` es Rust compilado y no publica wheel para las plataformas de
  las apps de Python de iPhone (verificado contra PyPI, incluido i686-musl de
  iSH). Alternativas desde el móvil: GitHub Codespaces, o Actions en repo
  privado.

## Relación con el resto del repo

Esta carpeta **no tiene nada que ver** con el repositorio que la contiene
(un sitio estático de un playoff de baloncesto cadete). Vive aquí solo porque
fue la rama asignada a la sesión que la creó: `claude/toyota-chr-gps-location-aasrv4`.
No la integres con el resto ni la mezcles con `main`.
