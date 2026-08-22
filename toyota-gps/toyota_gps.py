#!/usr/bin/env python3
"""Consulta la ubicacion GPS de un Toyota via Toyota Connected Services (Europa).

Usa pytoyoda, cliente no oficial del backend `ctpa-oneapi` (el mismo que usa la
app MyToyota). Se accede con TUS credenciales a TUS propios datos.

Uso:
    export TOYOTA_USER='tu@correo.com'
    export TOYOTA_PASS='tu-contrasena'

    python toyota_gps.py              # ultima posicion conocida
    python toyota_gps.py --wake       # despierta el coche y fuerza reporte
    python toyota_gps.py --json       # salida JSON
    python toyota_gps.py --open       # abre la posicion en el navegador

Alternativa a las variables de entorno: un fichero credentials.json junto al
script con {"username": "...", "password": "..."}.
"""

import argparse
import asyncio
import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import httpx
from loguru import logger

from pytoyoda.client import MyT
from pytoyoda.exceptions import (
    ToyotaApiError,
    ToyotaInvalidUsernameError,
    ToyotaLoginError,
    ToyotaRegionNotSupportedError,
)
from pytoyoda.models.endpoints.command import CommandType

CRED_FILE = Path(__file__).with_name("credentials.json")

# Espera entre sondeos tras despertar el coche: el gateway acepta la peticion
# de inmediato pero el coche tarda en reportar de vuelta.
WAKE_POLL_SECONDS = 15
WAKE_POLL_ATTEMPTS = 8


def load_credentials(args):
    """Devuelve (usuario, contrasena) desde argumentos, entorno o fichero."""
    import os

    user = args.user or os.environ.get("TOYOTA_USER")
    password = args.password or os.environ.get("TOYOTA_PASS")
    if not (user and password) and CRED_FILE.exists():
        data = json.loads(CRED_FILE.read_text())
        user = user or data.get("username")
        password = password or data.get("password")
    if not (user and password):
        sys.exit(
            "Faltan credenciales. Define TOYOTA_USER y TOYOTA_PASS, "
            f"o crea {CRED_FILE.name} con username/password."
        )
    return user, password


def age_of(timestamp):
    """Antiguedad legible de una marca de tiempo, o None si no la hay."""
    if timestamp is None:
        return None
    now = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    delta = now - timestamp
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"hace {minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"hace {hours} h {minutes % 60} min"
    return f"hace {hours // 24} dias"


def doors_locked(lock):
    """True si todas las puertas legibles estan cerradas con llave.

    Devuelve False si alguna esta abierta, y None si el coche no reporta
    estado de cerraduras.
    """
    doors = getattr(lock, "doors", None)
    if doors is None:
        return None
    states = [
        getattr(doors, name, None) and getattr(doors, name).locked
        for name in (
            "driver_seat",
            "passenger_seat",
            "driver_rear_seat",
            "passenger_rear_seat",
            "trunk",
        )
    ]
    known = [state for state in states if state is not None]
    if not known:
        return None
    return all(known)


def snapshot(vehicle):
    """Extrae los datos que nos interesan del vehiculo en un dict plano."""
    location = vehicle.location
    dashboard = vehicle.dashboard
    lock = vehicle.lock_status
    return {
        "alias": vehicle.alias,
        "vin": vehicle.vin,
        "latitude": getattr(location, "latitude", None),
        "longitude": getattr(location, "longitude", None),
        "timestamp": getattr(location, "timestamp", None),
        "state": getattr(location, "state", None),
        "odometer_km": getattr(dashboard, "odometer", None),
        "fuel_pct": getattr(dashboard, "fuel_level", None),
        "fuel_range_km": getattr(dashboard, "fuel_range", None),
        "doors_locked": doors_locked(lock),
    }


def render(data):
    """Imprime el snapshot en texto legible."""
    name = data["alias"] or "Vehiculo"
    print(f"\n{name}  ({data['vin']})")
    print("-" * 52)

    lat, lon = data["latitude"], data["longitude"]
    if lat is None or lon is None:
        print("  Sin coordenadas disponibles.")
        print("  Causas habituales: consentimiento de datos de ubicacion")
        print("  desactivado en la app, o suscripcion Connected Services")
        print("  caducada. Revisalo en MyToyota antes de insistir aqui.")
        return

    print(f"  Coordenadas : {lat:.6f}, {lon:.6f}")
    if data["state"]:
        print(f"  Zona        : {data['state']}")
    stamp = data["timestamp"]
    if stamp:
        print(f"  Reportado   : {stamp:%Y-%m-%d %H:%M:%S %Z}  ({age_of(stamp)})")
    else:
        print("  Reportado   : sin marca de tiempo")

    if data["odometer_km"] is not None:
        print(f"  Odometro    : {data['odometer_km']} km")
    if data["fuel_pct"] is not None:
        rng = data["fuel_range_km"]
        extra = f"  (~{rng} km de autonomia)" if rng is not None else ""
        print(f"  Combustible : {data['fuel_pct']}%{extra}")
    if data["doors_locked"] is not None:
        print(f"  Cerraduras  : {'cerrado' if data['doors_locked'] else 'ABIERTO'}")

    print(f"\n  Google Maps : https://maps.google.com/?q={lat},{lon}")
    print(f"  Apple Maps  : https://maps.apple.com/?ll={lat},{lon}&q=Coche")


async def wake_and_wait(vehicle, before_timestamp):
    """Despierta el coche y sondea hasta que reporte una posicion mas nueva."""
    print("\nEnviando peticion de despertar al coche...")
    response = await vehicle.refresh_status()
    code = getattr(getattr(response, "payload", None), "return_code", None)
    if code != "000000":
        print(f"  El coche no admite refresh remoto (codigo {code!r}).")
        print("  Seguira actualizandose solo al apagar el motor.")
        return False

    print(f"  Aceptado. Sondeando cada {WAKE_POLL_SECONDS}s...")
    for attempt in range(1, WAKE_POLL_ATTEMPTS + 1):
        await asyncio.sleep(WAKE_POLL_SECONDS)
        await vehicle.update(only=["location", "status", "telemetry"])
        now_timestamp = getattr(vehicle.location, "timestamp", None)
        if now_timestamp and now_timestamp != before_timestamp:
            print(f"  Posicion nueva recibida (intento {attempt}).")
            return True
        print(f"  Intento {attempt}/{WAKE_POLL_ATTEMPTS}: aun sin datos nuevos.")

    print("  El coche no ha respondido. Suele significar que esta sin")
    print("  cobertura (garaje subterraneo) o con el modulo dormido.")
    return False


async def run(args):
    user, password = load_credentials(args)
    client = MyT(username=user, password=password)
    try:
        try:
            await client.login()
        except (ToyotaLoginError, ToyotaInvalidUsernameError) as exc:
            sys.exit(
                f"Login rechazado: {exc}\n"
                "Comprueba usuario y contrasena en la app MyToyota. Si tienes "
                "verificacion en dos pasos activada, la libreria puede pedir "
                "un codigo por consola."
            )
        except ToyotaRegionNotSupportedError as exc:
            sys.exit(f"Region no soportada: {exc}")
        except httpx.HTTPError as exc:
            sys.exit(f"Error de red hablando con Toyota: {exc}")
        vehicles = await client.get_vehicles()
        vehicles = [v for v in vehicles if v is not None]
        if not vehicles:
            sys.exit("La cuenta no tiene vehiculos vinculados.")

        for vehicle in vehicles:
            if args.vin and vehicle.vin != args.vin:
                continue
            await vehicle.update()
            before = getattr(vehicle.location, "timestamp", None)

            if args.wake:
                await wake_and_wait(vehicle, before)
            if args.honk:
                # find-vehicle: pitido y luces, para localizarlo en un parking
                await vehicle.post_command(CommandType.FIND_VEHICLE)
                print("\nComando find-vehicle enviado (luces y claxon).")

            data = snapshot(vehicle)
            if args.json:
                print(json.dumps(data, indent=2, default=str, ensure_ascii=False))
            else:
                render(data)

            if args.open and data["latitude"] is not None:
                webbrowser.open(
                    f"https://maps.google.com/?q={data['latitude']},{data['longitude']}"
                )
    finally:
        await client.aclose()


def main():
    parser = argparse.ArgumentParser(
        description="Ubicacion GPS de un Toyota via Connected Services."
    )
    parser.add_argument("--user", help="usuario MyToyota (o TOYOTA_USER)")
    parser.add_argument("--password", help="contrasena MyToyota (o TOYOTA_PASS)")
    parser.add_argument("--vin", help="limita a un VIN concreto")
    parser.add_argument(
        "--wake",
        action="store_true",
        help="despierta el coche y espera un reporte fresco "
        "(consume bateria de 12V y datos moviles; usalo con moderacion)",
    )
    parser.add_argument(
        "--honk",
        action="store_true",
        help="hace sonar el claxon y parpadear las luces (find-vehicle)",
    )
    parser.add_argument("--json", action="store_true", help="salida en JSON")
    parser.add_argument("--open", action="store_true", help="abre Google Maps")
    parser.add_argument(
        "--debug", action="store_true", help="muestra el log interno de pytoyoda"
    )
    args = parser.parse_args()

    # pytoyoda usa loguru y escupe DEBUG por defecto; lo callamos salvo --debug.
    if not args.debug:
        logger.remove()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        sys.exit(130)
    except ToyotaApiError as exc:
        sys.exit(f"La API de Toyota devolvio un error: {exc}")
    except httpx.HTTPError as exc:
        sys.exit(f"Error de red hablando con Toyota: {exc}")


if __name__ == "__main__":
    main()
