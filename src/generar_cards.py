"""
Cards de los finalistas — Prix Online UNLP 2026.

Lee data/processed/tarjetas_finalistas.json (lo genera estadisticas_finalistas.py) y
dibuja una card vertical de 1080x1350 px por jugador (4:5, el formato más alto del
feed de Instagram). Además arma una hoja resumen con todas y un CSV con el texto
alternativo de cada imagen.

Se ejecuta desde la raíz del proyecto (la carpeta que contiene data/ y src/):

    pip install matplotlib                          # solo la primera vez
    python src/generar_cards.py                     # las 8 cards, tema oscuro
    python src/generar_cards.py --claro             # tema claro
    python src/generar_cards.py --sin-iconos        # sin los íconos de assets/icons
    python src/generar_cards.py Valeny Nicorita14   # solo algunos jugadores
    python src/generar_cards.py --crear-textos      # plantilla para editar 1.e4 / 1...c6

Opcional (todo se busca en la raíz del proyecto):
    assets/avatars/<Usuario>.png|jpg|webp   foto del jugador; sin foto se dibuja un monograma
    assets/icons/<nombre>.png|jpg|webp      íconos: berserk, reloj, rey_blanco, rey_negro (y jugadas, opcional).
                                            Sirve cualquier fondo; el script los pinta con los colores del tema.
    assets/fonts/*.ttf|otf                  tipografía (Inter); sin ella se usa DejaVu Sans
    assets/textos_cards.json                textos propios para "primera jugada" y "respuesta"

Escribe en output/cards/. No modifica data/.
"""
import argparse
import csv
import json
import logging
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # dibuja a un archivo, sin ventana: no hace falta Tk ni pantalla
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.patches import Circle, FancyBboxPatch
from PIL import Image

LANCZOS = getattr(Image, "Resampling", Image).LANCZOS

# ------------------------------------------------------------------ configuración
ANCHO, ALTO, DPI = 1080, 1350, 100      # a 100 dpi, 1 px = 0,72 pt
PT = 72 / DPI

JSON_ENTRADA = Path("data/processed/tarjetas_finalistas.json")
CARPETA_SALIDA = Path("output/cards")
CARPETA_AVATARES = Path("assets/avatars")
CARPETA_FUENTES = Path("assets/fonts")
CARPETA_ICONOS = Path("assets/icons")
ARCHIVO_TEXTOS = Path("assets/textos_cards.json")

TITULO = "PRIX ONLINE UNLP 2026"
SUBTITULO = "Clasificatorio"
CUENTA = "@clubajedrezinformatica"
FUENTE_DATOS = "Datos: API pública de Lichess"

COMA_DECIMAL = True          # 12,9 en vez de 12.9
DECIMALES_PCT = 0            # con 20-70 partidas por color, los decimales de un % son falsa precisión
TIEMPO_SIN_BERSERK = True    # el berserk deja la mitad del reloj y sin incremento: mezclarlo hace incomparables los tiempos
FUENTES_PREFERIDAS = ["Inter", "DejaVu Sans"]
PESO_SEMI = "semibold"       # configurar_fuentes() lo baja a "bold" si la fuente elegida no trae semibold (DejaVu Sans)

# Íconos: cada uno es una imagen común en assets/icons/<nombre>.png|jpg|jpeg|webp, con cualquier fondo (transparente,
# blanco, negro, o con el cuadriculado de "transparente" dibujado). El script separa el dibujo del fondo y lo pinta con
# los colores del tema, así que las mismas imágenes sirven para el tema oscuro y para el claro.
ICONOS = {
    "berserk": "tinta",          # "tinta": una sola tinta (la del texto secundario del tema)
    "jugadas": "tinta",          # opcional: sin archivo, "Jugadas por partida" queda sin ícono
    "reloj": "tinta",
    "rey_blanco": "pieza",       # "pieza": lo oscuro de la imagen es trazo y lo claro es relleno, con un borde fino
    "rey_negro": "pieza",
}
ICONOS_OPCIONALES = {"jugadas"}
EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".webp")
# Hasta 64 px las etiquetas entran a 26 px con Inter y con DejaVu; con más, "Partidas con" se achica o avisa en DejaVu.
TAM_ICONO = 64               # px de lado de cada insignia (arriba a la derecha del recuadro)
GROSOR_MIN_TRAZO = 3.5       # px: grosor mínimo del trazo en los íconos de una tinta; si es más fino se engrosa (0 = no tocar)
MAX_REFUERZO = 0.75          # px máximos que se agregan por lado; más que eso empasta los detalles del dibujo
REYES_EN_APERTURAS = True    # también en "Primera jugada" (rey blanco) y "Respuesta a 1.e4" (rey negro)

# Colores: los de la paleta de referencia de la guía de visualización (superficies, tintas y azul 1 de la serie).
# Un solo matiz de acento para todos los datos; el texto va siempre en tintas, nunca en el color del dato.
TEMAS = {
    "oscuro": {
        "plano": "#0d0d0d", "panel": "#1a1a19", "linea": "#2c2c2a",
        "tinta": "#f0efec", "tinta2": "#c3c2b7",
        "acento": "#3987e5", "pista": "#0d366b", "monograma": "#2c2c2a",
        "pieza_blanca": "#f0efec", "pieza_negra": "#0d0d0d", "pieza_borde": "#898781",
    },
    "claro": {
        "plano": "#f9f9f7", "panel": "#fcfcfb", "linea": "#e1e0d9",
        "tinta": "#0b0b0b", "tinta2": "#52514e",
        "acento": "#2a78d6", "pista": "#cde2fb", "monograma": "#e1e0d9",
        "pieza_blanca": "#ffffff", "pieza_negra": "#1a1a19", "pieza_borde": "#52514e",
    },
}


# ------------------------------------------------------------------ datos -> textos
def num(x, dec=0):
    """Número con coma decimal y redondeo 'de escuela' (el 0,5 sube); None -> raya."""
    if x is None:
        return "—"
    q = Decimal(1).scaleb(-dec)                      # 1, 0.1, 0.01...
    s = str(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP))
    return s.replace(".", ",") if COMA_DECIMAL else s


def porcentaje(k, n, respaldo=None):
    """% exacto desde los conteos (k de n). Si faltan, usa el que trae el JSON (que ya viene redondeado)."""
    if k is not None and n:
        return 100 * k / n
    return respaldo


def total_desde(k, pct):
    """Total n tal que k/n coincide con pct (1 decimal). None si no hay una única solución."""
    if not k or pct is None:
        return None
    candidatos = [n for n in range(k, 500) if round(100 * k / n, 1) == round(pct, 1)]
    return candidatos[0] if len(candidatos) == 1 else None


def iniciales(usuario):
    """'FernandoPoratto' -> 'FP'; 'MTJRFAN2' -> 'MT'; 'Valeny' -> 'VA'."""
    limpio = re.sub(r"\d+", "", usuario)
    partes = re.findall(r"[A-ZÁÉÍÓÚÑ]+(?![a-záéíóúñ])|[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+|[a-záéíóúñ]+", limpio)
    if len(partes) >= 2:
        return (partes[0][0] + partes[1][0]).upper()
    return (partes[0][:2] if partes else usuario[:2]).upper()


def preparar(j, extra=None):
    """Fila del JSON -> textos listos para dibujar. No dibuja nada (se puede probar aparte)."""
    extra = extra or {}
    b, n = j.get("blancas") or {}, j.get("negras") or {}
    partidas, fechas = j.get("partidas"), j.get("fechas_con_partidas")
    if partidas and fechas:
        contexto = f"{partidas} partidas en {fechas} fechas"
    else:
        contexto = f"{partidas} partidas" if partidas else ""

    bp = porcentaje(j.get("partidas_con_berserk"), partidas, j.get("berserk_pct"))
    if j.get("partidas_con_berserk") is not None and partidas:
        sub_bers = f"{j['partidas_con_berserk']} de {partidas} partidas"
    else:
        sub_bers = ""

    if TIEMPO_SIN_BERSERK and j.get("seg_por_jugada_sin_berserk") is not None:
        seg, sub_seg = j["seg_por_jugada_sin_berserk"], "sin berserk"
    else:
        seg, sub_seg = j.get("seg_por_jugada"), "en promedio"

    def victorias(d):
        p = porcentaje(d.get("victorias"), d.get("partidas"), d.get("pct_victorias"))
        hay_conteos = d.get("victorias") is not None and d.get("partidas")
        sub = f"{d['victorias']} de {d['partidas']} partidas" if hay_conteos else ""
        return {"val": num(p, DECIMALES_PCT), "frac": None if p is None else p / 100, "sub": sub}

    # primera jugada con blancas
    pj = j.get("primera_jugada_blancas") or {}
    if pj.get("jugada"):
        k = pj.get("partidas")
        if k is not None and b.get("partidas"):
            sub_pj = f"{k} de {b['partidas']} partidas con blancas"
        else:
            sub_pj = f"{num(pj.get('pct'), DECIMALES_PCT)} % de sus partidas con blancas"
        val_pj = f"1.{pj['jugada']}"
    else:
        val_pj, sub_pj = "—", ""

    # respuesta de las negras a 1.e4
    r = j.get("respuesta_a_1e4") or {}
    if r.get("jugada"):
        total = r.get("total") or total_desde(r.get("partidas"), r.get("pct"))
        if r.get("partidas") is not None and total:
            sub_r = f"{r['partidas']} de {total} partidas contra 1.e4"
        else:
            sub_r = f"{num(r.get('pct'), DECIMALES_PCT)} % de las veces contra 1.e4"
        val_r = f"1…{r['jugada']}"
    else:
        val_r, sub_r = "—", ""

    return {
        "usuario": j["usuario"],
        "contexto": contexto,
        "puntos": num(j.get("puntos_arena"), 0),
        "berserk": {"val": num(bp, DECIMALES_PCT), "frac": None if bp is None else bp / 100, "sub": sub_bers},
        "jugadas": {"val": num(j.get("jugadas_por_partida"), 1), "sub": "en promedio"},
        "segundos": {"val": num(seg, 1), "sub": sub_seg},
        "blancas": victorias(b),
        "negras": victorias(n),
        "primera": {"val": extra.get("primera", val_pj), "sub": extra.get("primera_sub", sub_pj)},
        "respuesta": {"val": extra.get("respuesta", val_r), "sub": extra.get("respuesta_sub", sub_r)},
    }


def texto_alternativo(f):
    """Descripción para el texto alternativo de Instagram: lo que dice la imagen, en palabras."""
    def con_sub(v):
        return f"{v['val']} % ({v['sub']})" if v["sub"] else f"{v['val']} %"
    partes = [f"Card de estadísticas de {f['usuario']} en el clasificatorio del Prix Online UNLP 2026.",
              f"{f['puntos']} puntos" + (f" en {f['contexto']}." if f["contexto"] else "."),
              f"Berserk en el {con_sub(f['berserk'])}.",
              f"{f['jugadas']['val']} jugadas por partida y {f['segundos']['val']} segundos por jugada"
              f" ({f['segundos']['sub']}).",
              f"Victorias con blancas: {con_sub(f['blancas'])}. Victorias con negras: {con_sub(f['negras'])}.",
              f"Primera jugada con blancas: {f['primera']['val']}. "
              f"Respuesta con negras a 1.e4: {f['respuesta']['val'].replace('…', '...')}."]
    return " ".join(partes)


# ------------------------------------------------------------------ íconos
def _luminancia(im):
    rgb = np.asarray(im.convert("RGB"), dtype=np.float64)
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def _hex_a_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64) / 255


def _contraste(a, b):
    """Contraste WCAG entre dos colores hex (1 a 21)."""
    def lum(h):
        c = _hex_a_rgb(h)
        c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    claro, oscuro = sorted((lum(a), lum(b)), reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


def _dilatar(a, r):
    """Máximo de `a` dentro de un disco de radio r px."""
    if r <= 0:
        return a.copy()
    h, w = a.shape
    p = np.pad(a, r)
    salida = a.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                np.maximum(salida, p[r + dy:r + dy + h, r + dx:r + dx + w], out=salida)
    return salida


def _conectado_al_borde(libre):
    """True en los píxeles de `libre` (bool) a los que se llega desde el borde de la imagen, moviéndose en las
    cuatro direcciones por píxeles libres. Inundación propia: no depende de Pillow ni de su versión."""
    h, w = libre.shape
    ok = bytearray(libre.astype(np.uint8).ravel().tobytes())
    visto = bytearray(h * w)
    pila = []
    semillas = [x for x in range(w)] + [(h - 1) * w + x for x in range(w)]
    semillas += [y * w for y in range(h)] + [y * w + w - 1 for y in range(h)]
    for i in semillas:
        if ok[i] and not visto[i]:
            visto[i] = 1
            pila.append(i)
    n = h * w
    while pila:
        i = pila.pop()
        col = i % w
        for j, valido in ((i - 1, col > 0), (i + 1, col < w - 1), (i - w, i >= w), (i + w, i + w < n)):
            if valido and ok[j] and not visto[j]:
                visto[j] = 1
                pila.append(j)
    return np.frombuffer(bytes(visto), dtype=np.uint8).reshape(h, w).astype(bool)


def mascara_tinta(im):
    """Cuánta tinta hay en cada píxel (0..1). Con transparencia real, lo opaco es el dibujo. Sin ella, se compara con
    el fondo (el color del borde de la imagen): sirve tinta oscura sobre fondo claro y al revés, y un cuadriculado de
    "transparente" cuenta como fondo. Devuelve None si no logra separar el dibujo del fondo."""
    alfa = np.asarray(im.convert("RGBA"), dtype=np.float64)[..., 3] / 255
    if (alfa < 0.98).mean() > 0.01:
        return alfa
    L = _luminancia(im)
    k = max(2, min(L.shape) // 100)
    borde = np.concatenate([L[:k].ravel(), L[-k:].ravel(), L[:, :k].ravel(), L[:, -k:].ravel()])
    if np.median(borde) >= 128:                         # fondo claro, tinta oscura
        fondo, tinta = np.percentile(borde, 5), np.percentile(L, 0.2)
        if fondo - tinta < 40:
            return None
        m = (fondo - L) / (fondo - tinta)
    else:                                               # fondo oscuro, tinta clara
        fondo, tinta = np.percentile(borde, 95), np.percentile(L, 99.8)
        if tinta - fondo < 40:
            return None
        m = (L - fondo) / (tinta - fondo)
    m = np.clip(m, 0, 1)
    fuerte = m[m >= 0.5]
    if fuerte.size:
        # El trazo suele quedar ~5 % por debajo del extremo con el que se midió; se lo lleva a tinta plena (1,0) tomando
        # como nivel el valor más repetido del trazo. Sin esto, el dibujo sale apenas translúcido.
        cuentas, cortes = np.histogram(fuerte, bins=50, range=(0.5, 1.0))
        m = np.clip(m / max(cortes[cuentas.argmax()] + 0.005, 0.5), 0, 1)
    m[m < 0.10] = 0                                     # ruido de la compresión JPG
    return m


def relleno_encerrado(tinta):
    """Píxeles sin tinta que la tinta deja encerrados: el relleno de una pieza dibujada solo con contorno. Si el
    contorno tiene una rendija, se cierra un poco y se reintenta."""
    dura = tinta >= 0.5
    mejor = np.zeros_like(dura)
    for cierre in (0, 3, 6):
        base = dura if cierre == 0 else _dilatar(dura.astype(np.float64), cierre) >= 0.5
        exterior = _conectado_al_borde(~base)
        if cierre:
            exterior = _dilatar(exterior.astype(np.float64), cierre) >= 0.5   # el halo de afuera no es relleno
        relleno = ~dura & ~exterior
        if relleno.sum() > mejor.sum():
            mejor = relleno
        if relleno.sum() >= 0.5 * dura.sum():
            break
    return mejor


def analizar_icono(im, modo):
    """Imagen -> {'forma', 'tinta'}: dos arreglos 0..1, recortados al dibujo y en un cuadrado. `forma` es cuánto
    ocupa cada píxel; `tinta` cuánto es trazo (1) y cuánto es relleno (0). None si no se puede."""
    im = im.convert("RGBA")
    im.thumbnail((400, 400), LANCZOS)
    m = mascara_tinta(im)
    if m is None:
        return None
    if modo == "pieza":
        alfa = np.asarray(im, dtype=np.float64)[..., 3] / 255
        if (alfa < 0.98).mean() > 0.01:                 # con transparencia real: lo oscuro es trazo, lo claro relleno
            forma, tinta = alfa, 1 - _luminancia(im) / 255
        else:                                           # sin ella: el interior del contorno es relleno
            forma, tinta = np.maximum(m, relleno_encerrado(m).astype(np.float64)), m
    else:
        forma, tinta = m, np.ones_like(m)
    ys, xs = np.where(forma > 0.25)                     # el ruido de un JPG de baja calidad no ensancha el recorte
    if len(ys) == 0:
        return None
    forma, tinta = (a[ys.min():ys.max() + 1, xs.min():xs.max() + 1] for a in (forma, tinta))
    h, w = forma.shape
    lado = max(h, w)
    pad = (((lado - h) // 2, lado - h - (lado - h) // 2), ((lado - w) // 2, lado - w - (lado - w) // 2))
    return {"forma": np.pad(forma, pad), "tinta": np.pad(tinta, pad)}


def grosor_trazo(forma, ss):
    """Grosor medio del trazo en px finales: 2 * área / perímetro de la forma binarizada (`forma` está a `ss` veces
    el tamaño final). Una línea de grosor t y largo L da 2tL / 2L = t; una silueta llena da un valor grande."""
    m = forma >= 0.5
    p = np.pad(m, 1)
    borde = m & ~(p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:])
    return 2 * m.sum() / max(int(borde.sum()), 1) / ss


def pintar_icono(ico, T, lado, ss=4, borde_px=2, margen=3, refuerzo=None):
    """RGBA (lado x lado, uint8) del ícono con los colores del tema. Se dibuja a `ss` veces el tamaño y se promedia,
    así los bordes quedan suaves y el recuadro de salida cae exacto sobre la grilla de píxeles. En los íconos de una
    tinta, `refuerzo` (px finales por lado) engrosa el trazo: un trazo de 2 px se vuelve una mancha en el celular.
    Sin indicarlo, se calcula para llegar a GROSOR_MIN_TRAZO sin pasar de MAX_REFUERZO."""
    clave = (lado, refuerzo, GROSOR_MIN_TRAZO, MAX_REFUERZO,
             T["tinta2"], T["panel"], T["pieza_blanca"], T["pieza_negra"], T["pieza_borde"])
    cache = ico.setdefault("_cache", {})
    if clave in cache:
        return cache[clave]
    n, interior = lado * ss, (lado - 2 * margen) * ss

    def al_lienzo(a):
        im = Image.fromarray((np.clip(a, 0, 1) * 255).round().astype(np.uint8)).resize((interior, interior), LANCZOS)
        lienzo = np.zeros((n, n))
        o = margen * ss
        lienzo[o:o + interior, o:o + interior] = np.asarray(im) / 255
        return lienzo

    forma, tinta = al_lienzo(ico["forma"]), al_lienzo(ico["tinta"])
    if ico["modo"] == "pieza":
        claro, oscuro, borde = (_hex_a_rgb(T[k]) for k in ("pieza_blanca", "pieza_negra", "pieza_borde"))
        color = claro * (1 - tinta[..., None]) + oscuro * tinta[..., None]
        # El borde fino separa a la pieza del panel solo cuando hace falta (negro sobre un panel oscuro).
        con_borde = _contraste(T["pieza_negra"], T["panel"]) < 3
        halo = _dilatar(forma, borde_px * ss) * (1 - forma) if con_borde else np.zeros_like(forma)
        alfa = forma + halo
        premult = color * forma[..., None] + borde * halo[..., None]
    else:
        if refuerzo is None:
            fino = GROSOR_MIN_TRAZO - grosor_trazo(forma, ss)
            refuerzo = min(MAX_REFUERZO, fino / 2) if fino > 0 else 0.0
        alfa = _dilatar(forma, round(refuerzo * ss)) if refuerzo > 0 else forma
        premult = _hex_a_rgb(T["tinta2"]) * alfa[..., None]
    bajar = lambda a: a.reshape(lado, ss, lado, ss, -1).mean(axis=(1, 3))
    a_f, p_f = bajar(alfa[..., None]), bajar(premult)
    rgb = np.divide(p_f, a_f, out=np.zeros_like(p_f), where=a_f > 1e-6)
    rgba = (np.dstack([rgb, a_f]) * 255).round().clip(0, 255).astype(np.uint8)
    cache[clave] = rgba
    return rgba


def cargar_iconos(carpeta=CARPETA_ICONOS):
    """Lee los íconos de la carpeta. Devuelve ({nombre: ícono}, [avisos]). Sin carpeta o sin archivos: ({}, [])."""
    catalogo, avisos = {}, []
    if not carpeta.is_dir():
        return catalogo, avisos
    archivos = {}
    for r in sorted(carpeta.iterdir()):
        if r.is_file() and r.suffix.lower() in EXTENSIONES_IMAGEN:
            archivos.setdefault(r.stem.lower(), r)
    for nombre, modo in ICONOS.items():
        ruta = archivos.get(nombre)
        if ruta is None:
            continue
        try:
            with Image.open(ruta) as im:
                ico = analizar_icono(im, modo)
        except Exception as e:                           # archivo corrupto, formato raro, imagen gigante...
            avisos.append(f"no pude leer {ruta} ({type(e).__name__}); sigo sin ese ícono")
            continue
        if ico is None:
            avisos.append(f"no pude separar el dibujo del fondo en {ruta}; sigo sin ese ícono")
            continue
        ico["modo"] = modo
        catalogo[nombre] = ico
    return catalogo, avisos


# ------------------------------------------------------------------ dibujo
class Lienzo:
    """Un lienzo de 1080x1350 px donde las coordenadas son píxeles (y crece hacia abajo)."""

    def __init__(self, T, catalogo=None):
        self.T = T
        self.catalogo = catalogo or {}
        self.insignias = []                       # (nombre, x0, y0, x1, y1) de cada ícono dibujado
        self.avisos = []
        self.fig = plt.figure(figsize=(ANCHO / DPI, ALTO / DPI), dpi=DPI, facecolor=T["plano"])
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, ANCHO)
        self.ax.set_ylim(ALTO, 0)
        self.ax.set_autoscale_on(False)
        self.ax.axis("off")
        self.rend = self.fig.canvas.get_renderer()

    # --- primitivas
    def rect(self, x, y, w, h, color, r=0, borde=None, lw=0, z=2):
        r = min(r, w / 2, h / 2)
        self.ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                         fc=color, ec=borde or "none", lw=lw * PT, zorder=z))

    def linea(self, x0, y0, x1, y1):
        self.ax.plot([x0, x1], [y0, y1], color=self.T["linea"], lw=1.5 * PT, solid_capstyle="butt", zorder=2)

    def ancho(self, t):
        return t.get_window_extent(self.rend).width

    def texto(self, x, y, s, px, color, peso="normal", ha="left", max_ancho=None, minimo=18, z=6):
        """Texto con la línea de base en y. Si max_ancho está, achica la letra hasta que entre."""
        t = self.ax.text(x, y, str(s).replace("$", r"\$"), fontsize=px * PT, color=color,
                         fontweight=PESO_SEMI if peso == "semibold" else peso, ha=ha, va="baseline", zorder=z)
        if max_ancho:
            while self.ancho(t) > max_ancho and px > minimo:
                px -= 2
                t.set_fontsize(px * PT)
            if self.ancho(t) > max_ancho + 1:
                self.avisos.append(f"no entra ni con letra de {px} px: {s!r}")
        return t

    def etiqueta(self, x, y, s, max_ancho, lineas, px=26):
        """Etiqueta en hasta `lineas` líneas. Respeta los saltos '\\n' y, si hace falta, corta por palabras."""
        filas = []
        for tramo in s.split("\n"):
            actual = ""
            for p in tramo.split():
                prueba = f"{actual} {p}".strip()
                t = self.ax.text(0, 0, prueba, fontsize=px * PT)
                entra = self.ancho(t) <= max_ancho
                t.remove()
                if entra or not actual:
                    actual = prueba
                else:
                    filas.append(actual)
                    actual = p
            filas.append(actual)
        if len(filas) > lineas:
            self.avisos.append(f"etiqueta demasiado larga para {lineas} línea(s): {s!r}")
        for i, fila in enumerate(filas[:lineas]):
            self.texto(x, y + 30 * i, fila, px, self.T["tinta2"], max_ancho=max_ancho)
        return min(len(filas), lineas)

    def pieza(self, cx, cy, color):
        T = self.T
        relleno = T["pieza_blanca"] if color == "blancas" else T["pieza_negra"]
        self.ax.add_patch(Circle((cx, cy), 11, fc=relleno, ec=T["pieza_borde"], lw=2 * PT, zorder=6))

    def icono(self, nombre, x, y, lado):
        """Dibuja un ícono del catálogo con su esquina superior izquierda en (x, y) (px enteros)."""
        rgba = pintar_icono(self.catalogo[nombre], self.T, lado)
        self.ax.imshow(rgba, extent=(x, x + lado, y + lado, y), zorder=6, interpolation="nearest", aspect="auto")
        self.ax.set_xlim(0, ANCHO)
        self.ax.set_ylim(ALTO, 0)
        self.insignias.append((nombre, x, y, x + lado, y + lado))

    def medidor(self, x, y, w, frac, alto=14):
        """Barra de porcentaje: pista y relleno del mismo matiz; el relleno mide exactamente frac * w."""
        T = self.T
        self.rect(x, y, w, alto, T["pista"], r=alto / 2, z=3)
        if frac and frac > 0:
            wf = w * min(frac, 1.0)
            self.rect(x, y, wf, alto, T["acento"], r=alto / 2, z=4)

    def avatar(self, cx, cy, r, usuario, foto):
        T = self.T
        if foto is not None:
            im = self.ax.imshow(foto, extent=(cx - r, cx + r, cy + r, cy - r), zorder=4, aspect="auto")
            im.set_clip_path(Circle((cx, cy), r, transform=self.ax.transData))
            self.ax.set_xlim(0, ANCHO)
            self.ax.set_ylim(ALTO, 0)
        else:
            self.ax.add_patch(Circle((cx, cy), r, fc=T["monograma"], ec="none", zorder=4))
            self.texto(cx, cy + 0.727 * 84 / 2, iniciales(usuario), 84, T["tinta"], "semibold", ha="center")
        self.ax.add_patch(Circle((cx, cy), r + 12, fill=False, ec=T["acento"], lw=3 * PT, zorder=5))

    def tile(self, x, y, w, h, etiqueta, d, unidad="", icono=None, pieza=None, lineas=1, valor_px=68, fijo_sub=None):
        """Dato con etiqueta arriba, valor grande, medidor opcional y detalle abajo. El ícono va de insignia arriba
        a la derecha, alineado con el final del medidor; si falta ese archivo, `pieza` dibuja el círculo blanco o
        negro de la versión anterior a la izquierda de la etiqueta."""
        T, pad = self.T, 26
        self.rect(x, y, w, h, T["panel"], r=24, borde=T["linea"], lw=1.5, z=2)
        xi, ancho = x + pad, w - 2 * pad
        ey = y + 44
        caja_icono = None
        if icono in self.catalogo:
            ix, iy = round(x + w - pad - TAM_ICONO), round(y + 24)
            self.icono(icono, ix, iy, TAM_ICONO)
            caja_icono = (ix, iy + TAM_ICONO)                 # borde izquierdo y borde inferior de la insignia
            self.etiqueta(xi, ey, etiqueta, ancho - TAM_ICONO - 12, lineas)
        elif pieza:
            self.pieza(xi + 11, ey - 9, pieza)
            self.etiqueta(xi + 34, ey, etiqueta, ancho - 34, lineas)
        else:
            self.etiqueta(xi, ey, etiqueta, ancho, lineas)
        vy = ey + 30 * (lineas - 1) + 24 + 0.727 * valor_px
        tv = self.texto(xi, vy, d["val"], valor_px, T["tinta"], "semibold", max_ancho=ancho, minimo=30)
        if caja_icono:
            # Un valor largo (p. ej. un texto propio "1.g3 · Húngara") no puede pasar por debajo de la insignia sin
            # tocarla: si llega a su altura y a su columna, se achica hasta que quede libre.
            px = tv.get_fontsize() / PT
            while px > 30 and vy - 0.727 * px < caja_icono[1] + 8 and xi + self.ancho(tv) > caja_icono[0] - 12:
                px -= 2
                tv.set_fontsize(px * PT)
            if vy - 0.727 * px < caja_icono[1] + 8 and xi + self.ancho(tv) > caja_icono[0] - 12:
                self.avisos.append(f"el valor tapa el ícono: {d['val']!r}")
        if unidad and d["val"] != "—":
            tu = self.texto(xi + self.ancho(tv) + 8, vy, unidad, round(valor_px * 0.5), T["tinta2"], "semibold")
            if xi + self.ancho(tv) + 8 + self.ancho(tu) > x + w - pad + 1:
                self.avisos.append(f"el valor y la unidad no entran en el recuadro: {d['val']} {unidad}")
        if d.get("frac") is not None:
            self.medidor(xi, vy + 22, ancho, d["frac"])
        if d.get("sub"):
            sy = fijo_sub if fijo_sub else vy + 40
            self.texto(xi, sy, d["sub"], 24, T["tinta2"], max_ancho=ancho, minimo=18)

    def verificar(self):
        """Red de seguridad: ningún texto puede salirse del panel."""
        for t in self.ax.texts:
            bb = t.get_window_extent(self.rend)
            if bb.x1 > ANCHO - 60 or bb.x0 < 60:
                self.avisos.append(f"texto fuera del margen: {t.get_text()!r}")

    def guardar(self, ruta):
        self.verificar()
        self.fig.savefig(ruta, dpi=DPI, facecolor=self.T["plano"])
        plt.close(self.fig)


def dibujar_card(f, T, foto=None, iconos=None):
    """Dibuja la card de un jugador y devuelve el lienzo (con sus avisos de maquetación)."""
    c = Lienzo(T, iconos)
    x0, x1, gap = 84, 996, 20
    c.rect(36, 36, 1008, 1278, T["panel"], r=40, borde=T["linea"], lw=1.5, z=1)

    # encabezado: marca de tablero 2x2, título y subtítulo
    for dx, dy, col in ((0, 0, "acento"), (1, 0, "pista"), (0, 1, "pista"), (1, 1, "acento")):
        c.rect(x0 + dx * 13, 88 + dy * 13, 13, 13, T[col], z=3)
    c.texto(x0 + 42, 112, TITULO, 24, T["tinta"], "semibold")
    c.texto(x1, 112, SUBTITULO, 24, T["tinta2"], ha="right")
    c.linea(x0, 142, x1, 142)

    # identidad: avatar, nombre y la cifra principal (una sola por card)
    r = 120
    cx, cy = x0 + r + 12, 292                  # el aro (r + 12) queda alineado con el margen izquierdo
    c.avatar(cx, cy, r, f["usuario"], foto)
    xt = cx + r + 12 + 40
    ancho_col = x1 - xt
    c.texto(xt, 206, f["usuario"], 62, T["tinta"], "semibold", max_ancho=ancho_col, minimo=32)
    c.texto(xt, 244, f["contexto"], 26, T["tinta2"], max_ancho=ancho_col)
    c.texto(xt, 290, "Puntos tomados", 26, T["tinta2"])
    c.texto(xt, 414, f["puntos"], 144, T["tinta"], "semibold", max_ancho=ancho_col, minimo=60)

    # fila 1: ritmo de juego (3 recuadros)
    y = 460
    w3 = (x1 - x0 - 2 * gap) / 3
    h1 = 244
    sub_y = y + 218                            # el detalle queda a la misma altura en los tres
    c.tile(x0, y, w3, h1, "Partidas con\nberserk", f["berserk"], "%", icono="berserk", lineas=2, fijo_sub=sub_y)
    c.tile(x0 + w3 + gap, y, w3, h1, "Jugadas por\npartida", f["jugadas"], icono="jugadas", lineas=2, fijo_sub=sub_y)
    c.tile(x0 + 2 * (w3 + gap), y, w3, h1, "Segundos\npor jugada", f["segundos"], "s", icono="reloj", lineas=2,
           fijo_sub=sub_y)

    # fila 2: victorias según el color
    y += h1 + gap
    w2 = (x1 - x0 - gap) / 2
    h2 = 216
    c.tile(x0, y, w2, h2, "Victorias con blancas", f["blancas"], "%", icono="rey_blanco", pieza="blancas",
           fijo_sub=y + 188)
    c.tile(x0 + w2 + gap, y, w2, h2, "Victorias con negras", f["negras"], "%", icono="rey_negro", pieza="negras",
           fijo_sub=y + 188)

    # fila 3: repertorio (solo la primera jugada, como se decidió)
    y += h2 + gap
    h3 = 200
    c.tile(x0, y, w2, h3, "Primera jugada", f["primera"], icono="rey_blanco" if REYES_EN_APERTURAS else None,
           pieza="blancas", valor_px=84)
    c.tile(x0 + w2 + gap, y, w2, h3, "Respuesta a 1.e4", f["respuesta"],
           icono="rey_negro" if REYES_EN_APERTURAS else None, pieza="negras", valor_px=84)

    # pie
    c.linea(x0, 1212, x1, 1212)
    c.texto(x0, 1262, CUENTA, 26, T["tinta"], "semibold")
    c.texto(x1, 1262, FUENTE_DATOS, 22, T["tinta2"], ha="right")
    return c


# ------------------------------------------------------------------ entradas y salidas
def configurar_fuentes():
    """Registra las fuentes de assets/fonts y usa la primera disponible de FUENTES_PREFERIDAS."""
    global PESO_SEMI
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)   # sin avisos de "findfont"
    if CARPETA_FUENTES.is_dir():
        for ruta in list(CARPETA_FUENTES.glob("*.ttf")) + list(CARPETA_FUENTES.glob("*.otf")):
            font_manager.fontManager.addfont(str(ruta))
    entradas = font_manager.fontManager.ttflist

    def pesos_de(nombre):
        pesos = set()
        for f in entradas:
            if f.name == nombre:
                p = f.weight
                pesos.add(font_manager.weight_dict.get(p, 400) if isinstance(p, str) else int(p))
        return pesos

    elegida = "DejaVu Sans"
    for nombre in FUENTES_PREFERIDAS:
        pesos = pesos_de(nombre)
        if not pesos:
            continue                                   # no está instalada
        if any(p >= 550 for p in pesos):
            elegida = nombre
            break
        # Una fuente variable (un solo archivo con todos los pesos) llega a matplotlib solo con el peso normal:
        # las cifras saldrían flacas. Mejor avisar y usar la siguiente.
        print(f"AVISO: la fuente {nombre!r} solo trae el peso normal (¿es la versión variable?). "
              f"Poné en {CARPETA_FUENTES}/ los archivos estáticos Regular y SemiBold. Uso la siguiente de la lista.")
    # Inter trae semibold (600); DejaVu Sans solo regular y bold: en ese caso se pide bold.
    PESO_SEMI = "semibold" if any(550 <= p <= 650 for p in pesos_de(elegida)) else "bold"
    plt.rcParams["font.family"] = elegida
    return elegida


def buscar_foto(usuario):
    if not CARPETA_AVATARES.is_dir():
        return None
    for ruta in sorted(CARPETA_AVATARES.iterdir()):
        if ruta.stem.lower() == usuario.lower() and ruta.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            return ruta
    return None


def cargar_foto(ruta, lado=540):
    """Recorta al centro en cuadrado y devuelve un arreglo RGB."""
    im = Image.open(ruta).convert("RGB")
    w, h = im.size
    m = min(w, h)
    izq, arr = (w - m) // 2, (h - m) // 2
    im = im.crop((izq, arr, izq + m, arr + m)).resize((lado, lado), getattr(Image, "Resampling", Image).LANCZOS)
    return np.asarray(im)


def cargar_textos():
    """{usuario en minúsculas: {primera, respuesta, ...}} desde assets/textos_cards.json, si existe."""
    if not ARCHIVO_TEXTOS.exists():
        return {}
    try:
        crudo = json.loads(ARCHIVO_TEXTOS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"{ARCHIVO_TEXTOS} no es un JSON válido: {e}")
    return {str(k).lower(): v for k, v in crudo.items() if isinstance(v, dict)}


def crear_plantilla_textos(jugadores):
    if ARCHIVO_TEXTOS.exists():
        sys.exit(f"{ARCHIVO_TEXTOS} ya existe; no lo piso. Editalo a mano o borralo para generar uno nuevo.")
    plantilla = {}
    for j in jugadores:
        f = preparar(j)
        plantilla[j["usuario"]] = {"primera": f["primera"]["val"], "respuesta": f["respuesta"]["val"]}
    ARCHIVO_TEXTOS.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVO_TEXTOS.write_text(json.dumps(plantilla, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Creé {ARCHIVO_TEXTOS} con los textos actuales. Editá los que quieras (p. ej. \"1.g3 · Húngara\") "
          f"y volvé a correr el script.")


def hoja_resumen(rutas, destino, columnas=4, ancho=540, alto=675):
    imgs = [Image.open(r).convert("RGB") for r in rutas]
    filas = (len(imgs) + columnas - 1) // columnas
    hoja = Image.new("RGB", (columnas * ancho, filas * alto), "#0d0d0d")
    remuestreo = getattr(Image, "Resampling", Image).LANCZOS
    for i, im in enumerate(imgs):
        hoja.paste(im.resize((ancho, alto), remuestreo), ((i % columnas) * ancho, (i // columnas) * alto))
    hoja.save(destino)


def main():
    ap = argparse.ArgumentParser(description="Genera las cards de los finalistas a partir del JSON de estadísticas.")
    ap.add_argument("usuarios", nargs="*", help="solo estos jugadores (por defecto, todos los del JSON)")
    ap.add_argument("--claro", action="store_true", help="tema claro (por defecto, oscuro)")
    ap.add_argument("--json", type=Path, default=JSON_ENTRADA, help=f"entrada (por defecto {JSON_ENTRADA})")
    ap.add_argument("--salida", type=Path, default=CARPETA_SALIDA, help=f"carpeta de salida (por defecto {CARPETA_SALIDA})")
    ap.add_argument("--crear-textos", action="store_true", help="crea assets/textos_cards.json para editar los textos")
    ap.add_argument("--sin-iconos", action="store_true", help=f"no usa los íconos de {CARPETA_ICONOS}/")
    args = ap.parse_args()

    if not args.json.exists():
        sys.exit(f"No encuentro {args.json}. Corré primero estadisticas_finalistas.py desde la raíz del proyecto.")
    try:
        jugadores = json.loads(args.json.read_text(encoding="utf-8"))["jugadores"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        sys.exit(f"{args.json} no tiene el formato esperado ({e!r}). Volvé a generarlo con estadisticas_finalistas.py.")

    if args.crear_textos:
        crear_plantilla_textos(jugadores)
        return

    numerados = list(enumerate(jugadores, 1))     # el número de archivo sigue el orden por puntos
    if args.usuarios:
        pedidos = {u.lower() for u in args.usuarios}
        numerados = [(i, j) for i, j in numerados if j["usuario"].lower() in pedidos]
        faltan = pedidos - {j["usuario"].lower() for _, j in numerados}
        if faltan:
            sys.exit(f"No están en el JSON: {', '.join(sorted(faltan))}")

    tema = TEMAS["claro" if args.claro else "oscuro"]
    fuente = configurar_fuentes()
    extras = cargar_textos()
    catalogo, avisos_iconos = ({}, []) if args.sin_iconos else cargar_iconos()
    try:
        args.salida.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        sys.exit(f"No pude crear {args.salida} ({e}). Si dice 'Permission denied', corré "
                 "'sudo chown -R $USER:$USER .' desde la raíz del proyecto y repetí.")

    print(f"Tipografía: {fuente}" + ("" if fuente == "Inter" else "  (para el aspecto de la muestra, dejá Inter en assets/fonts/)"))
    if args.sin_iconos:
        print("Íconos: desactivados (--sin-iconos)")
    elif catalogo:
        print("Íconos: " + ", ".join(catalogo))
        faltan = [n for n in ICONOS if n not in catalogo and n not in ICONOS_OPCIONALES]
        if faltan:
            print(f"  sin archivo en {CARPETA_ICONOS}/: {', '.join(faltan)}")
    else:
        print(f"Íconos: ninguno (van en {CARPETA_ICONOS}/ como {', '.join(ICONOS)}, en .png o .jpg)")
    rutas, filas_alt, hubo_avisos = [], [], bool(avisos_iconos)
    for a in avisos_iconos:
        print(f"AVISO: {a}")
    for pos, j in numerados:
        f = preparar(j, extras.get(j["usuario"].lower()))
        ruta_foto = buscar_foto(j["usuario"])
        foto = cargar_foto(ruta_foto) if ruta_foto else None
        lienzo = dibujar_card(f, tema, foto, catalogo)
        ruta = args.salida / f"card_{pos:02d}_{j['usuario']}.png"
        avisos = list(lienzo.avisos)
        lienzo.guardar(ruta)
        avisos += [a for a in lienzo.avisos if a not in avisos]
        rutas.append(ruta)
        filas_alt.append([j["usuario"], ruta.name, texto_alternativo(f)])
        print(f"  {ruta.name}" + ("" if foto is None else "  (con foto)"))
        for a in avisos:
            hubo_avisos = True
            print(f"    AVISO: {a}")

    if len(rutas) > 1:
        hoja_resumen(rutas, args.salida / "hoja_resumen.png")
    with open(args.salida / "textos_alternativos.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["usuario", "archivo", "texto_alternativo"])
        w.writerows(filas_alt)
    print(f"\nListo: {len(rutas)} card(s) en {args.salida}/ (más hoja_resumen.png y textos_alternativos.csv)."
          + ("\nRevisá los avisos de arriba antes de publicar." if hubo_avisos else ""))


if __name__ == "__main__":
    main()
