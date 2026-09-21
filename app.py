import sqlite3
import zlib
import os
import re
import json
import time
import secrets
from urllib.parse import urljoin, urlparse, urlencode
from xml.sax.saxutils import escape as xml_escape
import unicodedata
from flask import Flask, render_template, jsonify, request, abort, session, redirect, Response

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

MI_DOMINIO = os.environ.get("SITE_URL", "").strip().rstrip("/")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID", "").strip()
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "").strip()
APPLE_CLIENT_ID = os.environ.get("APPLE_CLIENT_ID", "").strip()
GAMEMONETIZE_AD_TAG = os.environ.get("GAMEMONETIZE_AD_TAG", "").strip()

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
# Curados antiguos desactivados: varios sitios cambiaron sus políticas de iframe.
# Los juegos manuales con IDs manual_* se preservan en juegos.db.
CURATED_RAW = []

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0 Safari/537.36",
      "Accept": "application/json"}

MUTE_SCRIPT = """<script id="obito-audio-control">
(function(){
  var muted=false,medias=[],contexts=[];
  function remember(m){
    if(!m)return;if(medias.indexOf(m)<0)medias.push(m);
    try{m.muted=muted;if(muted)m.volume=0;}catch(e){}
  }
  function scan(){try{document.querySelectorAll('audio,video').forEach(remember);}catch(e){}}
  try{
    var play=HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play=function(){remember(this);return play.apply(this,arguments);};
  }catch(e){}
  try{
    var AC=window.AudioContext||window.webkitAudioContext;
    if(AC){
      var resume=AC.prototype.resume;
      AC.prototype.resume=function(){var self=this;var p=resume.apply(this,arguments);try{if(contexts.indexOf(self)<0)contexts.push(self);}catch(e){};return p;};
    }
  }catch(e){}
  function setMuted(v){
    muted=!!v;scan();
    medias.forEach(function(m){try{m.muted=muted;if(muted)m.volume=0;}catch(e){}});
    contexts.forEach(function(ctx){try{if(muted&&ctx.state==='running')ctx.suspend();else if(!muted&&ctx.state==='suspended')ctx.resume();}catch(e){}});
  }
  window.__obitoSetMuted=setMuted;
  window.addEventListener('message',function(ev){
    var d=ev&&ev.data;if(d&&d.type==='OBITO_MUTE')setMuted(!!d.muted);
  });
  if('MutationObserver' in window){
    try{new MutationObserver(function(){if(muted)scan();}).observe(document.documentElement,{childList:true,subtree:true});}catch(e){}
  }
  scan();
})();
</script>"""


def con_proxy(u):
    return f"/px/{u}" if u and u.startswith("http") else u


_frame_cache = {}


def fuente_embebible(url):
    """Chequeo conservador para curados/manuales."""
    if not http_requests or not url:
        return False
    if url in _frame_cache:
        return _frame_cache[url]
    ok = False
    try:
        r = http_requests.get(url, headers=UA, timeout=8, stream=True, allow_redirects=True)
        xfo = (r.headers.get("X-Frame-Options") or "").strip().lower()
        csp = (r.headers.get("Content-Security-Policy") or "").lower()
        ok = r.status_code < 400
        if "deny" in xfo or "sameorigin" in xfo:
            ok = False
        m = re.search(r"(?:^|;)\s*frame-ancestors\s+([^;]+)", csp)
        if m and "*" not in m.group(1):
            ok = False
        r.close()
    except Exception:
        ok = False
    _frame_cache[url] = ok
    return ok


def orden_fuentes(base_src, check=False):
    """Usa fuentes directas; no intenta saltarse bloqueos mediante proxy."""
    if not base_src:
        return []
    out, seen = [], set()
    for s in base_src:
        s = str(s or "").strip()
        if not s.startswith(("http://", "https://")) or s in seen:
            continue
        seen.add(s)
        if check and not fuente_embebible(s):
            continue
        out.append(s)
    return out


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

_cache = {"db": [], "curated": {}, "stream": [], "counts": {}, "by_title": {}, "by_slug": {}, "ready": False}


def mapear_categoria(raw):
    primera = str(raw or "").split(",")[0].strip().lower()
    return CAT_MAP.get(primera, "arcade")


def pseudo(seed, base, spread):
    return base + (zlib.crc32(seed.encode()) % spread)


def norm_title(t):
    return ''.join(ch for ch in (t or '').lower() if ch.isalnum())


def slugify(text):
    """Slug legible y seguro para URLs SEO."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:80] or "juego"


def make_game_slug(title, stable_id):
    seed = str(stable_id or title or "game")
    suffix = f"{zlib.crc32(seed.encode('utf-8')) & 0xffffffff:08x}"
    return f"{slugify(title)}-{suffix}"


def parse_sources_value(value, fallback=""):
    """Acepta sources antiguos separados por | y nuevos guardados como JSON."""
    raw = str(value or "").strip()
    out = []
    if raw:
        if raw.startswith("["):
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    out = [str(x).strip() for x in data if str(x).strip()]
            except Exception:
                out = []
        if not out:
            out = [x.strip() for x in raw.split("|") if x.strip()]
    if not out and fallback:
        out = [str(fallback).strip()]
    return out


def site_base_url():
    return (MI_DOMINIO or request.url_root.rstrip("/")).rstrip("/")


def render_spa(title=None, description=None, canonical=None, image=None, initial_hash=""):
    return render_template(
        "index.html",
        seo_title=title or "Obito Games | Minijuegos Online Gratis",
        seo_description=description or (
            "Juega minijuegos online gratis en Obito Games. Descubre acción, arcade, "
            "carreras, puzzles, deportes y mucho más directamente desde tu navegador."
        ),
        seo_canonical=canonical or (site_base_url() + "/"),
        seo_image=image or (site_base_url() + "/static/logo.png"),
        initial_hash=initial_hash or "",
    )


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
        # GameMonetize usa tokens de embed que NO siempre coinciden con
        # el ID numérico del catálogo. La URL válida debe venir de la BD.
        if stored.startswith("http"):
            candidates.append(stored)

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
            if stored.startswith("http"):
                candidates.append(stored)

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



def extraer_gamemonetize_game_id(gid, fuente, urls=None):
    """Devuelve el hash real de GameMonetize usado por video.js/walkthroughs."""
    source = str(fuente or "").strip().lower()
    candidates = list(urls or [])
    raw_gid = str(gid or "").strip()
    if raw_gid.startswith("gm_"):
        candidates.append(raw_gid[3:])
    elif source in ("gm", "gamemonetize", "game monetize"):
        candidates.append(raw_gid)

    for item in candidates:
        value = str(item or "").strip()
        if re.fullmatch(r"[A-Za-z0-9]{20,80}", value):
            return value
        if not value.startswith(("http://", "https://")):
            continue
        try:
            parsed = urlparse(value)
            host = (parsed.hostname or "").lower()
            if host in {"html5.gamemonetize.com", "html5.gamemonetize.co", "html5.gamemonetize.games"}:
                token = next((p for p in parsed.path.split("/") if p), "")
                if re.fullmatch(r"[A-Za-z0-9]{20,80}", token):
                    return token
        except Exception:
            pass
    return None


def asegurar_columnas(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(juegos)")]
    for col, tipo in (("tag", "TEXT"), ("fuente", "TEXT"), ("sources", "TEXT"), ("orientacion", "TEXT"), ("preview_url", "TEXT")):
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
    conn.execute(f"DELETE FROM juegos WHERE fuente='curado' AND id LIKE 'c%' AND id NOT IN ({marks})", keep)
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

    db, curated, counts, by_title, by_slug = [], {}, {}, {}, {}
    for r in rows:
        gid = str(r["id"])
        imagen = (r["imagen_url"] or "").strip()
        if (r["fuente"] or "") == "curado":
            raw = [s for s in parse_sources_value(r["sources"], r["iframe_url"]) if s and not s.startswith("/px/")]
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
                "preview_url": (r["preview_url"] or "").strip() or None,
                "gm_game_id": extraer_gamemonetize_game_id(gid, r["fuente"], raw),
                "orientation": ORIENT_CURATED.get(r["titulo"], "horizontal" if mapear_categoria(r["categoria"]) in HORIZ_CATS else "auto"),
            }
            g["seo_slug"] = make_game_slug(g["title"], gid)
            g["seo_url"] = f"/juego/{g['seo_slug']}"
            curated[gid] = g
            by_slug[g["seo_slug"]] = g
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
                "preview_url": (r["preview_url"] or "").strip() or None,
                "gm_game_id": extraer_gamemonetize_game_id(gid, r["fuente"], base_src),
                "orientation": (r["orientacion"] if (has_orient and r["orientacion"]) else ("horizontal" if slug in HORIZ_CATS else "auto")),
            }
            g["seo_slug"] = make_game_slug(g["title"], gid)
            g["seo_url"] = f"/juego/{g['seo_slug']}"
            db.append(g)
        counts[g["category"]] = counts.get(g["category"], 0) + 1
        by_title.setdefault(norm_title(g["title"]), []).append(g)
        by_slug[g["seo_slug"]] = g

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

    _cache["db"], _cache["curated"], _cache["stream"], _cache["counts"], _cache["by_title"], _cache["by_slug"], _cache["ready"] = db, curated, stream, counts, by_title, by_slug, True
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


def verify_google_access_token(token):
    if not http_requests or not token:
        return None
    try:
        r = http_requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        data = r.json()
        if r.status_code != 200 or not data.get("sub"):
            return None
        return data
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
    base = site_base_url()
    return render_spa(canonical=base + "/")


@app.route('/categoria/<slug>')
def category_page(slug):
    if not cargar_cache():
        abort(500)
    cat = next((c for c in CATEGORIES_DEF if c["slug"] == slug), None)
    if not cat:
        abort(404)
    count = _cache["counts"].get(slug, 0)
    title = f"Minijuegos de {cat['name']} Online Gratis | Obito Games"
    desc = (
        f"Juega minijuegos de {cat['name'].lower()} online gratis en Obito Games. "
        f"Explora {count} juegos disponibles directamente desde tu navegador."
    )
    return render_spa(
        title=title,
        description=desc,
        canonical=site_base_url() + f"/categoria/{slug}",
        initial_hash=f"#cat-{slug}",
    )


@app.route('/juego/<game_slug>')
def game_page(game_slug):
    if not cargar_cache():
        abort(500)
    g = _cache["by_slug"].get(game_slug)
    if not g:
        abort(404)
    title = f"{g['title']} - Jugar Gratis Online | Obito Games"
    desc = (g.get("desc") or f"Juega {g['title']} gratis online en Obito Games.")[:300]
    image = g.get("logo") or (site_base_url() + "/static/logo.png")
    if image and image.startswith("/"):
        image = site_base_url() + image
    return render_spa(
        title=title,
        description=desc,
        canonical=site_base_url() + g["seo_url"],
        image=image,
        initial_hash=f"#juego-{g['id']}",
    )


@app.route('/sitemap.xml')
def sitemap():
    if not cargar_cache():
        abort(500)
    base = site_base_url()
    urls = [base + "/"]
    urls.extend(base + f"/categoria/{c['slug']}" for c in CATEGORIES_DEF if _cache["counts"].get(c["slug"]))
    urls.extend(base + g["seo_url"] for g in _cache["stream"])
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        body.append(f"<url><loc>{xml_escape(u)}</loc></url>")
    body.append("</urlset>")
    return Response("\n".join(body), mimetype="application/xml")


@app.route('/ads.txt')
def ads_txt():
    ads_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ads.txt")
    if os.path.exists(ads_path):
        with open(ads_path, 'r') as f:
            return f.read(), 200, {"Content-Type": "text/plain"}
    abort(404)


@app.route('/robots.txt')
def robots():
    base = site_base_url()
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /px/\n"
        "Disallow: /auth/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route('/api/config')
def api_config():
    return jsonify({
        "google": GOOGLE_CLIENT_ID,
        "facebook": FACEBOOK_APP_ID,
        "apple": APPLE_CLIENT_ID,
        "gamemonetize_ads_configured": bool(GAMEMONETIZE_AD_TAG),
    })


@app.route('/auth/google', methods=['POST'])
def auth_google():
    cred = (request.json or {}).get("credential", "")
    info = verify_google(cred)
    if not info:
        return jsonify({"ok": False, "error": "Token de Google inválido"})
    user = upsert_user("google", info.get("sub"), info.get("email"), info.get("name"), info.get("picture"))
    session["user"] = user
    return jsonify({"ok": True, "user": user})


@app.route('/auth/google-token', methods=['POST'])
def auth_google_token():
    tok = (request.json or {}).get("access_token", "")
    info = verify_google_access_token(tok)
    if not info:
        return jsonify({"ok": False, "error": "Token de Google inválido"}), 400
    user = upsert_user(
        "google",
        info.get("sub"),
        info.get("email"),
        info.get("name"),
        info.get("picture"),
    )
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


@app.route('/auth/apple/start')
def auth_apple_start():
    if not APPLE_CLIENT_ID:
        return "Apple Sign In no está configurado", 503
    state = secrets.token_urlsafe(24)
    session["apple_oauth_state"] = state
    redirect_uri = site_base_url() + "/auth/apple/callback"
    params = {
        "client_id": APPLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code id_token",
        "response_mode": "form_post",
        "scope": "name email",
        "state": state,
    }
    return redirect("https://appleid.apple.com/auth/authorize?" + urlencode(params))


@app.route('/auth/apple/callback', methods=['POST'])
def auth_apple_callback():
    expected_state = session.pop("apple_oauth_state", None)
    received_state = request.form.get("state")
    if expected_state and received_state != expected_state:
        return "Estado de Apple inválido", 400
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

    section = (request.args.get('section') or '').strip().lower()

    if section == 'originals':
        games = sorted(_cache["curated"].values(), key=lambda x: x["active_players"], reverse=True)
    elif section in ('popular', 'ranking'):
        games = sorted(_cache["stream"], key=lambda x: (x.get("active_players", 0), x.get("likes", 0)), reverse=True)
    elif section == 'multiplayer':
        games = [g for g in _cache["stream"] if g.get("category") in {"io", "disparos", "deportes"}]
    elif section in ('new', 'updated'):
        # La BD no guarda fecha de publicación. Se usa el orden de importación
        # más reciente como aproximación, sin inventar una fecha.
        games = list(reversed(_cache["db"])) + list(_cache["curated"].values())
    else:
        games = _cache["stream"]

    category = request.args.get('category')
    search = request.args.get('search', '').strip().lower()

    if category:
        games = [g for g in games if g['category'] == category]
    if search:
        games = [g for g in games if search in g['title'].lower()]

    total = len(games)
    try:
        offset = max(0, int(request.args.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(request.args.get('limit', 0))
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        limit = total
    limit = min(limit, 500)

    return jsonify({
        'success': True,
        'count': min(limit, max(total - offset, 0)),
        'total': total,
        'offset': offset,
        'games': games[offset:offset + limit]
    })


@app.route('/api/curated')
def get_curated():
    if not cargar_cache():
        return jsonify({'success': True, 'games': []})
    return jsonify({'success': True, 'games': sorted(_cache["curated"].values(), key=lambda x: x["active_players"], reverse=True)})


@app.route('/api/game/<game_id>')
def get_game(game_id):
    if not cargar_cache():
        abort(500)

    # Los curados pueden llamarse c1, c2... o manual_2048, manual_pacman, etc.
    g = _cache["curated"].get(str(game_id))
    if g:
        return jsonify({'success': True, 'game': g, 'alternativas': []})

    try:
        idx = int(game_id) - 1
    except ValueError:
        abort(404)
    if not (0 <= idx < len(_cache["db"])):
        abort(404)
    g = _cache["db"][idx]
    alts = [x for x in _cache["by_title"].get(norm_title(g["title"]), []) if x["id"] != g["id"] and x.get("sources")][:3]
    alts = [{"id": x["id"], "title": x["title"], "embed_url": x["embed_url"], "sources": x["sources"], "play_url": x["play_url"], "preview_url": x.get("preview_url"), "gm_game_id": x.get("gm_game_id")} for x in alts]
    return jsonify({'success': True, 'game': g, 'alternativas': alts})


@app.route('/api/categories')
def get_categories():
    if not cargar_cache():
        return jsonify({'success': True, 'categories': CATEGORIES_DEF})
    cats = [dict(c, count=_cache["counts"].get(c["slug"], 0)) for c in CATEGORIES_DEF if _cache["counts"].get(c["slug"])]
    return jsonify({'success': True, 'categories': cats})


@app.route('/api/report', methods=['POST'])
def report_game():
    data = request.get_json(silent=True) or {}
    game_id = str(data.get("game_id") or "")[:128]
    title = str(data.get("title") or "")[:200]
    reason = str(data.get("reason") or "")[:500]
    if not game_id or not reason:
        return jsonify({"ok": False, "error": "Datos incompletos"}), 400

    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS game_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            title TEXT,
            reason TEXT NOT NULL,
            user_email TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        user = session.get("user") or {}
        conn.execute(
            "INSERT INTO game_reports (game_id,title,reason,user_email) VALUES (?,?,?,?)",
            (game_id, title, reason, user.get("email"))
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@app.route('/api/stats')
def stats():
    cargar_cache()
    return jsonify({'success': True, 'total': len(_cache["stream"])})




@app.route('/manifest.webmanifest')
def manifest_webmanifest():
    data = {
        "name": "Obito Games",
        "short_name": "Obito Games",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": "#070203",
        "orientation": "any",
        "icons": [
            {"src": "/static/logo.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/logo.png", "sizes": "512x512", "type": "image/png"}
        ]
    }
    return Response(json.dumps(data), mimetype='application/manifest+json')

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/gm-video/<game_id>')
def gm_video_bridge(game_id):
    # Página aislada para el walkthrough de GameMonetize.
    # Se sirve desde el mismo dominio para que video.js vea un hostname real;
    # el frontend la carga dentro de un iframe sandbox sin navegación superior.
    gid = re.sub(r"[^A-Za-z0-9]", "", str(game_id or ""))
    if not re.fullmatch(r"[A-Za-z0-9]{20,80}", gid):
        abort(404)

    mode = "preview" if request.args.get("mode") == "preview" else "detail"
    ads = request.args.get("ads", "0") in {"1", "true", "yes"}
    token = re.sub(r"[^A-Za-z0-9_-]", "", request.args.get("token", ""))[:96]
    title = str(request.args.get("title") or "Juego").strip()[:140]
    domain = (request.host.split(":", 1)[0] or "").strip().lower()

    video_options = {
        "gameid": gid,
        "width": "100%",
        "height": "100%",
        "color": "#ff2424",
        "getAds": "true" if ads else "false",
    }
    direct_url = "https://gamemonetize.video/index.php?" + urlencode({
        "domain": domain,
        "gameid": gid,
        "game": title,
        "getads": "true" if ads else "false",
        "color": "#ff2424",
    })

    opts_json = json.dumps(video_options, separators=(",", ":"))
    token_json = json.dumps(token)
    mode_json = json.dumps(mode)
    direct_json = json.dumps(direct_url)

    page = f'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;color:#fff;font-family:Arial,sans-serif}}
#gm-root{{position:absolute;inset:0;overflow:hidden;background:transparent}}
#gamemonetize-video{{position:absolute;inset:0;width:100%;height:100%;overflow:hidden;background:transparent}}
#gamemonetize-video>*,#gamemonetize-video iframe,#gamemonetize-video video,#gamemonetize-video object,#gamemonetize-video embed{{display:block!important;width:100%!important;height:100%!important;min-width:100%!important;min-height:100%!important;max-width:none!important;max-height:none!important;border:0!important;margin:0!important;padding:0!important}}
body.preview #gamemonetize-video,body.preview #gamemonetize-video *{{pointer-events:none!important;user-select:none!important}}
#status{{position:absolute;inset:0;z-index:1;display:grid;place-items:center;pointer-events:none;background:radial-gradient(circle at 50% 45%,rgba(255,35,45,.10),transparent 34%)}}
#status.hide{{opacity:0;visibility:hidden;transition:opacity .25s ease}}
.spinner{{width:32px;height:32px;border-radius:50%;border:3px solid rgba(255,255,255,.12);border-top-color:#ff2938;animation:spin .9s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style>
</head>
<body>
<div id="gm-root"><div id="gamemonetize-video"></div><div id="status"><span class="spinner"></span></div></div>
<script>
(function(){{
  'use strict';
  var TOKEN={token_json}, MODE={mode_json}, DIRECT={direct_json};
  var host=document.getElementById('gamemonetize-video');
  var status=document.getElementById('status');
  var sentReady=false, directMounted=false, lastPlayer=null;
  if(MODE==='preview')document.body.classList.add('preview');

  function send(type,extra){{
    try{{ parent.postMessage(Object.assign({{type:type,token:TOKEN}},extra||{{}}),'*'); }}catch(e){{}}
  }}
  function markReady(reason){{
    if(sentReady)return;sentReady=true;
    if(status)status.classList.add('hide');
    send('OBITO_GM_READY',{{reason:reason||'player'}});
  }}
  function mountDirect(reason,src){{
    if(directMounted)return;
    directMounted=true;
    var target=src||DIRECT;
    try{{
      var u=new URL(target,location.href);
      if(u.hostname!=='gamemonetize.video')target=DIRECT;
    }}catch(e){{target=DIRECT;}}
    host.replaceChildren();
    var fr=document.createElement('iframe');
    fr.src=target;
    fr.title=MODE==='preview'?'Gameplay preview':'Guía del juego';
    fr.setAttribute('allow','autoplay; fullscreen; picture-in-picture');
    fr.setAttribute('allowfullscreen','true');
    fr.setAttribute('scrolling','no');
    fr.setAttribute('frameborder','0');
    fr.referrerPolicy='strict-origin-when-cross-origin';
    fr.onload=function(){{setTimeout(function(){{markReady(reason||'direct');}},MODE==='preview'?1300:650);}};
    fr.onerror=function(){{send('OBITO_GM_ERROR',{{reason:'direct_iframe_error'}});}};
    host.appendChild(fr);lastPlayer=fr;
  }}
  function decodeMarkupText(){{
    var text=(host.textContent||'').trim();
    if(!text || text.indexOf('<iframe')<0)return false;
    try{{
      var doc=new DOMParser().parseFromString(text,'text/html');
      var fr=doc.querySelector('iframe[src]');
      if(fr){{mountDirect('decoded_markup',fr.getAttribute('src'));return true;}}
    }}catch(e){{}}
    var m=text.match(/<iframe[^>]+src=["']([^"']+)["']/i);
    if(m){{mountDirect('decoded_markup_regex',m[1]);return true;}}
    return false;
  }}
  function inspect(){{
    if(sentReady)return;
    if(decodeMarkupText())return;
    var media=host.querySelector('video');
    if(media){{
      lastPlayer=media;
      if(MODE==='preview'){{
        try{{media.muted=true;media.defaultMuted=true;media.autoplay=true;media.playsInline=true;var p=media.play();if(p&&p.catch)p.catch(function(){{}});}}catch(e){{}}
      }}
      if(media.readyState>=2)markReady('video');
      else{{media.addEventListener('loadeddata',function(){{markReady('video_loaded');}},{{once:true}});media.addEventListener('canplay',function(){{markReady('video_canplay');}},{{once:true}});}}
      return;
    }}
    var fr=host.querySelector('iframe');
    if(fr){{
      if(lastPlayer!==fr){{
        lastPlayer=fr;
        fr.addEventListener('load',function(){{setTimeout(function(){{markReady('api_iframe');}},MODE==='preview'?1100:500);}},{{once:true}});
      }}
      setTimeout(function(){{if(!sentReady&&host.contains(fr))markReady('api_iframe_seen');}},MODE==='preview'?1800:900);
    }}
  }}

  try{{new MutationObserver(function(){{setTimeout(inspect,60);}}).observe(host,{{childList:true,subtree:true,characterData:true}});}}catch(e){{}}
  window.addEventListener('error',function(e){{if(!sentReady)send('OBITO_GM_SCRIPT_WARNING',{{message:String(e.message||'')}});}});
  window.VIDEO_OPTIONS={opts_json};
  var s=document.createElement('script');
  s.id='gamemonetize-video-api';
  s.src='https://api.gamemonetize.com/video.js?v='+Date.now();
  s.async=true;
  s.onload=function(){{setTimeout(inspect,180);setTimeout(inspect,900);setTimeout(function(){{if(!sentReady&&!directMounted)mountDirect('api_fallback');}},4800);}};
  s.onerror=function(){{mountDirect('script_error_fallback');}};
  document.head.appendChild(s);
  setTimeout(inspect,600);
  setTimeout(function(){{if(!sentReady&&!directMounted)mountDirect('timeout_fallback');}},6000);
  setTimeout(function(){{if(!sentReady)send('OBITO_GM_TIMEOUT',{{reason:'final_timeout'}});}},14000);
}})();
</script>
</body>
</html>'''
    resp = Response(page, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


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