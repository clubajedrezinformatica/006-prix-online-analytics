# src/extraccion.py
import requests
import json
import time
from pathlib import Path

BASE_URL = "https://lichess.org/api"
RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"Accept": "application/x-ndjson"}

TOURNAMENT_IDS = [
    #"mhvD5tb9",  # Fecha 1
    #"MxBsPRVH",  # Fecha 2
    #"IfsCbYsv",  # Fecha 3
    #"C4Jue0rf",  # Fecha 4
    "83kg4qfx",   # Fecha 5
    #"M06fBQuL",  # Fecha 6
    "qaIVXjoY",   # Fecha 7
    #"EPN0fCN8",  # Fecha 8
]

PLAYERS = [
    "Ajedrezfacu",    # 1° clasificado
    "MiyuKoto",       # 2°
    "FernandoPoratto", # 3°
    "grauclub",       # 4°
    "naty_la_25",     # 5°
    "ninjago27",      # 6°
    "Tomimartinez95", # 7°
    "MTJRFAN2",       # 8°
]

def get_tournament_results(tournament_id):
    """Resultados generales del torneo: score, performance, partidas."""
    url = f"{BASE_URL}/tournament/{tournament_id}/results"
    params = {"nb": 100}
    response = requests.get(url, params=params, headers=HEADERS)
    response.raise_for_status()
    results = []
    for line in response.text.strip().split("\n"):
        if line:
            results.append(json.loads(line))
    return results

def get_tournament_games(tournament_id, username):
    """Partidas de un jugador específico en un torneo."""
    url = f"{BASE_URL}/tournament/{tournament_id}/games"
    params = {
        "player": username,
        "moves": True,
        "opening": True,
        "clocks": False,
    }
    response = requests.get(url, params=params, headers=HEADERS)
    response.raise_for_status()
    games = []
    for line in response.text.strip().split("\n"):
        if line:
            games.append(json.loads(line))
    return games

def save_json(data, filename):
    path = RAW_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Guardado: {path} ({len(data)} registros)")

def extraer_todo():
    print("=== Prix Online UNLP 2026 — Extracción fechas faltantes ===\n")
    
    fechas_pendientes = [
        (5, "83kg4qfx"),
        (7, "qaIVXjoY"),
    ]
    
    for i, tid in fechas_pendientes:
        print(f"Fecha {i} — torneo {tid}")
        try:
            results = get_tournament_results(tid)
            save_json(results, f"results_fecha{i}_{tid}.json")
        except Exception as e:
            print(f"  ✗ Error en resultados fecha {i}: {e}")
        time.sleep(1)
        for username in PLAYERS:
            print(f"  Partidas de {username}...")
            try:
                games = get_tournament_games(tid, username)
                save_json(games, f"games_fecha{i}_{tid}_{username}.json")
            except Exception as e:
                print(f"  ✗ Error en partidas de {username}: {e}")
            time.sleep(1.5)
        print()
    print("=== Extracción completa ===")

if __name__ == "__main__":
    extraer_todo()