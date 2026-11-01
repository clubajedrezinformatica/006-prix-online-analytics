"""
Extracción de partidas de jugadores adicionales — Prix Online UNLP 2026.

Descarga, para cada una de las 8 fechas del clasificatorio, las partidas de los
jugadores indicados (con relojes, aperturas y jugadas) y las guarda en data/raw/
con el mismo formato de nombre que usa extraccion.py:

    games_fecha{N}_{torneo_id}_{usuario}.json

Se ejecuta desde la raíz del proyecto (la carpeta que contiene data/ y src/):

    python src/extraccion_jugadores.py                    # Pabameky y Nicorita14
    python src/extraccion_jugadores.py UsuarioA UsuarioB  # otros jugadores

Se puede volver a correr sin riesgo: pisa los mismos archivos.
"""
import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://lichess.org/api"
RAW_DIR = Path("data/raw")
HEADERS = {"Accept": "application/x-ndjson"}
MAX_INTENTOS = 3

# (número de fecha, id del torneo Arena)
TORNEOS = [
    (1, "mhvD5tb9"),
    (2, "MxBsPRVH"),
    (3, "IfsCbYsv"),
    (4, "C4Jue0rf"),
    (5, "83kg4qfx"),
    (6, "M06fBQuL"),
    (7, "qaIVXjoY"),
    (8, "EPN0fCN8"),
]

JUGADORES = sys.argv[1:] or ["Pabameky", "Nicorita14"]


def descargar_partidas(torneo_id, usuario):
    """Partidas de un jugador en un torneo, con relojes, apertura y jugadas."""
    url = f"{BASE_URL}/tournament/{torneo_id}/games"
    params = {
        "player": usuario,
        "moves": "true",
        "opening": "true",
        "clocks": "true",
    }
    for intento in range(1, MAX_INTENTOS + 1):
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        if resp.status_code == 429:
            if intento == MAX_INTENTOS:
                break
            # Lichess pide esperar un minuto completo después de un 429
            print("  ... límite de consultas de Lichess: espero 65 s y reintento")
            time.sleep(65)
            continue
        resp.raise_for_status()
        return [json.loads(linea) for linea in resp.text.splitlines() if linea.strip()]
    raise RuntimeError(f"Lichess respondió 429 en {MAX_INTENTOS} intentos seguidos")


def revisar_resultados(jugadores):
    """Solo lectura: ¿figuran los jugadores en los resultados ya descargados?"""
    print("\n=== Control: resultados por fecha (results_fecha*.json ya descargados) ===")
    for fecha, torneo_id in TORNEOS:
        archivo = RAW_DIR / f"results_fecha{fecha}_{torneo_id}.json"
        if not archivo.exists():
            print(f"Fecha {fecha}: no encuentro {archivo.name}")
            continue
        try:
            with open(archivo, encoding="utf-8") as f:
                filas = json.load(f)
        except Exception as e:
            print(f"Fecha {fecha}: no pude leer {archivo.name}: {e}")
            continue
        por_usuario = {str(fila.get("username", "")).lower(): fila for fila in filas}
        detalle = []
        for usuario in jugadores:
            fila = por_usuario.get(usuario.lower())
            if fila is None:
                detalle.append(f"{usuario}: no figura")
            else:
                detalle.append(f"{usuario}: puesto {fila.get('rank', '?')}")
        aviso = "  <- 100 filas: la lista puede estar cortada" if len(filas) >= 100 else ""
        print(f"Fecha {fecha}: {len(filas)} filas · " + " · ".join(detalle) + aviso)


def main():
    if not RAW_DIR.is_dir():
        sys.exit(
            "No encuentro la carpeta data/raw. Ejecutá el script desde la raíz "
            "del proyecto (006_prix_online_analytics), no desde src/."
        )

    print("=== Prix Online UNLP 2026 — extracción de jugadores adicionales ===")
    print(f"Jugadores: {', '.join(JUGADORES)}")
    print(f"Destino:   {RAW_DIR.resolve()}\n")

    resumen = {usuario: {} for usuario in JUGADORES}
    escritos = 0

    for fecha, torneo_id in TORNEOS:
        print(f"Fecha {fecha} — torneo {torneo_id}")
        for usuario in JUGADORES:
            try:
                partidas = descargar_partidas(torneo_id, usuario)
            except Exception as e:
                print(f"  ✗ {usuario}: {e}")
                resumen[usuario][fecha] = None
                continue

            destino = RAW_DIR / f"games_fecha{fecha}_{torneo_id}_{usuario}.json"
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(partidas, f, ensure_ascii=False, indent=2)
            escritos += 1

            con_reloj = sum(1 for p in partidas if "clocks" in p)
            resumen[usuario][fecha] = len(partidas)
            print(f"  ✓ {usuario}: {len(partidas)} partidas ({con_reloj} con reloj)")
            time.sleep(1.5)
        print()

    print("=== Resumen: partidas descargadas por fecha ===")
    print("jugador".ljust(22) + "".join(f"F{f}".ljust(6) for f, _ in TORNEOS))
    for usuario in JUGADORES:
        celdas = ""
        for fecha, _ in TORNEOS:
            n = resumen[usuario].get(fecha)
            celdas += ("ERR" if n is None else str(n)).ljust(6)
        print(usuario.ljust(22) + celdas)
    print(f"\nArchivos escritos: {escritos} de {len(TORNEOS) * len(JUGADORES)}")
    print("0 = sin partidas en esa fecha · ERR = falló la consulta (volver a correr)")
    print("Si un jugador da 0 en las 8 fechas, revisá que el usuario esté bien escrito.")

    revisar_resultados(JUGADORES)


if __name__ == "__main__":
    main()