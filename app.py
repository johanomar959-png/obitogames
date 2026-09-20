import sqlite3
import zlib
import os
import re
import json
import time
import secrets
from urllib.parse import urljoin, urlparse
from flask import Flask, render_template, jsonify, request, abort, session, redirect

try:
    import requests as http_requests
except ImportError:
    http_requests = None

try:
    import jwt
except ImportError:
    jwt = None

app = Flask(__name__)
DB_FILE = "juegos.db"
THUMB_DIR = os.path.join("static", "thumbs", "curated")

MI_DOMINIO = ""

GOOGLE_CLIENT_ID = ""
FACEBOOK_APP_ID = ""
FACEBOOK_APP_SECRET = ""
APPLE_CLIENT_ID = ""

SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret_key.txt")
def _load_secret():
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE) as f:
            return f.read().strip()
    s = secrets.token_hex(32)
    with open(SECRET_FILE, "w") as f:
        f.write(s)
    return s
app.secret_key = _load_secret()

MANUAL_PHOTOS = {
    "Smash Karts": "https://imgs.crazygames.com/smash-karts_16x9/20260210123937/smash-karts_16x9-cover?metadata=none&quality=100&width=1200&height=630&fit=crop",
}

# ===== CURADOS (se removieron 2048, Hole.io, Paper.io 2, Agar.io por no funcionar) =====
ORIENT_CURATED = {
    "Smash Karts": "horizontal", "1v1.LOL": "horizontal", "Venge.io": "horizontal",
    "Slither.io": "auto", "Shell Shockers": "horizontal",
    "ZombsRoyale.io": "horizontal", "Skribbl.io": "horizontal", "Diep.io": "auto",
    "Krunker.io": "horizontal", "Little Big Snake": "auto",
    "EvoWars.io": "auto", "Surviv.io": "horizontal",
    "Wings.io": "horizontal", "Bonk.io": "horizontal", "Gartic Phone": "horizontal",
    "Flappy Bird": "auto", "Pac-Man": "horizontal",
    "Tetris": "auto", "Hextris": "auto",
}
HORIZ_CATS = {"accion", "disparos", "io", "conducir", "deportes", "simulacion"}

CATEGORIES_DEF = [
    {"slug": "accion", "name": "Acción", "icon": "swords"},
    {"slug": "arcade", "name": "Arcade", "icon": "gamepad"},
    {"slug": "aventuras", "name": "Aventuras", "icon": "compass"},
    {"slug": "cartas", "name": "Cartas", "icon": "cards"},
    {"slug": "clic", "name": "Clic", "icon": "click"},
    {"slug": "conducir", "name": "Conducir", "icon": "car"},
    {"slug": "deportes", "name": "Deportes", "icon": "trophy"},
    {"slug": "disparos", "name": "Disparos", "icon": "crosshair"},
    {"slug": "estrategia", "name": "Estrategia", "icon": "rook"},
    {"slug": "io", "name": ".io", "icon": "globe"},
    {"slug": "mesa", "name": "Mesa", "icon": "dice"},
    {"slug": "palabras", "name": "Palabras", "icon": "type"},
    {"slug": "puzzle", "name": "Puzzle", "icon": "puzzle"},
    {"slug": "simulacion", "name": "Simulación", "icon": "building"},
    {"slug": "trivia", "name": "Trivia", "icon": "help"},
]

CAT_MAP = {
    "action": "accion", "adventure": "aventuras", "arcade": "arcade",
    "board": "mesa", "card": "cartas", "cards": "cartas",
    "clicker": "clic", "click": "clic",
    "driving": "conducir", "racing": "conducir", "car": "conducir",
    "io": "io", ".io": "io", "multiplayer": "io",
    "puzzle": "puzzle", "skill": "arcade", "educational": "puzzle",
    "shooting": "disparos", "shooter": "disparos",
    "simulation": "simulacion", "sports": "deportes",
    "strategy": "estrategia", "trivia": "trivia", "quiz": "trivia",
    "word": "palabras", "text": "palabras", "girls": "arcade",
}

EMOJIS = {
    "accion": "⚔️", "arcade": "🕹️", "aventuras": "🗺️", "cartas": "🃏",
    "clic": "👆", "conducir": "🏎️", "deportes": "🏆", "disparos": "🎯",
    "estrategia": "♟️", "io": "🌐", "mesa": "🎲", "palabras": "🔤",
    "puzzle": "🧩", "simulacion": "🏗️", "trivia": "❓",
}

GRADIENTS = {
    "accion": "from-red-700 to-rose-950", "arcade": "from-zinc-700 to-black",
    "aventuras": "from-emerald-800 to-black", "cartas": "from-rose-800 to-black",
    "clic": "from-sky-800 to-black", "conducir": "from-orange-700 to-black",
    "deportes": "from-green-800 to-black", "disparos": "from-zinc-800 to-black",
    "estrategia": "from-indigo-900 to-black", "io": "from-red-800 to-black",
    "mesa": "from-blue-900 to-black", "palabras": "from-amber-700 to-black",
    "puzzle": "from-red-900 to-black", "simulacion": "from-lime-800 to-black",
    "trivia": "from-yellow-700 to-black",
}

# ===== CURADOS FUNCIONALES (sin 2048/Hole.io/Paper.io2/Agar.io) =====
CURATED_RAW = [
    ("Smash Karts", "io", "io", "🏎️", ["https://smashkarts.io/"], 980000, 1500000),
    ("1v1.LOL", "batalla", "disparos", "🔫", ["https://1v1.lol/"], 950000, 1400000),
    ("Venge.io", "batalla", "disparos", "🥷", ["https://venge.io/"], 900000, 1300000),
    ("Slither.io", "io", "io", "🐍", ["https://slither.io/"], 800000, 1050000),
    ("Shell Shockers", "batalla", "disparos", "🥚", ["https://shellshock.io/"], 680000, 880000),
    ("ZombsRoyale.io", "io", "io", "🧟", ["https://zombsroyale.io/"], 660000, 860000),
    ("Skribbl.io", "mente", "palabras", "✏️", ["https://skribbl.io/"], 640000, 840000),
    ("Diep.io", "io", "io", "🔵", ["https://diep.io/"], 620000, 820000),
    ("Krunker.io", "batalla", "disparos", "💀", ["https://krunker.io/"], 600000, 800000),
    ("Little Big Snake", "io", "io", "🐍", ["https://littlebigsnake.com/"], 580000, 780000),
    ("EvoWars.io", "io", "io", "⚔️", ["https://evowars.io/"], 520000, 720000),
    ("Surviv.io", "io", "io", "🪖", ["https://surviv.io/"], 500000, 700000),
    ("Wings.io", "io", "io", "✈️", ["https://wings.io/"], 480000, 680000),
    ("Bonk.io", "io", "io", "⚾", ["https://bonk.io/"], 460000, 660000),
    ("Gartic Phone", "mente", "palabras", "🎨", ["https://garticphone.com/"], 780000, 1000000),
    ("Flappy Bird", "clasicos", "arcade", "🐦", ["https://ellisonleao.github.io/clumsy-bird/"], 360000, 560000),
    ("Pac-Man", "clasicos", "arcade", "👻", ["https://shaunew.github.io/Pac-Man/"], 100000, 300000),
    ("Tetris", "clasicos", "puzzle", "🧩", ["https://chvin.github.io/tetris/"], 90000, 280000),
    ("Hextris", "clasicos", "puzzle", "⬡", ["https://hextris.github.io/hextris/"], 80000, 260000),
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0 Safari/537.36",
      "Accept": "application/json"}

MUTE_SCRIPT = """<script id="obito-audio-control">
(function(){
  var muted=false, medias=[], gains=[];
  function setMed(m){try{m.muted=muted;m.volume=muted?0:1;}catch(e){}}
  var op=HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play=function(){if(medias.indexOf(this)<0)medias.push(this);setMed(this);return op.apply(this,arguments);};
  var AC=window.AudioContext||window.webkitAudioContext;
  if(AC){
    var dg=Object.getOwnPropertyDescriptor(AC.prototype,'destination');
    if(dg&&dg.get){
      Object.defineProperty(AC.prototype,'destination',{configurable:true,get:function(){
        if(!this.__og){var g=this.createGain();g.gain.value=muted?0:1;g.connect(dg.get.call(this));this.__og=g;gains.push(g);}
        return this.__og;
      }});
    }
  }
  window.__obitoSetMuted=function(m){muted=!!m;medias.forEach(setMed);gains.forEach(function(g){try{g.gain.value=muted?0:1;}catch(e){}});};
})();
</script>"""


def con_proxy(u):
    return f"/px/{u}" if u and u.startswith("http") else u


_frame_cache = {}


def fuente_embebible(url):
    if not http_requests:
        return True
    if url in _frame_cache:
        return _frame_cache[url]
    ok = True
    try:
        r = http_requests.get(url, headers=UA, timeout=8, stream=True)
        xfo = (r.headers.get("X-Frame-Options") or "").strip().lower()
        csp = (r.headers.get("Content-Security-Policy") or "").lower()
        if xfo in ("deny", "sameorigin") or "frame-ancestors" in csp:
            ok = False
        r.close()
    except Exception:
        ok = True
    _frame_cache[url] = ok
    return ok


def orden_fuentes(base_src, check=False):
    """Auto-ordena fuentes: embebibles directas primero; bloqueadas vía proxy después."""
    if not base_src:
        return []
    seen = set()
    res = []
    def add(s):
        if s and s not in seen:
            seen.add(s)
            res.append(s)
    if not check:
        # GD/GM: directa primero (diseñadas para iframe), proxy de respaldo al final
        for s in base_src:
            add(s)
        add(con_proxy(base_src[0]))
        return res
    # Curados: verificar embebibilidad real y elegir la mejor automáticamente
    directas = [s for s in base_src if fuente_embebible(s)]
    bloqueadas = [s for s in base_src if not fuente_embebible(s)]
    for s in directas:
        add(s)
    if not directas and bloqueadas:
        add(con_proxy(bloqueadas[0]))
    for s in bloqueadas:
        add(con_proxy(s))
    return res


# ===== TENDENCIAS GAMEMONETIZE =====
TRENDING_CACHE = {"ids": [], "ts": 0}

def fetch_gamemonetize_trending(num=50):
    """Consulta la API de GameMonetize y devuelve ids ordenados por popularidad."""
    now = time.time()
    if TRENDING_CACHE["ids"] and (now - TRENDING_CACHE["ts"]) < 3600:
        return TRENDING_CACHE["ids"]
    ids = []
    if http_requests:
        try:
            r = http_requests.get(f"https://gamemonetize.com/feed.php?format=0&num={num}",
                                  headers=UA, timeout=10)
            txt = r.text
            try:
                data = json.loads(txt)
                items = data if isinstance(data, list) else \
                        data.get("games", data.get("items", data.get("channel", {}).get("item", [])))
                for it in items:
                    if isinstance(it, dict):
                        gid = it.get("id") or it.get("game_id") or ""
                        if gid:
                            ids.append(str(gid))
            except Exception:
                ids = re.findall(r'<id>(\d+)</id>', txt) or re.findall(r'"id"\s*:\s*"?(\d+)"?', txt)
        except Exception:
            ids = []
    TRENDING_CACHE["ids"] = ids
    TRENDING_CACHE["ts"] = now
    return ids


def descargar_imagen_directa(url, destino):
    if not http_requests:
        return False
    try:
        ri = http_requests.get(url, headers=UA, timeout=25)
        if ri.status_code == 200 and len(ri.content) > 15000:
            with open(destino, "wb") as f:
                f.write(ri.content)
            return True
    except Exception:
        pass
    return False


def descargar_og_image(url, destino):
    if not http_requests:
        return False
    try:
        r = http_requests.get(url, headers=UA, timeout=12, allow_redirects=True)
        html = r.text[:400000]
        pats = [
            r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
        ]
        img = None
        for p in pats:
            m = re.search(p, html, re.I)
            if m:
                img = m.group(1)
                break
        if not img:
            return False
        img = urljoin(url, img)
        ri = http_requests.get(img, headers=UA, timeout=20)
        ct = ri.headers.get("Content-Type", "")
        if ri.status_code == 200 and len(ri.content) > 15000 and ("image" in ct or img.endswith((".jpg", ".png", ".webp"))):
            with open(destino, "wb") as f:
                f.write(ri.content)
            return True
    except Exception:
        pass
    return False


def ensure_curated_thumbs():
    os.makedirs(THUMB_DIR, exist_ok=True)
    marker_path = os.path.join(THUMB_DIR, "_sources.json")
    sources = {}
    if os.path.exists(marker_path):
        try:
            with open(marker_path) as f:
                sources = json.load(f)
        except Exception:
            sources = {}
    ok = set()
    for i, (title, tag, cat, em, srcs, pl, lk) in enumerate(CURATED_RAW, start=1):
        path = os.path.join(THUMB_DIR, f"c{i}.jpg")
        want = MANUAL_PHOTOS.get(title)
        have = os.path.exists(path) and os.path.getsize(path) > 15000
        if have:
            ok.add(f"c{i}")
            sources[f"c{i}"] = sources.get(f"c{i}") or (want or "og")
            continue
        print(f"   🖼️  Descargando foto de {title}...")
        done = descargar_imagen_directa(want, path) if want else False
        if not done:
            done = descargar_og_image(srcs[0], path)
        if done:
            sources[f"c{i}"] = want or "og"
            ok.add(f"c{i}")
        else:
            print(f"   ⚠️  {title} sin foto → se mantiene con emoji/gradiente")
            ok.add(f"c{i}")
    with open(marker_path, "w") as f:
        json.dump(sources, f)
    return ok


_ok = ensure_curated_thumbs()

CURATED = []
for i, (t, tag, cat, em, sources, pl, lk) in enumerate(CURATED_RAW, start=1):
    if f"c{i}" not in _ok:
        continue
    full = orden_fuentes(sources, check=True)
    logo_path = f"/static/thumbs/curated/c{i}.jpg"
    local_path = os.path.join(THUMB_DIR, f"c{i}.jpg")
    logo = logo_path if os.path.exists(local_path) and os.path.getsize(local_path) > 15000 else None
    CURATED.append({
        "id": f"c{i}", "title": t, "tag": tag, "category": cat, "emoji": em,
        "gradient": GRADIENTS.get(cat, "from-zinc-800 to-black"),
        "logo": logo,
        "sources": full, "embed_url": full[0], "play_url": sources[0],
        "active_players": pl, "likes": lk, "sections": [],
        "desc": f"{t} — juega gratis en Obito Games.",
    })

_cache = {"db": [], "curated": {}, "stream": [], "counts": {}, "by_title": {}, "ready": False}


def mapear_categoria(raw):
    primera = str(raw or "").split(",")[0].strip().lower()
    return CAT_MAP.get(primera, "arcade")


def pseudo(seed, base, spread):
    return base + (zlib.crc32(seed.encode()) % spread)


def norm_title(t):
    return ''.join(ch for ch in (t or '').lower() if ch.isalnum())


def construir_fuentes(gid, stored_url, fuente=None):
    """
    Construye las URLs correctas según el distribuidor.

    GameMonetize:
        gm_123456
        -> https://html5.gamemonetize.com/123456/

    GameDistribution:
        UUID/ID de GD
        -> https://html5.gamedistribution.com/ID/

    itch.io:
        itch_123456
        -> utiliza la URL guardada en iframe_url.
    """

    gid = str(gid or "").strip()
    stored = str(stored_url or "").strip()

    source = str(fuente or "").strip().lower()

    # Normalizar nombres de fuente
    if source in ("gm", "game monetize", "gamemonetize"):
        source = "gamemonetize"
    elif source in ("gd", "game distribution", "gamedistribution"):
        source = "gamedistribution"
    elif source in ("itch", "itch.io", "itchio"):
        source = "itchio"

    candidates = []

    # =========================================================
    # GAMEMONETIZE
    # =========================================================
    if source == "gamemonetize" or gid.startswith("gm_"):
        if stored.startswith("http"):
            candidates.append(stored)

        if gid.startswith("gm_"):
            gm_id = gid[3:].strip()

            if gm_id:
                candidates.append(
                    f"https://html5.gamemonetize.com/{gm_id}/"
                )

    # =========================================================
    # ITCH.IO
    # =========================================================
    elif source == "itchio" or gid.startswith("itch_"):
        # Para itch.io NO construimos una URL de GameDistribution.
        # Usamos la URL que guardó actualizar_juegos.py.
        if stored.startswith("http"):
            candidates.append(stored)

    # =========================================================
    # GAMEDISTRIBUTION
    # =========================================================
    elif source == "gamedistribution":
        if stored.startswith("http"):
            candidates.append(stored)

        if gid:
            candidates.append(
                f"https://html5.gamedistribution.com/{gid}/"
            )

    # =========================================================
    # COMPATIBILIDAD CON REGISTROS ANTIGUOS
    # =========================================================
    else:
        if gid.startswith("gm_"):
            gm_id = gid[3:].strip()

            if stored.startswith("http"):
                candidates.append(stored)

            if gm_id:
                candidates.append(
                    f"https://html5.gamemonetize.com/{gm_id}/"
                )

        elif gid.startswith("itch_"):
            if stored.startswith("http"):
                candidates.append(stored)

        else:
            if stored.startswith("http"):
                candidates.append(stored)

            if gid:
                candidates.append(
                    f"https://html5.gamedistribution.com/{gid}/"
                )

    # Eliminar duplicados y URLs inválidas
    result = []
    seen = set()

    for url in candidates:
        url = url.strip()

        if not url.startswith(("http://", "https://")):
            continue

        if url in seen:
            continue

        seen.add(url)
        result.append(url)

    return result


def asegurar_columnas(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(juegos)")]
    for col, tipo in (("tag", "TEXT"), ("fuente", "TEXT"), ("sources", "TEXT"), ("orientacion", "TEXT")):
        if col not in cols:
            conn.execute(f"ALTER TABLE juegos ADD COLUMN {col} {tipo}")
    conn.commit()


def sync_curated():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""CREATE TABLE IF NOT EXISTS juegos (
        id TEXT PRIMARY KEY, titulo TEXT, descripcion TEXT, categoria TEXT,
        imagen_url TEXT, iframe_url TEXT)""")
    asegurar_columnas(conn)
    keep = [g["id"] for g in CURATED]
    marks = ",".join("?" for _ in keep) or "''"
    conn.execute(f"DELETE FROM juegos WHERE fuente='curado' AND id NOT IN ({marks})", keep)
    for g in CURATED:
        conn.execute("""INSERT INTO juegos (id,titulo,descripcion,categoria,imagen_url,iframe_url,tag,fuente,sources)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET titulo=excluded.titulo, categoria=excluded.categoria,
            imagen_url=excluded.imagen_url, iframe_url=excluded.iframe_url, tag=excluded.tag,
            fuente=excluded.fuente, sources=excluded.sources""",
            (g["id"], g["title"], g["desc"], g["category"], g["logo"] or "", g["embed_url"], g["tag"], "curado", "|".join(g["sources"])))
    conn.commit()
    conn.close()
    print(f"💾 {len(CURATED)} juegos oficiales sincronizados en juegos.db")


def cargar_cache():
    if _cache["ready"]:
        return True
    if not os.path.exists(DB_FILE):
        print(f"❌ No existe '{DB_FILE}' en {os.getcwd()}")
        return False
    sync_curated()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cols = [r[1] for r in conn.execute("PRAGMA table_info(juegos)")]
    has_orient = "orientacion" in cols
    rows = conn.execute("SELECT * FROM juegos ORDER BY rowid").fetchall()
    conn.close()
    print(f"📚 Leyendo {len(rows)} juegos...")

    db, curated, counts, by_title = [], {}, {}, {}
    for r in rows:
        gid = str(r["id"])
        imagen = (r["imagen_url"] or "").strip()
        if (r["fuente"] or "") == "curado":
            raw = [s for s in (r["sources"] or "").split("|") if s and not s.startswith("/px/")] or [r["iframe_url"]]
            full = orden_fuentes([s for s in raw if s and s.startswith("http")], check=True)
            base = next((c for c in CURATED if c["id"] == gid), None)
            g = {
                "id": gid, "title": r["titulo"], "category": r["categoria"], "tag": r["tag"],
                "emoji": base["emoji"] if base else "🎮",
                "gradient": GRADIENTS.get(r["categoria"], "from-zinc-800 to-black"),
                "logo": imagen or None, "sources": full,
                "embed_url": full[0] if full else None,
                "play_url": next((s for s in raw if s and s.startswith("http")), None),
                "active_players": base["active_players"] if base else 1000,
                "likes": base["likes"] if base else 1000,
                "sections": [], "desc": r["descripcion"] or "", "blocked": False,
                "orientation": ORIENT_CURATED.get(r["titulo"], "horizontal" if mapear_categoria(r["categoria"]) in HORIZ_CATS else "auto"),
            }
            curated[gid] = g
        else:
            if not imagen:
                fuente_actual = str(r["fuente"] or "").strip().lower()

                if fuente_actual in ("gm", "gamemonetize", "game monetize") or gid.startswith("gm_"):
                    imagen = f"https://img.gamemonetize.com/{gid[3:]}/512x384.jpg"

                elif fuente_actual in ("gd", "gamedistribution", "game distribution"):
                    imagen = f"https://img.gamedistribution.com/{gid}.jpg"

                elif fuente_actual in ("itch", "itchio", "itch.io") or gid.startswith("itch_"):
                    # itch.io: no inventamos una URL de imagen.
                    # Si actualizar_juegos.py guardó imagen_url, se utilizará arriba.
                    imagen = ""

                else:
                    imagen = ""
            
            slug = mapear_categoria(r["categoria"])
            
            base_src = construir_fuentes(
                gid,
                r["iframe_url"],
                r["fuente"]
            )
            
            full = orden_fuentes(base_src, check=False)
            g = {
                "id": len(db) + 1, "gd_id": gid, "title": r["titulo"] or "Sin título",
                "category": slug, "emoji": EMOJIS.get(slug, "🎮"),
                "gradient": GRADIENTS.get(slug, "from-zinc-800 to-black"),
                "logo": imagen,
                "active_players": pseudo(gid, 300, 12000),
                "likes": pseudo(gid + "likes", 5000, 900000),
                "sections": [], "play_url": (base_src[0] if base_src else None),
                "embed_url": full[0] if full else None, "sources": full,
                "desc": (r["descripcion"] or "Juega gratis en Obito Games.")[:220],
                "blocked": False,
                "orientation": (r["orientacion"] if (has_orient and r["orientacion"]) else ("horizontal" if slug in HORIZ_CATS else "auto")),
            }
            db.append(g)
        counts[g["category"]] = counts.get(g["category"], 0) + 1
        by_title.setdefault(norm_title(g["title"]), []).append(g)

    # ===== TENDENCIAS: GameMonetize populares primero, ligados con curados =====
    trending_ids = fetch_gamemonetize_trending()
    trank = {gid: i for i, gid in enumerate(trending_ids)}
    for g in db:
        raw_id = g["gd_id"][3:] if g["gd_id"].startswith("gm_") else g["gd_id"]
        g["trending"] = trank.get(raw_id, trank.get(g["gd_id"]))

    trend_games = sorted([g for g in db if g.get("trending") is not None], key=lambda x: x["trending"])
    rest_games = sorted([g for g in db if g.get("trending") is None], key=lambda x: x["active_players"], reverse=True)
    cur_list = sorted(curated.values(), key=lambda x: x["active_players"], reverse=True)

    # Top intercalado: 2 tendencias + 1 curado (liga famosos con curados)
    top = []
    ti = cj = 0
    while ti < len(trend_games) or cj < len(cur_list):
        for _ in range(2):
            if ti < len(trend_games):
                top.append(trend_games[ti]); ti += 1
        if cj < len(cur_list):
            top.append(cur_list[cj]); cj += 1
    stream = top + rest_games

    _cache["db"], _cache["curated"], _cache["stream"], _cache["counts"], _cache["by_title"], _cache["ready"] = db, curated, stream, counts, by_title, True
    print(f"✅ Caché lista: {len(stream)} juegos | {len(trend_games)} tendencias GM | {len(cur_list)} curados")
    return True


# ===== USUARIOS =====
def ensure_users():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL, provider_id TEXT NOT NULL,
        email TEXT, name TEXT, avatar TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(provider, provider_id))""")
    conn.commit()
    conn.close()


def upsert_user(provider, pid, email, name, avatar):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE provider=? AND provider_id=?", (provider, pid)).fetchone()
    if row:
        conn.execute("UPDATE users SET email=?, name=?, avatar=? WHERE id=?", (email, name, avatar, row["id"]))
        uid = row["id"]
        conn.commit()
    else:
        cur = conn.execute("INSERT INTO users (provider,provider_id,email,name,avatar) VALUES (?,?,?,?,?)",
                           (provider, pid, email, name, avatar))
        uid = cur.lastrowid
        conn.commit()
    conn.close()
    return {"id": uid, "provider": provider, "email": email, "name": name, "avatar": avatar}


def verify_google(credential):
    if not http_requests:
        return None
    try:
        r = http_requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": credential}, timeout=10).json()
        if GOOGLE_CLIENT_ID and r.get("aud") != GOOGLE_CLIENT_ID:
            return None
        if "sub" not in r:
            return None
        return r
    except Exception:
        return None


def verify_facebook(token):
    if not http_requests:
        return None
    try:
        if FACEBOOK_APP_SECRET:
            app_token = f"{FACEBOOK_APP_ID}|{FACEBOOK_APP_SECRET}"
            dbg = http_requests.get("https://graph.facebook.com/debug_token",
                               params={"input_token": token, "access_token": app_token}, timeout=10).json()
            if not dbg.get("data", {}).get("is_valid"):
                return None
            if FACEBOOK_APP_ID and dbg["data"].get("app_id") != FACEBOOK_APP_ID:
                return None
        me = http_requests.get("https://graph.facebook.com/me",
                          params={"fields": "id,name,email,picture", "access_token": token}, timeout=10).json()
        if "id" not in me:
            return None
        return me
    except Exception:
        return None


def verify_apple_id_token(token):
    if not jwt or not http_requests:
        return None
    try:
        headers = jwt.get_unverified_header(token)
        keys = http_requests.get("https://appleid.apple.com/auth/keys", timeout=10).json()["keys"]
        key = next((k for k in keys if k["kid"] == headers.get("kid")), None)
        if not key:
            return None
        pub = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        payload = jwt.decode(token, pub, algorithms=["RS256"],
                             audience=APPLE_CLIENT_ID or None,
                             options={"verify_aud": bool(APPLE_CLIENT_ID)})
        if payload.get("iss") != "https://appleid.apple.com":
            return None
        return payload
    except Exception:
        return None


# ===== RUTAS =====
@app.route('/')
def home():
    return render_template('index.html')


@app.route('/ads.txt')
def ads_txt():
    ads_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ads.txt")
    if os.path.exists(ads_path):
        with open(ads_path, 'r') as f:
            return f.read(), 200, {"Content-Type": "text/plain"}
    abort(404)


@app.route('/robots.txt')
def robots():
    return "User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"}


@app.route('/api/config')
def api_config():
    return jsonify({"google": GOOGLE_CLIENT_ID, "facebook": FACEBOOK_APP_ID, "apple": APPLE_CLIENT_ID})


@app.route('/auth/google', methods=['POST'])
def auth_google():
    cred = (request.json or {}).get("credential", "")
    info = verify_google(cred)
    if not info:
        return jsonify({"ok": False, "error": "Token de Google inválido"})
    user = upsert_user("google", info.get("sub"), info.get("email"), info.get("name"), info.get("picture"))
    session["user"] = user
    return jsonify({"ok": True, "user": user})


@app.route('/auth/facebook', methods=['POST'])
def auth_facebook():
    tok = (request.json or {}).get("access_token", "")
    me = verify_facebook(tok)
    if not me:
        return jsonify({"ok": False, "error": "Token de Facebook inválido"})
    pic = me.get("picture", {}).get("data", {}).get("url")
    user = upsert_user("facebook", me.get("id"), me.get("email"), me.get("name"), pic)
    session["user"] = user
    return jsonify({"ok": True, "user": user})


@app.route('/auth/apple/callback', methods=['POST'])
def auth_apple_callback():
    id_token = request.form.get("id_token") or ""
    payload = verify_apple_id_token(id_token)
    if not payload:
        return "Apple login inválido", 400
    email = payload.get("email")
    name = email.split("@")[0] if email else "Usuario Apple"
    user_json = request.form.get("user")
    if user_json:
        try:
            nj = json.loads(user_json)
            nm = nj.get("name", {})
            if nm:
                name = (nm.get("firstName", "") + " " + nm.get("lastName", "")).strip() or name
        except Exception:
            pass
    user = upsert_user("apple", payload.get("sub"), email, name, None)
    session["user"] = user
    return redirect("/")


@app.route('/auth/email', methods=['POST'])
def auth_email():
    email = (request.json or {}).get("email", "").strip().lower()
    if "@" not in email:
        return jsonify({"ok": False, "error": "Correo inválido"})
    user = upsert_user("email", email, email, email.split("@")[0], None)
    session["user"] = user
    return jsonify({"ok": True, "user": user})


@app.route('/auth/me')
def auth_me():
    return jsonify({"user": session.get("user")})


@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    session.pop("user", None)
    return jsonify({"ok": True})


@app.route('/api/games')
def get_games():
    if not cargar_cache():
        return jsonify({'success': False, 'games': [], 'total': 0, 'count': 0})
    games = _cache["stream"]
    category = request.args.get('category')
    search = request.args.get('search', '').lower()
    if category:
        games = [g for g in games if g['category'] == category]
    if search:
        games = [g for g in games if search in g['title'].lower()]
    total = len(games)
    offset = max(0, int(request.args.get('offset', 0)))
    limit = int(request.args.get('limit', 0)) or total
    return jsonify({'success': True, 'count': min(limit, max(total - offset, 0)), 'total': total, 'offset': offset, 'games': games[offset:offset + limit]})


@app.route('/api/curated')
def get_curated():
    if not cargar_cache():
        return jsonify({'success': True, 'games': []})
    return jsonify({'success': True, 'games': sorted(_cache["curated"].values(), key=lambda x: x["active_players"], reverse=True)})


@app.route('/api/game/<game_id>')
def get_game(game_id):
    if not cargar_cache():
        abort(500)
    if str(game_id).startswith('c'):
        g = _cache["curated"].get(game_id)
        if not g:
            abort(404)
        return jsonify({'success': True, 'game': g, 'alternativas': []})
    try:
        idx = int(game_id) - 1
    except ValueError:
        abort(404)
    if not (0 <= idx < len(_cache["db"])):
        abort(404)
    g = _cache["db"][idx]
    alts = [x for x in _cache["by_title"].get(norm_title(g["title"]), []) if x["id"] != g["id"] and x.get("sources")][:3]
    alts = [{"id": x["id"], "title": x["title"], "embed_url": x["embed_url"], "sources": x["sources"], "play_url": x["play_url"]} for x in alts]
    return jsonify({'success': True, 'game': g, 'alternativas': alts})


@app.route('/api/categories')
def get_categories():
    if not cargar_cache():
        return jsonify({'success': True, 'categories': CATEGORIES_DEF})
    cats = [dict(c, count=_cache["counts"].get(c["slug"], 0)) for c in CATEGORIES_DEF if _cache["counts"].get(c["slug"])]
    return jsonify({'success': True, 'categories': cats})


@app.route('/api/stats')
def stats():
    cargar_cache()
    return jsonify({'success': True, 'total': len(_cache["stream"])})


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/px/<path:target>')
def proxy_juego(target):
    if not http_requests:
        abort(502)
    url = target if target.startswith("http") else "https://" + target
    try:
        r = http_requests.get(url, headers=UA, timeout=15)
    except Exception:
        abort(502)
    html = r.text
    html = re.sub(r'<meta[^>]+http-equiv=["\']?(Content-Security-Policy|X-Frame-Options)["\']?[^>]*>', '', html, flags=re.I)
    base = urlparse(url).scheme + "://" + urlparse(url).netloc + "/"
    if "<head>" in html.lower():
        idx = html.lower().index("<head>") + 6
        html = html[:idx] + MUTE_SCRIPT + f'<base href="{base}">' + html[idx:]
    else:
        html = MUTE_SCRIPT + f'<base href="{base}">' + html
    resp = app.make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


try:
    ensure_users()
    cargar_cache()
except Exception as _e:
    print("prewarm skip:", _e)

PORT = int(os.environ.get("PORT", "5000"))
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

if __name__ == '__main__':
    print("=" * 60)
    print(f"📂 Carpeta: {os.getcwd()} | Puerto: {PORT}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)