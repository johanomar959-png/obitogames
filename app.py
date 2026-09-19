import sqlite3
import zlib
import os
import re
import json
from urllib.parse import urljoin, urlparse
from flask import Flask, render_template, jsonify, request, abort

try:
    import requests
except ImportError:
    requests = None

app = Flask(__name__)
DB_FILE = "juegos.db"
THUMB_DIR = os.path.join("static", "thumbs", "curated")

MI_DOMINIO = ""  # pon tu dominio cuando lo tengas

MANUAL_PHOTOS = {
    "Smash Karts": "https://imgs.crazygames.com/smash-karts_16x9/20260210123937/smash-karts_16x9-cover?metadata=none&quality=100&width=1200&height=630&fit=crop",
}

ORIENT_CURATED = {
    "Smash Karts": "horizontal", "1v1.LOL": "horizontal", "Venge.io": "horizontal",
    "Slither.io": "auto", "Agar.io": "auto", "Shell Shockers": "horizontal",
    "ZombsRoyale.io": "horizontal", "Skribbl.io": "horizontal", "Diep.io": "auto",
    "Krunker.io": "horizontal", "Little Big Snake": "auto", "Hole.io": "auto",
    "Paper.io 2": "auto", "EvoWars.io": "auto", "Surviv.io": "horizontal",
    "Wings.io": "horizontal", "Bonk.io": "horizontal", "Gartic Phone": "horizontal",
    "2048": "auto", "Flappy Bird": "auto", "Pac-Man": "horizontal",
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

CURATED_RAW = [
    ("Smash Karts", "io", "io", "🏎️", ["https://smashkarts.io/"], 980000, 1500000),
    ("1v1.LOL", "batalla", "disparos", "🔫", ["https://1v1.lol/"], 950000, 1400000),
    ("Venge.io", "batalla", "disparos", "🥷", ["https://venge.io/"], 900000, 1300000),
    ("Slither.io", "io", "io", "🐍", ["https://slither.io/"], 800000, 1050000),
    ("Agar.io", "io", "io", "🦠", ["https://agar.io/"], 760000, 980000),
    ("Shell Shockers", "batalla", "disparos", "🥚", ["https://shellshock.io/"], 680000, 880000),
    ("ZombsRoyale.io", "io", "io", "🧟", ["https://zombsroyale.io/"], 660000, 860000),
    ("Skribbl.io", "mente", "palabras", "✏️", ["https://skribbl.io/"], 640000, 840000),
    ("Diep.io", "io", "io", "🔵", ["https://diep.io/"], 620000, 820000),
    ("Krunker.io", "batalla", "disparos", "💀", ["https://krunker.io/"], 600000, 800000),
    ("Little Big Snake", "io", "io", "🐍", ["https://littlebigsnake.com/"], 580000, 780000),
    ("Hole.io", "io", "io", "🕳️", ["https://hole-io.com/"], 560000, 760000),
    ("Paper.io 2", "io", "io", "📄", ["https://paper-io.com/"], 540000, 740000),
    ("EvoWars.io", "io", "io", "⚔️", ["https://evowars.io/"], 520000, 720000),
    ("Surviv.io", "io", "io", "🪖", ["https://surviv.io/"], 500000, 700000),
    ("Wings.io", "io", "io", "✈️", ["https://wings.io/"], 480000, 680000),
    ("Bonk.io", "io", "io", "⚾", ["https://bonk.io/"], 460000, 660000),
    ("Gartic Phone", "mente", "palabras", "🎨", ["https://garticphone.com/"], 780000, 1000000),
    ("2048", "mente", "puzzle", "🔢", ["https://gabrielecirulli.github.io/2048/"], 340000, 540000),
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
    if not requests:
        return True
    if url in _frame_cache:
        return _frame_cache[url]
    ok = True
    try:
        r = requests.get(url, headers=UA, timeout=10, stream=True)
        xfo = (r.headers.get("X-Frame-Options") or "").strip().lower()
        csp = (r.headers.get("Content-Security-Policy") or "").lower()
        if xfo in ("deny", "sameorigin") or "frame-ancestors" in csp:
            ok = False
        r.close()
    except Exception:
        ok = True
    _frame_cache[url] = ok
    return ok


def orden_fuentes(curado, base_src):
    if not base_src:
        return []
    if curado and not fuente_embebible(base_src[0]):
        return [con_proxy(base_src[0])] + base_src[1:]
    return base_src + [con_proxy(base_src[0])]


def descargar_imagen_directa(url, destino):
    if not requests:
        return False
    try:
        ri = requests.get(url, headers=UA, timeout=25)
        if ri.status_code == 200 and len(ri.content) > 15000:
            with open(destino, "wb") as f:
                f.write(ri.content)
            return True
    except Exception:
        pass
    return False


def descargar_og_image(url, destino):
    if not requests:
        return False
    try:
        r = requests.get(url, headers=UA, timeout=12, allow_redirects=True)
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
        ri = requests.get(img, headers=UA, timeout=20)
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
        need = True
        if have:
            need = sources.get(f"c{i}") != (want or "og")
        if need:
            print(f"   🖼️  Descargando foto de {title}...")
            done = descargar_imagen_directa(want, path) if want else False
            if not done:
                done = descargar_og_image(srcs[0], path)
            if done:
                sources[f"c{i}"] = want or "og"
                have = os.path.exists(path) and os.path.getsize(path) > 15000
            elif os.path.exists(path):
                os.remove(path)
                have = False
        if have:
            ok.add(f"c{i}")
        else:
            print(f"   ❌ {title} sin foto → descartado")
    with open(marker_path, "w") as f:
        json.dump(sources, f)
    return ok


_ok = ensure_curated_thumbs()

CURATED = []
for i, (t, tag, cat, em, sources, pl, lk) in enumerate(CURATED_RAW, start=1):
    if f"c{i}" not in _ok:
        continue
    full = orden_fuentes(True, sources)
    CURATED.append({
        "id": f"c{i}", "title": t, "tag": tag, "category": cat, "emoji": em,
        "gradient": GRADIENTS.get(cat, "from-zinc-800 to-black"),
        "logo": f"/static/thumbs/curated/c{i}.jpg",
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


def construir_fuentes(gid, stored_url):
    stored = (stored_url or "").strip()
    if gid.startswith("gm_"):
        cand = [stored, f"https://html5.gamemonetize.co/{gid[3:]}/"]
    else:
        cand = [f"https://html5.gamedistribution.com/{gid}/", stored]
    out = []
    for c in cand:
        if c and c.startswith("http") and c not in out:
            out.append(c)
    return out


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
            (g["id"], g["title"], g["desc"], g["category"], g["logo"], g["embed_url"], g["tag"], "curado", "|".join(g["sources"])))
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
            full = orden_fuentes(True, [s for s in raw if s and s.startswith("http")])
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
                if gid.startswith("gm_"):
                    imagen = f"https://img.gamemonetize.com/{gid[3:]}/512x384.jpg"
                else:
                    imagen = f"https://img.gamedistribution.com/{gid}.jpg"
            slug = mapear_categoria(r["categoria"])
            base_src = construir_fuentes(gid, r["iframe_url"])
            full = orden_fuentes(False, base_src)
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

    cur_list = sorted(curated.values(), key=lambda x: x["active_players"], reverse=True)
    cur_titles = {norm_title(g["title"]) for g in cur_list}
    db_sorted = sorted([g for g in db if norm_title(g["title"]) not in cur_titles],
                       key=lambda x: x["active_players"], reverse=True)
    stream = []
    i = j = 0
    while j < len(cur_list) or i < len(db_sorted):
        if j < len(cur_list) and (i >= len(db_sorted) or j <= i):
            stream.append(cur_list[j]); j += 1
        else:
            stream.append(db_sorted[i]); i += 1

    _cache["db"], _cache["curated"], _cache["stream"], _cache["counts"], _cache["by_title"], _cache["ready"] = db, curated, stream, counts, by_title, True
    print(f"✅ Caché lista: {len(stream)} juegos ligados ({len(cur_list)} oficiales + {len(db_sorted)} catálogo)")
    return True


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/robots.txt')
def robots():
    return "User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"}


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
    if not requests:
        abort(502)
    url = target if target.startswith("http") else "https://" + target
    try:
        r = requests.get(url, headers=UA, timeout=15)
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


# Precarga para servidores de producción (gunicorn/Render)
try:
    cargar_cache()
except Exception as _e:
    print("prewarm skip:", _e)

PORT = int(os.environ.get("PORT", "5000"))
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

if __name__ == '__main__':
    print("=" * 60)
    print(f"📂 Carpeta: {os.getcwd()} | BD existe: {os.path.exists(DB_FILE)} | Puerto: {PORT}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)