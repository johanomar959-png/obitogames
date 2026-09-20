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
GM_RANK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gm_ranking.json")

MI_DOMINIO = ""
GOOGLE_CLIENT_ID = ""
FACEBOOK_APP_ID = ""
FACEBOOK_APP_SECRET = ""
APPLE_CLIENT_ID = ""

SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret_key.txt")
def _load_secret():
    env = os.environ.get("SECRET_KEY")
    if env: return env
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE) as f: return f.read().strip()
    s = secrets.token_hex(32)
    with open(SECRET_FILE, "w") as f: f.write(s)
    return s
app.secret_key = _load_secret()

MANUAL_PHOTOS = {
    "Smash Karts": "https://imgs.crazygames.com/smash-karts_16x9/20260210123937/smash-karts_16x9-cover?metadata=none&quality=100&width=1200&height=630&fit=crop",
}

ORIENT_CURATED = {
    "Smash Karts": "horizontal", "1v1.LOL": "horizontal", "Venge.io": "horizontal",
    "Slither.io": "auto", "Shell Shockers": "horizontal", "ZombsRoyale.io": "horizontal",
    "Skribbl.io": "horizontal", "Diep.io": "auto", "Krunker.io": "horizontal",
    "Little Big Snake": "auto", "EvoWars.io": "auto", "Surviv.io": "horizontal",
    "Wings.io": "horizontal", "Bonk.io": "horizontal", "Gartic Phone": "horizontal",
    "Flappy Bird": "auto", "Pac-Man": "horizontal", "Tetris": "auto", "Hextris": "auto",
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

# Curados externos (van ABAJO ligados; NUNCA en el mosaico superior)
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
    if not http_requests: return True
    if url in _frame_cache: return _frame_cache[url]
    ok = True
    try:
        r = http_requests.get(url, headers=UA, timeout=8, stream=True)
        xfo = (r.headers.get("X-Frame-Options") or "").strip().lower()
        csp = (r.headers.get("Content-Security-Policy") or "").lower()
        if xfo in ("deny", "sameorigin") or "frame-ancestors" in csp: ok = False
        r.close()
    except Exception:
        ok = True
    _frame_cache[url] = ok
    return ok


def orden_fuentes(base_src, check=False):
    if not base_src: return []
    seen = set(); res = []
    def add(s):
        if s and s not in seen: seen.add(s); res.append(s)
    if not check:
        for s in base_src: add(s)
        add(con_proxy(base_src[0]))
        return res
    directas = [s for s in base_src if fuente_embebible(s)]
    bloqueadas = [s for s in base_src if not fuente_embebible(s)]
    for s in directas: add(s)
    if not directas and bloqueadas: add(con_proxy(bloqueadas[0]))
    for s in bloqueadas: add(con_proxy(s))
    return res


# ===== RANKING GAMEMONETIZE (popularidad real) =====
_gm_rank = None
def cargar_ranking_gm():
    global _gm_rank
    if _gm_rank is not None: return _gm_rank
    if os.path.exists(GM_RANK_FILE):
        try:
            with open(GM_RANK_FILE) as f:
                _gm_rank = json.load(f); return _gm_rank
        except Exception: pass
    _gm_rank = {}
    if http_requests:
        try:
            r = http_requests.get("https://gamemonetize.com/feed.php?format=0&num=38000",
                                  headers=UA, timeout=30)
            try:
                data = json.loads(r.text)
            except Exception:
                data = None
            items = []
            if isinstance(data, list): items = data
            elif isinstance(data, dict):
                items = data.get("games", data.get("items", data.get("channel", {}).get("item", [])))
            for i, it in enumerate(items):
                if isinstance(it, dict):
                    gid = str(it.get("id") or it.get("game_id") or "")
                    if gid: _gm_rank[gid] = i
            if _gm_rank:
                with open(GM_RANK_FILE, "w") as f: json.dump(_gm_rank, f)
        except Exception:
            _gm_rank = {}
    return _gm_rank


def descargar_imagen_directa(url, destino):
    if not http_requests: return False
    try:
        ri = http_requests.get(url, headers=UA, timeout=25)
        if ri.status_code == 200 and len(ri.content) > 15000:
            with open(destino, "wb") as f: f.write(ri.content)
            return True
    except Exception: pass
    return False


def descargar_og_image(url, destino):
    if not http_requests: return False
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
            if m: img = m.group(1); break
        if not img: return False
        img = urljoin(url, img)
        ri = http_requests.get(img, headers=UA, timeout=20)
        ct = ri.headers.get("Content-Type", "")
        if ri.status_code == 200 and len(ri.content) > 15000 and ("image" in ct or img.endswith((".jpg", ".png", ".webp"))):
            with open(destino, "wb") as f: f.write(ri.content)
            return True
    except Exception: pass
    return False


def ensure_curated_thumbs():
    os.makedirs(THUMB_DIR, exist_ok=True)
    marker_path = os.path.join(THUMB_DIR, "_sources.json")
    sources = {}
    if os.path.exists(marker_path):
        try:
            with open(marker_path) as f: sources = json.load(f)
        except Exception: sources = {}
    ok = set()
    for i, (title, tag, cat, em, srcs, pl, lk) in enumerate(CURATED_RAW, start=1):
        path = os.path.join(THUMB_DIR, f"c{i}.jpg")
        want = MANUAL_PHOTOS.get(title)
        have = os.path.exists(path) and os.path.getsize(path) > 15000
        if have:
            ok.add(f"c{i}"); sources[f"c{i}"] = sources.get(f"c{i}") or (want or "og"); continue
        done = descargar_imagen_directa(want, path) if want else False
        if not done: done = descargar_og_image(srcs[0], path)
        if done:
            sources[f"c{i}"] = want or "og"; ok.add(f"c{i}")
        else:
            ok.add(f"c{i}")
    with open(marker_path, "w") as f: json.dump(sources, f)
    return ok


_ok = ensure_curated_thumbs()

CURATED = []
for i, (t, tag, cat, em, sources, pl, lk) in enumerate(CURATED_RAW, start=1):
    if f"c{i}" not in _ok: continue
    full = orden_fuentes(sources, check=True)
    local_path = os.path.join(THUMB_DIR, f"c{i}.jpg")
    logo = f"/static/thumbs/curated/c{i}.jpg" if os.path.exists(local_path) and os.path.getsize(local_path) > 15000 else None
    CURATED.append({
        "id": f"c{i}", "title": t, "tag": tag, "category": cat, "emoji": em,
        "gradient": GRADIENTS.get(cat, "from-zinc-800 to-black"), "logo": logo,
        "sources": full, "embed_url": full[0], "play_url": sources[0],
        "active_players": pl, "likes": lk, "sections": [],
        "desc": f"{t} — juega gratis en Obito Games.",
    })

_cache = {"db": [], "curated": {}, "stream": [], "counts": {}, "by_title": {}, "ready": False}


def mapear_categoria(raw):
    return CAT_MAP.get(str(raw or "").split(",")[0].strip().lower(), "arcade")

def pseudo(seed, base, spread):
    return base + (zlib.crc32(seed.encode()) % spread)

def norm_title(t):
    return ''.join(ch for ch in (t or '').lower() if ch.isalnum())

def construir_fuentes(gid, stored_url):
    stored = (stored_url or "").strip()
    if gid.startswith("gm_"):
        cand = [stored, f"https://html5.gamemonetize.co/{gid[3:]}/"]
    else:
        cand = [f"https://html5.gamedistribution.com/{gid}/", stored]
    out = []
    for c in cand:
        if c and c.startswith("http") and c not in out: out.append(c)
    return out


def asegurar_columnas(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(juegos)")]
    for col, tipo in (("tag", "TEXT"), ("fuente", "TEXT"), ("sources", "TEXT"), ("orientacion", "TEXT"), ("score", "REAL")):
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
    conn.commit(); conn.close()
    print(f"💾 {len(CURATED)} curados sincronizados en juegos.db")


def cargar_cache():
    if _cache["ready"]: return True
    if not os.path.exists(DB_FILE):
        print(f"❌ No existe '{DB_FILE}'"); return False
    sync_curated()
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row
    cols = [r[1] for r in conn.execute("PRAGMA table_info(juegos)")]
    has_orient = "orientacion" in cols
    rows = conn.execute("SELECT * FROM juegos ORDER BY rowid").fetchall()
    conn.close()
    print(f"📚 Leyendo {len(rows)} juegos...")

    gm_rank = cargar_ranking_gm()
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
                "sections": [], "desc": r["descripcion"] or "", "blocked": False, "es_curado": True,
                "orientation": ORIENT_CURATED.get(r["titulo"], "horizontal" if mapear_categoria(r["categoria"]) in HORIZ_CATS else "auto"),
            }
            curated[gid] = g
        else:
            if not imagen:
                imagen = f"https://img.gamemonetize.com/{gid[3:]}/512x384.jpg" if gid.startswith("gm_") else f"https://img.gamedistribution.com/{gid}.jpg"
            slug = mapear_categoria(r["categoria"])
            base_src = construir_fuentes(gid, r["iframe_url"])
            full = orden_fuentes(base_src, check=False)
            raw_id = gid[3:] if gid.startswith("gm_") else gid
            rank = gm_rank.get(raw_id, gm_rank.get(gid))
            score = (10_000_000 - rank) if rank is not None else float(pseudo(gid, 300, 12000))
            g = {
                "id": len(db) + 1, "gd_id": gid, "title": r["titulo"] or "Sin título",
                "category": slug, "emoji": EMOJIS.get(slug, "🎮"),
                "gradient": GRADIENTS.get(slug, "from-zinc-800 to-black"), "logo": imagen,
                "active_players": pseudo(gid, 300, 12000),
                "likes": pseudo(gid + "likes", 5000, 900000),
                "sections": [], "play_url": (base_src[0] if base_src else None),
                "embed_url": full[0] if full else None, "sources": full,
                "desc": (r["descripcion"] or "Juega gratis en Obito Games.")[:220],
                "blocked": False, "es_curado": False, "score": score,
                "orientation": (r["orientacion"] if (has_orient and r["orientacion"]) else ("horizontal" if slug in HORIZ_CATS else "auto")),
            }
            db.append(g)
        counts[g["category"]] = counts.get(g["category"], 0) + 1
        by_title.setdefault(norm_title(g["title"]), []).append(g)

    # ===== ORDEN: GameMonetize mejor→peor; curados ligados ABAJO cada 20 =====
    gm_sorted = sorted(db, key=lambda x: x.get("score", 0), reverse=True)
    cur_sorted = sorted(curated.values(), key=lambda x: x["active_players"], reverse=True)
    stream = []
    gi = ci = 0
    while gi < len(gm_sorted) or ci < len(cur_sorted):
        for _ in range(20):
            if gi < len(gm_sorted): stream.append(gm_sorted[gi]); gi += 1
        if ci < len(cur_sorted): stream.append(cur_sorted[ci]); ci += 1

    _cache["db"], _cache["curated"], _cache["stream"], _cache["counts"], _cache["by_title"], _cache["ready"] = db, curated, stream, counts, by_title, True
    print(f"✅ Caché: {len(stream)} juegos | GM ordenados: {len(gm_sorted)} | curados ligados: {len(cur_sorted)}")
    return True


# ===== USUARIOS =====
def ensure_users():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, provider_id TEXT NOT NULL,
        email TEXT, name TEXT, avatar TEXT, password_hash TEXT,
        created_at TEXT DEFAULT (datetime('now')), UNIQUE(provider, provider_id))""")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    if "password_hash" not in cols:
        try: conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        except Exception: pass
    conn.commit(); conn.close()

def hash_password(password, salt=None):
    if salt is None: salt = secrets.token_hex(16)
    h = hashlib_pbkdf2(password, salt)
    return f"{salt}${h}"

def hashlib_pbkdf2(password, salt):
    import hashlib
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()

def verify_password(password, stored):
    try:
        salt, _ = stored.split("$"); import hmac
        return hmac.compare_digest(hash_password(password, salt), stored)
    except Exception: return False

def upsert_user(provider, pid, email, name, avatar, password_hash=None):
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE provider=? AND provider_id=?", (provider, pid)).fetchone()
    if row:
        if password_hash:
            conn.execute("UPDATE users SET email=?,name=?,avatar=?,password_hash=? WHERE id=?", (email,name,avatar,password_hash,row["id"]))
        else:
            conn.execute("UPDATE users SET email=?,name=?,avatar=? WHERE id=?", (email,name,avatar,row["id"]))
        uid = row["id"]; conn.commit()
    else:
        cur = conn.execute("INSERT INTO users (provider,provider_id,email,name,avatar,password_hash) VALUES (?,?,?,?,?,?)",
                           (provider,pid,email,name,avatar,password_hash))
        uid = cur.lastrowid; conn.commit()
    conn.close()
    return {"id": uid, "provider": provider, "email": email, "name": name, "avatar": avatar}

def find_user_by_email(email):
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
    conn.close()
    return dict(row) if row else None

def verify_google(credential):
    if not http_requests: return None
    try:
        r = http_requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": credential}, timeout=10).json()
        if GOOGLE_CLIENT_ID and r.get("aud") != GOOGLE_CLIENT_ID: return None
        return r if "sub" in r else None
    except Exception: return None

def verify_facebook(token):
    if not http_requests: return None
    try:
        if FACEBOOK_APP_SECRET:
            app_token = f"{FACEBOOK_APP_ID}|{FACEBOOK_APP_SECRET}"
            dbg = http_requests.get("https://graph.facebook.com/debug_token", params={"input_token": token, "access_token": app_token}, timeout=10).json()
            if not dbg.get("data", {}).get("is_valid"): return None
        me = http_requests.get("https://graph.facebook.com/me", params={"fields": "id,name,email,picture", "access_token": token}, timeout=10).json()
        return me if "id" in me else None
    except Exception: return None

def verify_apple_id_token(token):
    if not jwt or not http_requests: return None
    try:
        headers = jwt.get_unverified_header(token)
        keys = http_requests.get("https://appleid.apple.com/auth/keys", timeout=10).json()["keys"]
        key = next((k for k in keys if k["kid"] == headers.get("kid")), None)
        if not key: return None
        pub = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        payload = jwt.decode(token, pub, algorithms=["RS256"], audience=APPLE_CLIENT_ID or None, options={"verify_aud": bool(APPLE_CLIENT_ID)})
        return payload if payload.get("iss") == "https://appleid.apple.com" else None
    except Exception: return None


# ===== RUTAS =====
@app.route('/')
def home(): return render_template('index.html')

@app.route('/ads.txt')
def ads_txt():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ads.txt")
    if os.path.exists(p):
        with open(p) as f: return f.read(), 200, {"Content-Type": "text/plain"}
    abort(404)

@app.route('/robots.txt')
def robots(): return "User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"}

@app.route('/api/config')
def api_config(): return jsonify({"google": GOOGLE_CLIENT_ID, "facebook": FACEBOOK_APP_ID, "apple": APPLE_CLIENT_ID})

@app.route('/auth/google', methods=['POST'])
def auth_google():
    info = verify_google((request.json or {}).get("credential", ""))
    if not info: return jsonify({"ok": False, "error": "Token de Google inválido"})
    user = upsert_user("google", info.get("sub"), info.get("email"), info.get("name"), info.get("picture"))
    session["user"] = user; return jsonify({"ok": True, "user": user})

@app.route('/auth/facebook', methods=['POST'])
def auth_facebook():
    me = verify_facebook((request.json or {}).get("access_token", ""))
    if not me: return jsonify({"ok": False, "error": "Token de Facebook inválido"})
    pic = me.get("picture", {}).get("data", {}).get("url")
    user = upsert_user("facebook", me.get("id"), me.get("email"), me.get("name"), pic)
    session["user"] = user; return jsonify({"ok": True, "user": user})

@app.route('/auth/apple/callback', methods=['POST'])
def auth_apple_callback():
    payload = verify_apple_id_token(request.form.get("id_token") or "")
    if not payload: return "Apple login inválido", 400
    email = payload.get("email"); name = email.split("@")[0] if email else "Usuario Apple"
    user = upsert_user("apple", payload.get("sub"), email, name, None)
    session["user"] = user; return redirect("/")

@app.route('/auth/register', methods=['POST'])
def auth_register():
    d = request.json or {}
    email = (d.get("email") or "").strip().lower(); password = d.get("password") or ""; name = (d.get("name") or "").strip()
    if not email or "@" not in email: return jsonify({"ok": False, "error": "Correo inválido"})
    if len(password) < 6: return jsonify({"ok": False, "error": "Contraseña mínima 6 caracteres"})
    if find_user_by_email(email): return jsonify({"ok": False, "error": "Este correo ya está registrado"})
    user = upsert_user("email", email, email, name or email.split("@")[0], None, password_hash=hash_password(password))
    session["user"] = user; return jsonify({"ok": True, "user": user})

@app.route('/auth/login', methods=['POST'])
def auth_login():
    d = request.json or {}
    email = (d.get("email") or "").strip().lower(); password = d.get("password") or ""
    u = find_user_by_email(email)
    if not u or not u.get("password_hash") or not verify_password(password, u["password_hash"]):
        return jsonify({"ok": False, "error": "Correo o contraseña incorrectos"})
    session["user"] = {"id": u["id"], "provider": u["provider"], "email": u["email"], "name": u["name"], "avatar": u["avatar"]}
    return jsonify({"ok": True, "user": session["user"]})

@app.route('/auth/me')
def auth_me(): return jsonify({"user": session.get("user")})

@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    session.pop("user", None); return jsonify({"ok": True})

@app.route('/api/games')
def get_games():
    if not cargar_cache(): return jsonify({'success': False, 'games': [], 'total': 0, 'count': 0})
    games = _cache["stream"]
    category = request.args.get('category'); search = (request.args.get('search') or '').lower()
    if category: games = [g for g in games if g['category'] == category]
    if search: games = [g for g in games if search in g['title'].lower()]
    total = len(games); offset = max(0, int(request.args.get('offset', 0))); limit = int(request.args.get('limit', 0)) or total
    return jsonify({'success': True, 'count': min(limit, max(total-offset,0)), 'total': total, 'offset': offset, 'games': games[offset:offset+limit]})

@app.route('/api/curated')
def get_curated():
    if not cargar_cache(): return jsonify({'success': True, 'games': []})
    return jsonify({'success': True, 'games': sorted(_cache["curated"].values(), key=lambda x: x["active_players"], reverse=True)})

@app.route('/api/game/<game_id>')
def get_game(game_id):
    if not cargar_cache(): abort(500)
    if str(game_id).startswith('c'):
        g = _cache["curated"].get(game_id)
        if not g: abort(404)
        return jsonify({'success': True, 'game': g, 'alternativas': []})
    try: idx = int(game_id) - 1
    except ValueError: abort(404)
    if not (0 <= idx < len(_cache["db"])): abort(404)
    g = _cache["db"][idx]
    alts = [x for x in _cache["by_title"].get(norm_title(g["title"]), []) if x["id"] != g["id"] and x.get("sources")][:3]
    alts = [{"id": x["id"], "title": x["title"], "embed_url": x["embed_url"], "sources": x["sources"], "play_url": x["play_url"]} for x in alts]
    return jsonify({'success': True, 'game': g, 'alternativas': alts})

@app.route('/api/categories')
def get_categories():
    if not cargar_cache(): return jsonify({'success': True, 'categories': CATEGORIES_DEF})
    return jsonify({'success': True, 'categories': [dict(c, count=_cache["counts"].get(c["slug"],0)) for c in CATEGORIES_DEF if _cache["counts"].get(c["slug"])]})

@app.route('/api/stats')
def stats():
    cargar_cache(); return jsonify({'success': True, 'total': len(_cache["stream"])})

@app.route('/api/health')
def health(): return jsonify({'status': 'ok'})

@app.route('/px/<path:target>')
def proxy_juego(target):
    if not http_requests: abort(502)
    url = target if target.startswith("http") else "https://" + target
    try: r = http_requests.get(url, headers=UA, timeout=15)
    except Exception: abort(502)
    html = r.text
    html = re.sub(r'<meta[^>]+http-equiv=["\']?(Content-Security-Policy|X-Frame-Options)["\']?[^>]*>', '', html, flags=re.I)
    base = urlparse(url).scheme + "://" + urlparse(url).netloc + "/"
    if "<head>" in html.lower():
        i = html.lower().index("<head>") + 6
        html = html[:i] + MUTE_SCRIPT + f'<base href="{base}">' + html[i:]
    else:
        html = MUTE_SCRIPT + f'<base href="{base}">' + html
    resp = app.make_response(html); resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


try:
    ensure_users(); cargar_cache()
except Exception as _e:
    print("prewarm skip:", _e)

PORT = int(os.environ.get("PORT", "5000"))
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)