import sqlite3, os, json, shutil, time
try:
    import requests
except ImportError:
    requests = None

DB = "juegos.db"
TOP_TOTAL = 5000  # Solo los mejores 5000 COMBINADOS de los 3 distribuidores
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0 Safari/537.36",
      "Accept": "application/json"}

GD_RSS  = "https://catalog.api.gamedistribution.com/api/v2.0/rss/All"
GM_FEED = "https://gamemonetize.com/feed.php?format=0&num=20000"
ITCH_KEY = "3XqyxYbYA3hiBze4kjXdJOlPTdVRPfSRukExJjtQ"  # Tu clave API

CAT_MAP = {"action":"accion","adventure":"aventuras","arcade":"arcade","board":"mesa","card":"cartas",
 "cards":"cartas","clicker":"clic","click":"clic","driving":"conducir","racing":"conducir","car":"conducir",
 "io":"io",".io":"io","multiplayer":"io","puzzle":"puzzle","skill":"arcade","educational":"puzzle",
 "shooting":"disparos","shooter":"disparos","simulation":"simulacion","sports":"deportes",
 "strategy":"estrategia","trivia":"trivia","quiz":"trivia","word":"palabras","text":"palabras","girls":"arcade"}

def ensure_cols(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(juegos)")]
    for col, typ in (("distribuidor","TEXT"),("tag","TEXT"),("fuente","TEXT"),("sources","TEXT"),("orientacion","TEXT"),("score","REAL")):
        if col not in cols:
            try: conn.execute(f"ALTER TABLE juegos ADD COLUMN {col} {typ}")
            except Exception: pass
    conn.commit()

def fetch_json(url, headers=None):
    if not requests: return None
    try:
        r = requests.get(url, headers=headers or UA, timeout=90)
        try: return json.loads(r.text)
        except Exception: return None
    except Exception:
        return None

def cat_slug(raw): return CAT_MAP.get(str(raw or "").split(",")[0].strip().lower(), "arcade")

def modernidad(item, idx, total):
    """Score unificado para comparar entre distribuidores."""
    score = 0.0
    # Plays/views (si existen)
    for k in ("plays","play_count","playCount","views","downloads"):
        if item.get(k): 
            try: score += float(item[k]) * 100
            except Exception: pass
    # Rating (si existe)
    for k in ("rating","rate","stars"):
        if item.get(k):
            try: score += float(item[k]) * 1e6
            except Exception: pass
    # Fecha (timestamp si es numérico)
    for k in ("updated","updated_at","date","created","published","created_at"):
        v = item.get(k)
        if v:
            try: score += float(v) if str(v).replace('.','',1).isdigit() else 0
            except Exception: pass
    # ID secuencial (más alto = más nuevo en GM/GD)
    nid = item.get("id") or item.get("game_id") or item.get("AssetId") or ""
    if str(nid).isdigit():
        score += float(nid) * 10  # peso al ID
    else:
        score += (total - idx) * 10  # orden del feed como respaldo
    return score

def cargar_gd():
    """GameDistribution"""
    data = fetch_json(GD_RSS)
    items = data if isinstance(data, list) else (data or {}).get("games", (data or {}).get("items", []))
    out = []
    total = len(items)
    for i, it in enumerate(items):
        if not isinstance(it, dict): continue
        gid = str(it.get("AssetId") or it.get("Id") or it.get("id") or "")
        if not gid: continue
        img = it.get("Thumb") or it.get("Asset") or it.get("image")
        if isinstance(img, list): img = img[0] if img else None
        out.append({
            "gid": gid,
            "titulo": it.get("Title") or it.get("title") or "",
            "desc": (it.get("Description") or it.get("description") or "")[:220],
            "cat": cat_slug(it.get("Category") or it.get("category")),
            "img": img or f"https://img.gamedistribution.com/{gid}.jpg",
            "embed": f"https://html5.gamedistribution.com/{gid}/",
            "dist": "gamedistribution",
            "score": modernidad(it, i, total),
        })
    return out

def cargar_gm():
    """GameMonetize"""
    data = fetch_json(GM_FEED)
    items = data if isinstance(data, list) else (data or {}).get("games", [])
    out = []
    total = len(items)
    for i, it in enumerate(items):
        if not isinstance(it, dict): continue
        raw = str(it.get("id") or it.get("game_id") or "")
        if not raw: continue
        out.append({
            "gid": f"gm_{raw}",
            "titulo": it.get("title") or it.get("name") or "",
            "desc": (it.get("description") or it.get("desc") or "")[:220],
            "cat": cat_slug(it.get("category")),
            "img": it.get("thumb") or it.get("image") or f"https://img.gamemonetize.com/{raw}/512x384.jpg",
            "embed": f"https://html5.gamemonetize.co/{raw}/",
            "dist": "gamemonetize",
            "score": modernidad(it, i, total),
        })
    return out

def cargar_itch():
    """itch.io (solo juegos web embeddables)"""
    if not ITCH_KEY: return []
    data = fetch_json("https://itch.io/api/1/x/whisper/games?platform=web&tag=html5",
                      headers={"Authorization": ITCH_KEY})
    items = (data or {}).get("games", [])
    out = []
    total = len(items)
    for i, it in enumerate(items):
        gid = str(it.get("id") or "")
        if not gid: continue
        # Solo juegos embeddables
        if not it.get("embeddable", False) and not (it.get("classification") == "game"):
            continue
        url = it.get("url") or ""
        if not url: continue
        out.append({
            "gid": f"itch_{gid}",
            "titulo": it.get("title") or "",
            "desc": (it.get("short_text") or it.get("text") or "")[:220],
            "cat": "arcade",
            "img": (it.get("cover") or {}).get("url") or "",
            "embed": url,  # itch.io usa la URL directa como embed
            "dist": "itchio",
            "score": modernidad(it, i, total),
        })
    return out

def main():
    if not requests:
        print("❌ pip install requests"); return
    
    # Backup de seguridad
    bk = f"juegos.db.backup_{int(time.time())}"
    shutil.copy2(DB, bk)
    print(f"🛡️  Backup: {bk}")

    conn = sqlite3.connect(DB)
    ensure_cols(conn)

    # Cargar de los 3 distribuidores
    print("📥 Descargando de GameDistribution...")
    gd = cargar_gd()
    print(f"   → {len(gd)} juegos")
    
    print("📥 Descargando de GameMonetize...")
    gm = cargar_gm()
    print(f"   → {len(gm)} juegos")
    
    print("📥 Descargando de itch.io...")
    itch = cargar_itch()
    print(f"   → {len(itch)} juegos")

    # COMBINAR todos
    todos = gd + gm + itch
    print(f"\n🔀 Total combinado: {len(todos)} juegos")

    # ORDENAR por score (más moderno/mejor primero)
    todos.sort(key=lambda x: x["score"], reverse=True)

    # SELECCIONAR solo los TOP 5000
    top = todos[:TOP_TOTAL]
    
    # Estadísticas de la selección
    from collections import Counter
    dist_count = Counter(g["dist"] for g in top)
    print(f"\n🏆 TOP {len(top)} seleccionado:")
    for dist, count in dist_count.items():
        print(f"   • {dist}: {count}")

    # LIMPIAR la BD de juegos de distribuidores (conservar curados)
    print(f"\n🧹 Limpiando BD de juegos anteriores...")
    conn.execute("DELETE FROM juegos WHERE distribuidor IS NOT NULL AND distribuidor != ''")
    
    # INSERTAR solo los TOP 5000
    print(f"💾 Insertando {len(top)} juegos seleccionados...")
    for g in top:
        conn.execute("""INSERT INTO juegos (id,titulo,descripcion,categoria,imagen_url,iframe_url,distribuidor,fuente,score)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET titulo=excluded.titulo, descripcion=excluded.descripcion,
                        categoria=excluded.categoria, imagen_url=excluded.imagen_url, iframe_url=excluded.iframe_url,
                        distribuidor=excluded.distribuidor, score=excluded.score""",
                     (g["gid"], g["titulo"], g["desc"], g["cat"], g["img"], g["embed"], g["dist"], g["dist"], g["score"]))

    conn.commit()
    
    # Estadísticas finales
    total = conn.execute("SELECT COUNT(*) FROM juegos").fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM juegos WHERE fuente='curado'").fetchone()[0]
    conn.close()
    
    print(f"\n🎉 ÉXITO:")
    print(f"   • Total en BD: {total} juegos")
    print(f"   • Curados fijos: {cur}")
    print(f"   • De distribuidores: {total - cur}")
    print(f"\n▶️  Reinicia app.py para ver los cambios")
    print(f"⚠️  REGENERA tu API key de itch.io (la compartiste en texto plano)")

if __name__ == "__main__":
    main()