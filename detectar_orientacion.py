import sqlite3
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0 Safari/537.36",
      "Accept": "application/json"}

GM_FEED = "https://gamemonetize.com/feed.json"
GD_FEED = "https://catalog.api.gamedistribution.com/api/v2.0/rss/All"


def clasificar(w, h):
    """Devuelve 'horizontal', 'vertical' o 'auto' según proporción real."""
    if not w or not h:
        return None
    r = w / h
    if r >= 1.2:
        return "horizontal"
    if r <= 0.85:
        return "vertical"
    return "auto"


def dims(item):
    w = item.get("width") or item.get("Width") or item.get("gameWidth") or 0
    h = item.get("height") or item.get("Height") or item.get("gameHeight") or 0
    try:
        return int(w), int(h)
    except Exception:
        return 0, 0


def asegurar_columna(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(juegos)")]
    if "orientacion" not in cols:
        conn.execute("ALTER TABLE juegos ADD COLUMN orientacion TEXT")
        conn.commit()


def main():
    conn = sqlite3.connect("juegos.db")
    asegurar_columna(conn)

    updates = {}

    # --- GameMonetize: trae width/height reales por juego ---
    try:
        print("📡 Leyendo feed GameMonetize...")
        data = requests.get(GM_FEED, headers=UA, timeout=60).json()
        n = 0
        for item in data:
            gid = f"gm_{item.get('id')}"
            o = clasificar(*dims(item))
            if o:
                updates[gid] = o
                n += 1
        print(f"   ✅ {n} juegos GameMonetize con orientación real")
    except Exception as e:
        print(f"   ❌ GameMonetize falló: {e}")

    # --- GameDistribution: si el feed trae Width/Height, usarlos ---
    try:
        print("📡 Leyendo feed GameDistribution...")
        data = requests.get(GD_FEED, headers=UA, timeout=60).json()
        n = 0
        for item in data:
            gid = str(item.get("AssetId") or item.get("Id") or item.get("Md5") or "")
            if not gid:
                continue
            o = clasificar(*dims(item))
            if o:
                updates[gid] = o
                n += 1
        print(f"   ✅ {n} juegos GameDistribution con orientación real")
    except Exception as e:
        print(f"   ⚠️ GameDistribution sin dimensiones: {e}")

    # --- Aplicar a la BD ---
    cnt = 0
    for gid, o in updates.items():
        cur = conn.execute("UPDATE juegos SET orientacion=? WHERE id=?", (o, gid))
        cnt += cur.rowcount
    conn.commit()

    # Resumen
    res = conn.execute("SELECT orientacion, COUNT(*) FROM juegos GROUP BY orientacion").fetchall()
    conn.close()
    print(f"\n💾 {cnt} filas actualizadas en juegos.db")
    print("📊 Distribución final:")
    for o, c in res:
        print(f"   {o or '(sin dato → heurística)'}: {c}")
    print("\n▶️  Reinicia ahora: python app.py")


if __name__ == "__main__":
    main()