# Ubicación GPS del Toyota C-HR

Script para consultar la posición del coche vía Toyota Connected Services
(Europa), sin depender de la app MyToyota del iPhone.

## Cómo funciona

Toyota no publica una API oficial, pero el backend que usa la app nueva
(`ctpa-oneapi`) está documentado por ingeniería inversa en el proyecto
[pytoyoda](https://github.com/pytoyoda/pytoyoda). El script se autentica con
**tus propias credenciales de MyToyota** y lee **tus propios datos**: es el
mismo acceso que ya tienes desde el móvil, solo que por línea de comandos.

## Instalación

```bash
python3 -m venv venv
source venv/bin/activate          # en Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
export TOYOTA_USER='tu@correo.com'
export TOYOTA_PASS='tu-contraseña'

python toyota_gps.py           # última posición conocida
python toyota_gps.py --wake    # despierta el coche y fuerza un reporte nuevo
python toyota_gps.py --honk    # claxon + luces para encontrarlo en un parking
python toyota_gps.py --json    # salida JSON, para encadenar con otras cosas
python toyota_gps.py --open    # abre la posición en Google Maps
python toyota_gps.py --debug   # muestra el log interno de la librería
```

Alternativa a las variables de entorno: un fichero `credentials.json` junto al
script con `{"username": "...", "password": "..."}`. Está en el `.gitignore`,
pero aun así queda en claro en tu disco — las variables de entorno o un gestor
de contraseñas son mejor idea.

## Sobre `--wake`

Es la diferencia real frente a mirar la app. La app enseña la última posición
que el coche reportó por su cuenta, normalmente al apagar el motor. `--wake`
envía un `POST /v1/remote/status` que **despierta el módulo telemático** y le
pide que reporte ahora, y después sondea hasta ver una marca de tiempo nueva.

Advertencias:

- Consume batería de 12V y datos de la SIM del coche. No lo dejes en bucle.
- El gateway responde "aceptado" antes de que el coche conteste; por eso el
  script sondea después en vez de fiarse de la respuesta inmediata.
- Si el coche está sin cobertura (garaje subterráneo) no contestará.
- No todos los vehículos lo soportan: si el código de retorno no es `000000`,
  el script te lo dice y deja de insistir.

## Limitaciones honestas

- **No hay seguimiento en vivo.** Ni por aquí ni por la app. Se obtienen
  posiciones puntuales, no una traza continua.
- Es una API no oficial: Toyota puede romperla en cualquier actualización.
- Si `latitude`/`longitude` vienen vacíos, casi siempre es el consentimiento
  de datos de ubicación desactivado en MyToyota o la suscripción de Connected
  Services caducada. Eso se arregla en la app, no en el código.
- En caso de robo, la vía correcta es Toyota + denuncia policial: ellos tienen
  localización en tiempo real que esta API no expone.

## Seguridad

Estas credenciales abren y cierran el coche. El script solo lee posición (y
`--honk`, que hace ruido pero no abre nada), pero la cuenta puede más: activa
verificación en dos pasos en MyToyota y no compartas el fichero de credenciales.
