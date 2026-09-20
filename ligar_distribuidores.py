import sqlite3, os, json, shutil, time
import xml.etree.ElementTree as ET
try:
    import requests
except ImportError:
    requests = None

DB = "juegos.db"
TOP_TOTAL = 5000
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0 Safari/537.36"}

GM_FEED   = "https://gamemonetize.com/feed.php?format=0&num=20000"
GD_RSS    = "https://catalog.api.gamedistribution.com/api/v2.0/rss/All"
ITCH_KEY  = "3XqyxYbYA3hiBze4kjXdJOlPTdVRPfSRukExJjtQ"
ITCH_URL  = "https://itch.io/api/1/{}/search?query=html5"

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

def cat_slug(raw): return CAT_MAP.get(str(raw or "").split(",")[0].strip().lower(), "arcade")

def modernidad(item, idx, total):
    score = 0.0
    for k in ("plays","play_count","playCount","views","downloads"):
        if item.get(k):
            try: score += float(item[k]) * 100
            except Exception: pass
    for k in ("rating","rate","stars"):
        if item.get(k):
            try: score += float(item[k]) * 1e6
            except Exception: pass
    nid = item.get("id") or item.get("game_id") or item.get("AssetId") or ""
    if str(nid).isdigit():
        score += float(nid) * 10
    else:
        score += (total - idx) * 10
    return score

# ===== GAME DISTRIBUTION (parsea XML RSS) =====
def cargar_gd():
    if not requests: return []
    try:
        r = requests.get(GD_RSS, headers=UA, timeout=90)
        if r.status_code != 200:
            print(f"   ⚠️  GD respondió HTTP {r.status_code}")
            return []
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"   ⚠️  Error parseando GD: {e}")
        return []

    out = []
    items = root.findall(".//item") or root.findall(".//channel/item")
    total = len(items)
    for i, it in enumerate(items):
        def t(tag):
            el = it.find(tag) or it.find(".//" + tag)
            return el.text.strip() if el is not None and el.text else ""
        gid = t("id") or t("AssetId") or t("link").split("/")[-1].split(".")[0] if t("link") else ""
        if not gid: continue
        titulo = t("title") or ""
        desc = (t("description") or "")[:220]
        cat = cat_slug(t("category"))
        img = t("image") or t("thumb") or f"https://img.gamedistribution.com/{gid}.jpg"
        embed = f"https://html5.gamedistribution.com/{gid}/"
        out.append({
            "gid": gid, "titulo": titulo, "desc": desc, "cat": cat,
            "img": img, "embed": embed, "dist": "gamedistribution",
            "score": modernidad({"id": gid}, i, total),
        })
    return out

# ===== GAME MONETIZE (JSON) =====
def cargar_gm():
    if not requests: return []
    try:
        r = requests.get(GM_FEED, headers=UA, timeout=90)
        data = json.loads(r.text)
    except Exception as e:
        print(f"   ⚠️  Error GM: {e}")
        return []
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

# ===== ITCH.IO (búsqueda pública de juegos HTML5) =====
def cargar_itch():
    if not requests or not ITCH_KEY: return []
    out = []
    page = 1
    while True:
        url = ITCH_URL.format(ITCH_KEY) + f"&page={page}&count=50"
        try:
            r = requests.get(url, headers=UA, timeout=60)
            data = json.loads(r.text)
        except Exception as e:
            print(f"   ⚠️  Error itch p{page}: {e}")
            break
        games = data.get("games", [])
        if not games: break
        total = len(games)
        for i, it in enumerate(games):
            gid = str(it.get("id") or "")
            if not gid: continue
            # Solo juegos web embeddables
            classification = it.get("classification") or "game"
            if classification != "game": continue
            url_game = it.get("url") or ""
            if not url_game: continue
            out.append({
                "gid": f"itch_{gid}",
                "titulo": it.get("title") or "",
                "desc": (it.get("short_text") or "")[:220],
                "cat": "arcade",
                "img": (it.get("cover") or {}).get("url") or (it.get("still_cover") or {}).get("url") or "",
                "embed": url_game,
                "dist": "itchio",
                "score": modernidad(it, i, total) + (it.get("views") or 0) * 50 + (it.get("rating") or 0) * 2e6,
            })
        page += 1
        if page > 20: break  # tope de seguridad (20 páginas × 50 = 1000 juegos)
    return out

def main():
    if not requests:
        print("❌ pip install requests"); return

    bk = f"juegos.db.backup_{int(time.time())}"
    shutil.copy2(DB, bk)
    print(f"🛡️  Backup: {bk}")

    conn = sqlite3.connect(DB)
    ensure_cols(conn)

    print("📥 GameDistribution (XML)...")
    gd = cargar_gd()
    print(f"   → {len(gd)} juegos")

    print("📥 GameMonetize (JSON)...")
    gm = cargar_gm()
    print(f"   → {len(gm)} juegos")

    print("📥 itch.io (paginado)...")
    itch = cargar_itch()
    print(f"   → {len(itch)} juegos")

    todos = gd + gm + itch
    print(f"\n🔀 Combinado: {len(todos)} juegos")

    todos.sort(key=lambda x: x["score"], reverse=True)
    top = todos[:TOP_TOTAL]

    from collections import Counter
    dist_count = Counter(g["dist"] for g in top)
    print(f"\n🏆 TOP {len(top)} seleccionado:")
    for dist, count in dist_count.items():
        print(f"   • {dist}: {count}")

    # 🔥 LIMPIEZA CORRECTA: borrar TODO excepto curados
    print(f"\n🧹 Limpiando BD completa (conservando curados)...")
    cur = conn.execute("SELECT COUNT(*) FROM juegos WHERE fuente='curado'").fetchone()[0]
    conn.execute("DELETE FROM juegos WHERE fuente != 'curado' OR fuente IS NULL")
    borrados = conn.total_changes
    print(f"   ✓ Curados conservados: {cur}")

    print(f"💾 Insertando {len(top)} juegos...")
    for g in top:
        conn.execute("""INSERT INTO juegos (id,titulo,descripcion,categoria,imagen_url,iframe_url,distribuidor,fuente,score)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                     (g["gid"], g["titulo"], g["desc"], g["cat"], g["img"], g["embed"], g["dist"], g["dist"], g["score"]))

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM juegos").fetchone()[0]
    cur_final = conn.execute("SELECT COUNT(*) FROM juegos WHERE fuente='curado'").fetchone()[0]
    conn.close()

    print(f"\n🎉 ÉXITO:")
    print(f"   • Total en BD: {total} juegos")
    print(f"   • Curados: {cur_final}")
    print(f"   • Distribuidores: {total - cur_final}")
    print(f"\n⚠️  REGENERA tu API key de itch.io (compartida en texto plano)")

if __name__ == "__main__":
    main()