import sqlite3
import requests
import time

# ===== FUENTE 1: GameDistribution (endpoint básico que sí funciona) =====
GD_API_URL = "https://catalog.api.gamedistribution.com/api/v2.0/rss/All"

# ===== FUENTE 2: GameMonetize (feed JSON público funcional) =====
GM_FEED_URL = "https://gamemonetize.com/feed.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def inicializar_bd():
    """Crea la base de datos y la tabla 'juegos' si no existen."""
    conn = sqlite3.connect("juegos.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS juegos (
            id TEXT PRIMARY KEY,
            titulo TEXT,
            descripcion TEXT,
            categoria TEXT,
            imagen_url TEXT,
            iframe_url TEXT,
            fuente TEXT
        )
    """)
    # Migración: agregar columna 'fuente' si no existe
    try:
        cursor.execute("ALTER TABLE juegos ADD COLUMN fuente TEXT")
    except sqlite3.OperationalError:
        pass  # Ya existe
    conn.commit()
    conn.close()


def importar_gamedistribution():
    """Descarga juegos de GameDistribution (endpoint básico)."""
    print("\n📡 [GameDistribution] Descargando desde feed All...")
    try:
        r = requests.get(GD_API_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        juegos_raw = r.json()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return 0

    conn = sqlite3.connect("juegos.db")
    cursor = conn.cursor()
    nuevos = 0

    for juego in juegos_raw:
        id_juego = str(
            juego.get("AssetId") or juego.get("Id") or juego.get("Md5") or ""
        ).strip()
        if not id_juego:
            continue

        titulo = juego.get("Title", "Sin título")
        descripcion = juego.get("Description", "")

        categoria_raw = juego.get("Category", "")
        if isinstance(categoria_raw, list):
            categoria = ", ".join(str(c) for c in categoria_raw)
        else:
            categoria = str(categoria_raw)

        # Imagen
        imagen_url = ""
        assets = juego.get("Asset") or juego.get("Assets") or []
        if isinstance(assets, list) and len(assets) > 0:
            primer = assets[0]
            if isinstance(primer, dict):
                imagen_url = primer.get("name") or primer.get("url") or ""
            else:
                imagen_url = str(primer)
        if not imagen_url:
            imagen_url = (
                juego.get("Thumb") or juego.get("Thumbnail")
                or juego.get("Image") or ""
            )
        if imagen_url and not imagen_url.startswith("http"):
            imagen_url = f"https://img.gamedistribution.com/{id_juego}.jpg"

        # Iframe
        iframe_url = juego.get("Url") or juego.get("GameUrl") or ""
        if not iframe_url.startswith("http"):
            iframe_url = f"https://html5.gamedistribution.com/{id_juego}/"

        cursor.execute(
            """
            INSERT INTO juegos (id, titulo, descripcion, categoria, imagen_url, iframe_url, fuente)
            VALUES (?, ?, ?, ?, ?, ?, 'gamedistribution')
            ON CONFLICT(id) DO UPDATE SET
                titulo=excluded.titulo,
                descripcion=excluded.descripcion,
                categoria=excluded.categoria,
                imagen_url=excluded.imagen_url,
                iframe_url=excluded.iframe_url
            """,
            (id_juego, titulo, descripcion, categoria, imagen_url, iframe_url),
        )
        nuevos += 1

    conn.commit()
    conn.close()
    print(f"   ✅ {nuevos} juegos de GameDistribution procesados")
    return nuevos


def importar_gamemonetize():
    """Descarga juegos del feed JSON de GameMonetize."""
    print("\n📡 [GameMonetize] Descargando desde feed.json...")
    try:
        r = requests.get(GM_FEED_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        juegos_raw = r.json()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return 0

    if not isinstance(juegos_raw, list):
        print("   ⚠️ Formato de respuesta inesperado")
        return 0

    conn = sqlite3.connect("juegos.db")
    cursor = conn.cursor()
    nuevos = 0

    for juego in juegos_raw:
        # ID único con prefijo para no colisionar con GameDistribution
        id_gm = str(juego.get("id", "")).strip()
        if not id_gm:
            continue
        id_juego = f"gm_{id_gm}"  # Prefijo 'gm_' para distinguir

        titulo = juego.get("title", "Sin título")
        descripcion = juego.get("description", "")
        categoria = juego.get("category", "Arcade")

        # Imagen: el feed ya trae URL completa
        imagen_url = juego.get("thumb", "")
        if not imagen_url and id_gm:
            imagen_url = f"https://img.gamemonetize.com/{id_gm}/512x384.jpg"

        # URL del iframe: ya viene completa
        iframe_url = juego.get("url", "")
        if not iframe_url and id_gm:
            iframe_url = f"https://html5.gamemonetize.co/{id_gm}/"

        cursor.execute(
            """
            INSERT INTO juegos (id, titulo, descripcion, categoria, imagen_url, iframe_url, fuente)
            VALUES (?, ?, ?, ?, ?, ?, 'gamemonetize')
            ON CONFLICT(id) DO UPDATE SET
                titulo=excluded.titulo,
                descripcion=excluded.descripcion,
                categoria=excluded.categoria,
                imagen_url=excluded.imagen_url,
                iframe_url=excluded.iframe_url
            """,
            (id_juego, titulo, descripcion, categoria, imagen_url, iframe_url),
        )
        nuevos += 1

    conn.commit()
    conn.close()
    print(f"   ✅ {nuevos} juegos de GameMonetize procesados")
    return nuevos


def importar_catalogo():
    print("=" * 60)
    print("🎮 IMPORTADOR DE JUEGOS — Multi-fuente")
    print("=" * 60)

    inicializar_bd()

    # Contar antes
    conn = sqlite3.connect("juegos.db")
    antes = conn.execute("SELECT COUNT(*) FROM juegos").fetchone()[0]
    conn.close()

    # Importar de ambas fuentes
    gd_count = importar_gamedistribution()
    time.sleep(1)
    gm_count = importar_gamemonetize()

    # Contar después
    conn = sqlite3.connect("juegos.db")
    despues = conn.execute("SELECT COUNT(*) FROM juegos").fetchone()[0]
    
    # Estadísticas por fuente
    gd_total = conn.execute("SELECT COUNT(*) FROM juegos WHERE fuente='gamedistribution'").fetchone()[0]
    gm_total = conn.execute("SELECT COUNT(*) FROM juegos WHERE fuente='gamemonetize'").fetchone()[0]
    conn.close()

    print("\n" + "=" * 60)
    print("🎮 ¡Proceso completado!")
    print(f"   📥 Antes: {antes} juegos")
    print(f"   📥 Ahora: {despues} juegos (nuevos: {despues - antes})")
    print(f"   🔵 GameDistribution: {gd_total} juegos")
    print(f"   🟢 GameMonetize: {gm_total} juegos")
    print(f"   📁 Archivo: juegos.db")
    print("=" * 60)


if __name__ == "__main__":
    importar_catalogo()