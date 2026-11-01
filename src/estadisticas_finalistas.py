"""
Tarjetas de estadísticas de los finalistas - PRIX ONLINE UNLP 2026.

Lee los archivos que bajó la API de Lichess(data/raw/) y calcula, para cada finalista, los datos de su "sport card": 
1. Puntos de arena tomados en el clasificatorio (suma de las 8 fechas) 
2.% de partidas jugadas con berserk
3.Jugadas por partida(promedio)
4.Segundos por jugada(promedio)
5.%de victorias con blancas 
6.%de victorias con negras 
7.Apertura más jugada con blancas y defensa más jugada con negras 

Se ejecuta desde la raíz del proyecto (ka carpeta que contiene  data/ y src/):

python /src/estadisticas_finalistas.py #los 8 finalistas 
python /src/estadisticas_finalistas.py UsuarioA UsuarioB #otros jugadores 

Solo lee data/row/. Escribe data/processed/tarjetass_finalistas.json y .csv. Antes de la tabla imprime un diagnóstico de los datos y al final los avisos.
"""
import csv
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/processed")

FINALISTAS = ["Ajedrezfacu", "MiyuKoto", "FernandoPoratto", "Valeny",
              "Tomimartinez95", "MTJRFAN2", "Pabameky", "Nicorita14"]

# fecha -> id del torneo Arena (los mismos que usan los scripts de extracción)
TORNEOS = {1: "mhvD5tb9", 2: "MxBsPRVH", 3: "IfsCbYsv", 4: "C4Jue0rf",
           5: "83kg4qfx", 6: "M06fBQuL", 7: "qaIVXjoY", 8: "EPN0fCN8"}

INCREMENTO_DEFECTO = 2    # segundos (3+2); solo si la partida no trae su campo "clock"
UMBRAL_BERSERK = 0.75     # reloj inicial menor al 75% del tiempo base => berserk
PATRON_PARTIDAS = re.compile(r"games_fecha(\d+)_([A-Za-z0-9]+)_(.+)\.json")

DEFINICIONES = {
    "puntos_arena": "suma de los puntos oficiales de Lichess (con rachas y bonus de berserk) en las fechas jugadas",
    "puntos_ajedrez": "victorias + 0,5 por tablas, en las partidas usadas",
    "berserk_pct": "% de partidas con berserk sobre las partidas usadas",
    "jugadas_por_partida": "jugadas completas por partida (una jugada = blancas + negras)",
    "seg_por_jugada": "segundos consumidos por jugada propia; no cuenta la primera jugada (el reloj aún no corre) y descuenta el incremento",
    "pct_victorias": "victorias / partidas con ese color (tablas y derrotas cuentan en el total)",
    "aperturas_blancas / defensas_negras": "familia de apertura según Lichess (texto anterior a los dos puntos); lista de las 3 más jugadas",
}

avisos = []                   # se imprimen al final
diag = Counter()              # contadores para el diagnóstico
primeros_relojes = Counter()  # primer reloj de cada jugador en cada partida (centésimas)


def leer_json(ruta):
    """Lista de objetos de un .json (lista) o de un NDJSON (un objeto por línea)."""
    texto = ruta.read_text(encoding="utf-8")
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        datos = [json.loads(linea) for linea in texto.splitlines() if linea.strip()]
    if isinstance(datos, dict):
        listas = [v for v in datos.values() if isinstance(v, list)]
        datos = listas[0] if listas else [datos]
    return [d for d in datos if isinstance(d, dict)]


def buscar_archivos(jugadores):
    """{usuario en minúsculas: {fecha: ruta}} y los usuarios ajenos que hay en data/raw."""
    por_jugador = {u.lower(): {} for u in jugadores}
    ajenos = Counter()
    for ruta in sorted(RAW_DIR.glob("games_fecha*.json")):
        m = PATRON_PARTIDAS.fullmatch(ruta.name)
        if not m:
            avisos.append(f"Nombre de archivo no reconocido (se ignora): {ruta.name}")
            continue
        fecha, torneo_id, usuario = int(m.group(1)), m.group(2), m.group(3)
        if usuario.lower() not in por_jugador:
            ajenos[usuario] += 1
        elif TORNEOS.get(fecha) != torneo_id:
            avisos.append(f"{ruta.name}: el id {torneo_id} no corresponde a la fecha {fecha} "
                          f"(debería ser {TORNEOS.get(fecha)}). Se ignora; conviene borrarlo.")
        else:
            por_jugador[usuario.lower()][fecha] = ruta
    return por_jugador, ajenos


def cargar_partidas(usuario, archivos):
    """{fecha: [partidas]} de un jugador, contando cada partida una sola vez."""
    vistas, por_fecha, repetidas = set(), {}, 0
    for fecha, ruta in sorted(archivos.items()):
        try:
            partidas = leer_json(ruta)
        except Exception as e:
            avisos.append(f"No pude leer {ruta.name}: {e}")
            continue
        nuevas = []
        for g in partidas:
            if g.get("id") in vistas:
                repetidas += 1
            else:
                vistas.add(g.get("id"))
                nuevas.append(g)
        por_fecha[fecha] = nuevas
    if repetidas:
        avisos.append(f"{usuario}: {repetidas} partida(s) repetida(s) entre archivos; se cuentan una sola vez.")
    return por_fecha


def cargar_resultados():
    """{fecha: filas} de results_fecha{N}_{id}.json."""
    resultados = {}
    for fecha, torneo_id in TORNEOS.items():
        ruta = RAW_DIR / f"results_fecha{fecha}_{torneo_id}.json"
        if not ruta.exists():
            avisos.append(f"Falta {ruta.name}: no hay puntos oficiales de la fecha {fecha}.")
            continue
        try:
            resultados[fecha] = leer_json(ruta)
        except Exception as e:
            avisos.append(f"No pude leer {ruta.name}: {e}")
    return resultados


def color_de(g, usuario):
    """'white', 'black' o None si el jugador no participa de la partida."""
    for color in ("white", "black"):
        u = ((g.get("players") or {}).get(color) or {}).get("user") or {}
        if usuario.lower() in (str(u.get("id", "")).lower(), str(u.get("name", "")).lower()):
            return color
    return None


def pct(parte, total):
    return round(100 * parte / total, 1) if total else None


def promedio(valores):
    return round(sum(valores) / len(valores), 1) if valores else None


def analizar(g, color, ref_cs, usar_bandera):
    """Mide una partida desde el lado `color`. Devuelve un dict con lo medido."""
    ganador = g.get("winner")
    resultado = "tablas" if not ganador else ("victoria" if ganador == color else "derrota")
    movs = (g.get("moves") or "").split()
    relojes = g.get("clocks") or []
    plies = len(movs) or len(relojes)
    mios = relojes[0::2] if color == "white" else relojes[1::2]   # mis relojes, tras cada jugada mía

    reloj = g.get("clock") or {}
    inicial_cs = reloj["initial"] * 100 if reloj.get("initial") else ref_cs
    incremento_cs = (reloj["increment"] if reloj.get("increment") is not None else INCREMENTO_DEFECTO) * 100

    bandera = bool(((g.get("players") or {}).get(color) or {}).get("berserk"))
    por_reloj = bool(mios[0] < UMBRAL_BERSERK * inicial_cs) if (mios and inicial_cs) else None
    if usar_bandera:
        berserk = bandera
        if por_reloj is not None:
            diag["berserk: bandera y reloj comparados"] += 1
            diag["berserk: bandera y reloj coinciden"] += (bandera == por_reloj)
    else:
        berserk = por_reloj

    # Tiempo consumido: la primera jugada de cada bando no corre reloj y no suma incremento;
    # desde la segunda, reloj_anterior - reloj_actual + incremento. La suma "telescopa":
    # primer_reloj - último_reloj + incremento * jugadas_cronometradas (el berserk no tiene incremento).
    consumido = cronometradas = None
    if mios:
        primeros_relojes[mios[0]] += 1
    if berserk is not None and len(mios) >= 2:
        cronometradas = len(mios) - 1
        consumido = mios[0] - mios[-1] + (0 if berserk else incremento_cs) * cronometradas
        clave = "con berserk" if berserk else "sin berserk"
        diag[f"subidas {clave}"] += sum(1 for a, b in zip(mios, mios[1:]) if b > a)
        diag[f"transiciones {clave}"] += cronometradas
        if consumido < -200:
            diag["consumo de tiempo negativo"] += 1

    apertura = (g.get("opening") or {}).get("name")
    return {
        "color": color,
        "resultado": resultado,
        "jugadas": math.ceil(plies / 2) if plies else None,
        "berserk": berserk,
        "consumido_cs": consumido,
        "cronometradas": cronometradas,
        "apertura": apertura,
        "familia": apertura.split(":")[0].strip() if apertura else None,
        "primera": movs[0] if color == "white" and movs else None,
        "rival_primera": movs[0] if color == "black" and movs else None,
        "respuesta": movs[1] if color == "black" and len(movs) > 1 else None,
    }


def por_color(lista):
    v = sum(p["resultado"] == "victoria" for p in lista)
    t = sum(p["resultado"] == "tablas" for p in lista)
    return {"partidas": len(lista), "victorias": v, "tablas": t,
            "derrotas": len(lista) - v - t, "pct_victorias": pct(v, len(lista))}


def top_aperturas(lista, k=3):
    """Las k familias de apertura más frecuentes (nombre de Lichess antes de los dos puntos)."""
    familias = Counter(p["familia"] for p in lista if p["familia"])
    total = sum(familias.values())
    salida = []
    for familia, cuenta in familias.most_common(k):
        variantes = Counter(p["apertura"] for p in lista if p["familia"] == familia)
        salida.append({"familia": familia, "partidas": cuenta, "pct": pct(cuenta, total),
                       "variante_frecuente": variantes.most_common(1)[0][0]})
    return salida


def mas_comun(valores):
    cuentas = Counter(v for v in valores if v)
    if not cuentas:
        return None
    jugada, n = cuentas.most_common(1)[0]
    return {"jugada": jugada, "partidas": n, "pct": pct(n, sum(cuentas.values()))}


def seg_por_jugada(lista):
    """Segundos por jugada propia: tiempo total consumido / jugadas cronometradas."""
    lista = [p for p in lista if p["consumido_cs"] is not None]
    jugadas = sum(p["cronometradas"] for p in lista)
    return round(sum(p["consumido_cs"] for p in lista) / jugadas / 100, 2) if jugadas else None


def resumir(usuario, por_fecha, resultados, ref_cs, usar_bandera):
    """Todas las métricas de un jugador."""
    partidas = []
    for fecha, lista in sorted(por_fecha.items()):
        for g in lista:
            diag["partidas leídas"] += 1
            if g.get("status") in ("aborted", "noStart", "created", "started"):
                diag["descartadas: abortadas o sin terminar"] += 1
                continue
            color = color_de(g, usuario)
            if color is None:
                diag["descartadas: el jugador no juega esa partida"] += 1
                continue
            if not g.get("winner") and g.get("status") not in ("draw", "stalemate"):
                diag["descartadas: sin resultado claro"] += 1
                continue
            p = analizar(g, color, ref_cs, usar_bandera)
            if p["jugadas"] is None:
                diag["descartadas: sin jugadas"] += 1
                continue
            p["fecha"] = fecha
            partidas.append(p)
            diag["usadas"] += 1
            diag["con reloj"] += bool(g.get("clocks"))
            diag["con apertura"] += bool(p["apertura"])

    # --- puntos oficiales de arena, fecha por fecha ---
    puntos = {}
    for fecha in sorted(TORNEOS):
        filas = resultados.get(fecha)
        if filas is None:
            continue
        del_dia = [p for p in partidas if p["fecha"] == fecha]
        fila = next((r for r in filas if str(r.get("username", "")).lower() == usuario.lower()), None)
        if fila is None:
            if del_dia:
                causa = "puede estar fuera del top 100" if len(filas) >= 100 else "no figura"
                avisos.append(f"{usuario}, fecha {fecha}: tiene partidas pero {causa} en los resultados; "
                              f"sus puntos de esa fecha NO están sumados.")
            continue
        if "score" not in fila:
            avisos.append(f"{usuario}, fecha {fecha}: la fila de resultados no trae 'score' "
                          f"(campos: {sorted(fila)}).")
            continue
        v = sum(p["resultado"] == "victoria" for p in del_dia)
        t = sum(p["resultado"] == "tablas" for p in del_dia)
        score = fila["score"]
        # Cotas seguras: una victoria vale al menos 2; como mucho 6 (4 de racha + bonus); unas tablas, como mucho 2.
        if score < 2 * v:
            avisos.append(f"{usuario}, fecha {fecha}: {score} puntos oficiales pero {v} victorias en los archivos "
                          f"(mínimo posible {2 * v}): ¿partidas de más o de otro torneo?")
        elif score > 6 * v + 2 * t:
            avisos.append(f"{usuario}, fecha {fecha}: {score} puntos oficiales con solo {v} victorias y {t} tablas "
                          f"en los archivos (máximo posible {6 * v + 2 * t}): ¿faltan partidas?")
        puntos[fecha] = {"puesto": fila.get("rank"), "puntos": score, "performance": fila.get("performance")}

    # --- resto de las métricas ---
    blancas = [p for p in partidas if p["color"] == "white"]
    negras = [p for p in partidas if p["color"] == "black"]
    con_dato = [p for p in partidas if p["berserk"] is not None]
    n_berserk = sum(bool(p["berserk"]) for p in con_dato)
    cronometradas = [p for p in partidas if p["consumido_cs"] is not None]
    victorias = sum(p["resultado"] == "victoria" for p in partidas)
    tablas = sum(p["resultado"] == "tablas" for p in partidas)
    return {
        "usuario": usuario,
        "puntos_arena": sum(f["puntos"] for f in puntos.values()),
        "fechas_con_puntos": len(puntos),
        "puntos_por_fecha": puntos,
        "partidas": len(partidas),
        "fechas_con_partidas": len({p["fecha"] for p in partidas}),
        "puntos_ajedrez": victorias + 0.5 * tablas,
        "berserk_pct": pct(n_berserk, len(con_dato)),
        "partidas_con_berserk": n_berserk,
        "jugadas_por_partida": promedio([p["jugadas"] for p in partidas]),
        "seg_por_jugada": seg_por_jugada(cronometradas),
        "seg_por_jugada_sin_berserk": seg_por_jugada([p for p in cronometradas if not p["berserk"]]),
        "seg_por_jugada_con_berserk": seg_por_jugada([p for p in cronometradas if p["berserk"]]),
        "blancas": por_color(blancas),
        "negras": por_color(negras),
        "aperturas_blancas": top_aperturas(blancas),
        "defensas_negras": top_aperturas(negras),
        "primera_jugada_blancas": mas_comun([p["primera"] for p in blancas]),
        "respuesta_a_1e4": mas_comun([p["respuesta"] for p in negras if p["rival_primera"] == "e4"]),
        "respuesta_a_1d4": mas_comun([p["respuesta"] for p in negras if p["rival_primera"] == "d4"]),
    }


def controles_de_coherencia(usar_bandera):
    """Avisos si los datos contradicen los supuestos del cálculo de tiempos y berserk."""
    comparadas = diag["berserk: bandera y reloj comparados"]
    if usar_bandera and comparadas and diag["berserk: bandera y reloj coinciden"] < 0.98 * comparadas:
        avisos.append("El campo 'berserk' y el reloj inicial no coinciden en "
                      f"{comparadas - diag['berserk: bandera y reloj coinciden']} de {comparadas} partidas: "
                      "revisar antes de publicar el % de berserk.")
    t_con, t_sin = diag["transiciones con berserk"], diag["transiciones sin berserk"]
    if t_con >= 20 and diag["subidas con berserk"] > 0.02 * t_con:
        avisos.append("En partidas con berserk el reloj SUBE entre jugadas "
                      f"({diag['subidas con berserk']} de {t_con}): el incremento no estaría anulado y los "
                      "segundos por jugada de los berserkers saldrían subestimados.")
    if t_sin >= 50 and diag["subidas sin berserk"] == 0:
        avisos.append("Sin berserk el reloj nunca sube entre jugadas: los relojes del JSON quizá ya "
                      "descuentan el incremento; los segundos por jugada saldrían sobreestimados.")
    if diag["consumo de tiempo negativo"]:
        avisos.append(f"{diag['consumo de tiempo negativo']} partida(s) con consumo de tiempo negativo: "
                      "los relojes no cuadran con el incremento supuesto.")


def num(x, ancho, dec=1):
    return (f"{x:.{dec}f}" if x is not None else "—").rjust(ancho)


def imprimir_diagnostico(usados, esperados, n_resultados, ajenos, primera, usar_bandera):
    descartes = {k.split(": ", 1)[1]: v for k, v in diag.items() if k.startswith("descartadas: ")}
    print("--- Diagnóstico de los datos ---")
    print(f"Archivos de partidas: {usados} usados de {esperados} esperados · "
          f"resultados: {n_resultados} de {len(TORNEOS)}")
    if ajenos:
        print(f"Archivos de otros usuarios (ignorados): {sum(ajenos.values())} de {len(ajenos)} usuario(s)")
    detalle = f" ({', '.join(f'{k}: {v}' for k, v in descartes.items())})" if descartes else ""
    print(f"Partidas leídas: {diag['partidas leídas']} · usadas: {diag['usadas']} · "
          f"descartadas: {sum(descartes.values())}{detalle}")
    print(f"Con relojes: {diag['con reloj']} · con apertura: {diag['con apertura']}")
    print(f"Campos de players.white en la primera partida: {sorted((primera.get('players') or {}).get('white') or {})}")
    if usar_bandera:
        print("Berserk: se usa el campo 'berserk' del JSON; coincide con el reloj inicial en "
              f"{diag['berserk: bandera y reloj coinciden']} de {diag['berserk: bandera y reloj comparados']} partidas")
    else:
        print("Berserk: el JSON no trae el campo 'berserk'; se infiere por el reloj inicial "
              f"(menos del {UMBRAL_BERSERK:.0%} del tiempo base)")
    comunes = primeros_relojes.most_common(3)
    resto = sum(primeros_relojes.values()) - sum(v for _, v in comunes)
    print("Primer reloj propio (centésimas): " + " · ".join(f"{k} ×{v}" for k, v in comunes)
          + (f" · otros ×{resto}" if resto else ""))

    def tasa(clave):
        t, s = diag[f"transiciones {clave}"], diag[f"subidas {clave}"]
        return f"{100 * s / t:.0f}% ({s}/{t})" if t else "—"
    print(f"Subidas de reloj entre jugadas propias: sin berserk {tasa('sin berserk')} · "
          f"con berserk {tasa('con berserk')}")


def imprimir_tabla(filas):
    print("\n--- Tarjetas ---")
    print(f"{'Jugador':<17}{'Pts':>5}{'Part':>6}{'Bers%':>7}{'Jug/p':>7}{'s/jug':>7}"
          f"{'V%Bl':>7}{'V%Ng':>7}{'nBl':>5}{'nNg':>5}")
    for f in filas:
        print(f"{f['usuario']:<17}{num(f['puntos_arena'], 5, 0)}{num(f['partidas'], 6, 0)}"
              f"{num(f['berserk_pct'], 7)}{num(f['jugadas_por_partida'], 7)}{num(f['seg_por_jugada'], 7, 2)}"
              f"{num(f['blancas']['pct_victorias'], 7)}{num(f['negras']['pct_victorias'], 7)}"
              f"{num(f['blancas']['partidas'], 5, 0)}{num(f['negras']['partidas'], 5, 0)}")
    print("Pts = puntos de arena · Part = partidas · Bers% = partidas con berserk · Jug/p = jugadas por partida")
    print("s/jug = segundos por jugada · V%Bl / V%Ng = % de victorias con blancas / negras · "
          "nBl / nNg = partidas con cada color")

    def top(lista):
        return " · ".join(f"{x['familia']} ({x['partidas']})" for x in lista) or "—"

    def jug(x):
        return f"{x['jugada']} ({x['pct']:.0f}%)" if x else "—"
    print("\nAperturas: las 3 familias de Lichess más frecuentes (entre paréntesis, partidas) y la elección propia del jugador."
          "\nOjo: Lichess nombra la posición, no quién la eligió (con 1.e4 el rival puede llevar a 'Sicilian Defense').")
    for f in filas:
        print(f"{f['usuario']}")
        print(f"   Blancas: {top(f['aperturas_blancas'])}   | primera jugada más usada: {jug(f['primera_jugada_blancas'])}")
        print(f"   Negras:  {top(f['defensas_negras'])}   | vs 1.e4: {jug(f['respuesta_a_1e4'])} · vs 1.d4: {jug(f['respuesta_a_1d4'])}")


def guardar(filas):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ruta_json = OUT_DIR / "tarjetas_finalistas.json"
    ruta_json.write_text(json.dumps(
        {"generado": datetime.now().isoformat(timespec="seconds"), "definiciones": DEFINICIONES,
         "jugadores": filas}, ensure_ascii=False, indent=2), encoding="utf-8")
    columnas = ["usuario", "puntos_arena", "fechas_con_puntos", "partidas", "berserk_pct",
                "jugadas_por_partida", "seg_por_jugada", "partidas_blancas", "victorias_blancas_pct",
                "partidas_negras", "victorias_negras_pct", "apertura_blancas", "apertura_blancas_partidas",
                "defensa_negras", "defensa_negras_partidas"]
    ruta_csv = OUT_DIR / "tarjetas_finalistas.csv"
    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columnas)
        for r in filas:
            ap = r["aperturas_blancas"][0] if r["aperturas_blancas"] else {}
            de = r["defensas_negras"][0] if r["defensas_negras"] else {}
            w.writerow([r["usuario"], r["puntos_arena"], r["fechas_con_puntos"], r["partidas"], r["berserk_pct"],
                        r["jugadas_por_partida"], r["seg_por_jugada"], r["blancas"]["partidas"],
                        r["blancas"]["pct_victorias"], r["negras"]["partidas"], r["negras"]["pct_victorias"],
                        ap.get("familia"), ap.get("partidas"), de.get("familia"), de.get("partidas")])
    print(f"\nGuardado: {ruta_json} y {ruta_csv.name}")


def main():
    if not RAW_DIR.is_dir():
        sys.exit("No encuentro la carpeta data/raw. Ejecutá el script desde la raíz "
                 "del proyecto (006_prix_online_analytics), no desde src/.")
    jugadores = sys.argv[1:] or FINALISTAS
    print("=== Tarjetas de estadísticas — Prix Online UNLP 2026 ===")
    print(f"Jugadores: {', '.join(jugadores)}\n")

    archivos, ajenos = buscar_archivos(jugadores)
    resultados = cargar_resultados()
    cargadas = {}
    for u in jugadores:
        faltan = [f for f in TORNEOS if f not in archivos[u.lower()]]
        if faltan:
            avisos.append(f"{u}: faltan los archivos de partidas de las fechas {faltan}.")
        cargadas[u] = cargar_partidas(u, archivos[u.lower()])

    todas = [g for por_fecha in cargadas.values() for lista in por_fecha.values() for g in lista]
    if not todas:
        sys.exit("No encontré partidas en data/raw para estos jugadores. ¿Están los games_fecha*.json?")

    usar_bandera = any(((g.get("players") or {}).get(c) or {}).get("berserk")
                       for g in todas for c in ("white", "black"))
    iniciales = [max(g["clocks"][:2]) for g in todas if g.get("clocks")]
    ref_cs = max(iniciales) if iniciales else None

    filas = [resumir(u, cargadas[u], resultados, ref_cs, usar_bandera) for u in jugadores]
    filas.sort(key=lambda f: (-f["puntos_arena"], -f["partidas"]))
    controles_de_coherencia(usar_bandera)

    usados = sum(len(a) for a in archivos.values())
    imprimir_diagnostico(usados, len(jugadores) * len(TORNEOS), len(resultados), ajenos, todas[0], usar_bandera)
    imprimir_tabla(filas)
    try:
        guardar(filas)
    except OSError as e:
        avisos.append(f"No pude escribir en data/processed ({e}). Si dice 'Permission denied', corré "
                      "'sudo chown -R $USER:$USER .' desde la raíz del proyecto y repetí.")

    print("\n--- Avisos ---")
    for a in avisos:
        print(f"* {a}")
    if not avisos:
        print("Sin avisos.")


if __name__ == "__main__":
    main()