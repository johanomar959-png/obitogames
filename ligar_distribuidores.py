import sqlite3
import os
import json
import shutil
import time
import re
import html
import xml.etree.ElementTree as ET

try:
    import requests
except ImportError:
    requests = None


# ============================================================
# CONFIGURACIÓN
# ============================================================

DB = "juegos.db"
TOP_TOTAL = 5000

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

# GameDistribution:
# Endpoint paginado actual/flexible.
GD_JSON = (
    "https://catalog.api.gamedistribution.com/api/v2.0/rss/All/"
    "?collection=All"
    "&categories=All"
    "&tags=All"
    "&subType=All"
    "&type=All"
    "&mobile=All"
    "&rewarded=all"
    "&amount=40"
    "&page={page}"
    "&format=json"
)

GD_XML = (
    "https://catalog.api.gamedistribution.com/api/v2.0/rss/All/"
    "?collection=All"
    "&categories=All"
    "&tags=All"
    "&subType=All"
    "&type=All"
    "&mobile=All"
    "&rewarded=all"
    "&amount=40"
    "&page={page}"
    "&format=xml"
)

GM_FEED = "https://gamemonetize.com/feed.php?format=0&num=20000"

# itch.io:
# Se usa el RSS público de juegos para navegador.
# No dependemos de la API legacy para descubrir juegos.
ITCH_FEEDS = [
    "https://itch.io/games/top-rated/html5/platform-web.xml",
    "https://itch.io/games/new-and-popular/html5/platform-web.xml",
    "https://itch.io/games/most-recent/html5/platform-web.xml",
]

# Cantidad máxima de páginas RSS de itch.
ITCH_MAX_PAGES = 20

# La API key anterior estaba expuesta.
# Se mantiene como compatibilidad opcional, pero NO es necesaria
# para el nuevo método RSS.
ITCH_KEY = ""


# ============================================================
# CATEGORÍAS
# ============================================================

CAT_MAP = {
    "action": "accion",
    "adventure": "aventuras",
    "arcade": "arcade",
    "board": "mesa",
    "card": "cartas",
    "cards": "cartas",
    "clicker": "clic",
    "click": "clic",
    "driving": "conducir",
    "racing": "conducir",
    "car": "conducir",
    "io": "io",
    ".io": "io",
    "multiplayer": "io",
    "puzzle": "puzzle",
    "skill": "arcade",
    "educational": "puzzle",
    "shooting": "disparos",
    "shooter": "disparos",
    "simulation": "simulacion",
    "sports": "deportes",
    "strategy": "estrategia",
    "trivia": "trivia",
    "quiz": "trivia",
    "word": "palabras",
    "text": "palabras",
    "girls": "arcade",
}


# ============================================================
# UTILIDADES
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = str(value)

    # Elimina HTML
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)

    value = html.unescape(value)

    value = re.sub(r"\s+", " ", value).strip()

    return value


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, bool):
            return float(value)

        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return default


def get_nested(data, *keys, default=None):
    """
    Busca una clave en un diccionario.
    Permite variantes de mayúsculas/minúsculas.
    """
    if not isinstance(data, dict):
        return default

    for key in keys:
        if key in data:
            return data[key]

        key_lower = str(key).lower()

        for real_key, value in data.items():
            if str(real_key).lower() == key_lower:
                return value

    return default


def normalize_url(url):
    if not url:
        return ""

    url = html.unescape(str(url).strip())

    # Quita espacios accidentales
    url = url.replace(" ", "")

    return url


def cat_slug(raw):
    raw = str(raw or "").strip().lower()

    if not raw:
        return "arcade"

    # Puede venir:
    # "Action"
    # "Action,Arcade"
    # "action|arcade"
    # "Action / Arcade"
    raw = re.split(r"[,|/]", raw)[0].strip()

    return CAT_MAP.get(raw, "arcade")


def extract_id_from_url(url):
    if not url:
        return ""

    url = url.rstrip("/")

    last = url.split("/")[-1]

    last = last.split("?")[0]
    last = last.split("#")[0]

    return last


# ============================================================
# SCORE
# ============================================================

def modernidad(item, idx, total):
    score = 0.0

    # Popularidad
    for k in (
        "plays",
        "play_count",
        "playCount",
        "views",
        "views_count",
        "downloads",
        "downloads_count",
        "purchases_count",
    ):
        value = get_nested(item, k)

        if value:
            try:
                score += float(value) * 100
            except Exception:
                pass

    # Rating
    for k in (
        "rating",
        "rate",
        "stars",
        "rating_score",
    ):
        value = get_nested(item, k)

        if value:
            try:
                score += float(value) * 1e6
            except Exception:
                pass

    # IDs grandes suelen corresponder a contenido más reciente
    nid = (
        get_nested(item, "id")
        or get_nested(item, "game_id")
        or get_nested(item, "AssetId")
        or get_nested(item, "asset_id")
        or ""
    )

    if str(nid).isdigit():
        score += float(nid) * 10
    else:
        score += max(0, total - idx) * 10

    return score


# ============================================================
# DATABASE
# ============================================================

def ensure_cols(conn):
    cols = [
        r[1]
        for r in conn.execute("PRAGMA table_info(juegos)")
    ]

    for col, typ in (
        ("distribuidor", "TEXT"),
        ("tag", "TEXT"),
        ("fuente", "TEXT"),
        ("sources", "TEXT"),
        ("orientacion", "TEXT"),
        ("score", "REAL"),
    ):
        if col not in cols:
            try:
                conn.execute(
                    f"ALTER TABLE juegos ADD COLUMN {col} {typ}"
                )
            except Exception:
                pass

    conn.commit()


# ============================================================
# HTTP
# ============================================================

def request_url(url, timeout=90):
    if not requests:
        return None

    try:
        r = requests.get(
            url,
            headers=UA,
            timeout=timeout,
        )

        if r.status_code != 200:
            print(
                f"   ⚠️ HTTP {r.status_code}: {url[:120]}"
            )
            return None

        if not r.content:
            print("   ⚠️ Respuesta vacía")
            return None

        return r

    except requests.RequestException as e:
        print(f"   ⚠️ Error HTTP: {e}")
        return None

    except Exception as e:
        print(f"   ⚠️ Error de conexión: {e}")
        return None


# ============================================================
# GAME DISTRIBUTION
# ============================================================

def parse_gd_items(data):
    """
    GameDistribution cambia ocasionalmente nombres/campos.
    Esta función acepta varias estructuras.
    """

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    possible_keys = (
        "games",
        "items",
        "data",
        "results",
        "result",
    )

    for key in possible_keys:
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            for subkey in possible_keys:
                subvalue = value.get(subkey)

                if isinstance(subvalue, list):
                    return subvalue

    return []


def cargar_gd():
    if not requests:
        return []

    print("   🔎 Intentando GameDistribution JSON paginado...")

    out = []
    seen = set()

    # 500 páginas x 40 = hasta 20.000 registros.
    # El proceso se detiene cuando deja de recibir juegos.
    for page in range(1, 501):

        url = GD_JSON.format(page=page)

        r = request_url(url, timeout=90)

        if not r:
            break

        try:
            data = r.json()
        except Exception as e:
            print(
                f"   ⚠️ GD página {page}: "
                f"respuesta no JSON ({e})"
            )

            # Intentamos XML solamente en esa página.
            xml_url = GD_XML.format(page=page)
            rx = request_url(xml_url, timeout=90)

            if not rx:
                break

            try:
                root = ET.fromstring(rx.content)

                items = (
                    root.findall(".//item")
                    or root.findall(".//channel/item")
                )

                parsed = []

                for it in items:

                    def xtag(tag):
                        el = it.find(tag)

                        if el is None:
                            el = it.find(".//" + tag)

                        if el is not None and el.text:
                            return el.text.strip()

                        return ""

                    parsed.append({
                        "id": xtag("id"),
                        "AssetId": xtag("AssetId"),
                        "title": xtag("title"),
                        "description": xtag("description"),
                        "category": xtag("category"),
                        "image": xtag("image"),
                        "thumb": xtag("thumb"),
                        "link": xtag("link"),
                    })

                items = parsed

            except Exception as xml_error:
                print(
                    f"   ⚠️ GD XML también falló "
                    f"en página {page}: {xml_error}"
                )
                break

        else:
            items = parse_gd_items(data)

        if not items:
            print(
                f"   ✓ GD terminó en página {page - 1}"
            )
            break

        total_page = len(items)

        for i, it in enumerate(items):

            if not isinstance(it, dict):
                continue

            raw_id = (
                get_nested(it, "id")
                or get_nested(it, "game_id")
                or get_nested(it, "AssetId")
                or get_nested(it, "asset_id")
                or ""
            )

            link = normalize_url(
                get_nested(it, "link")
                or get_nested(it, "url")
                or ""
            )

            if not raw_id and link:
                raw_id = extract_id_from_url(link)

            raw_id = str(raw_id).strip()

            if not raw_id:
                continue

            gid = raw_id

            if gid in seen:
                continue

            seen.add(gid)

            titulo = clean_text(
                get_nested(it, "title")
                or get_nested(it, "name")
                or ""
            )

            desc = clean_text(
                get_nested(it, "description")
                or get_nested(it, "desc")
                or ""
            )[:220]

            category = (
                get_nested(it, "category")
                or get_nested(it, "categories")
                or ""
            )

            cat = cat_slug(category)

            img = normalize_url(
                get_nested(it, "image")
                or get_nested(it, "image_url")
                or get_nested(it, "thumb")
                or get_nested(it, "thumbnail")
                or ""
            )

            if not img:
                img = (
                    f"https://img.gamedistribution.com/"
                    f"{gid}.jpg"
                )

            embed = normalize_url(
                get_nested(it, "embed")
                or get_nested(it, "embed_url")
                or ""
            )

            if not embed:
                embed = (
                    f"https://html5.gamedistribution.com/"
                    f"{gid}/"
                )

            score = modernidad(
                it,
                i,
                total_page
            )

            out.append({
                "gid": gid,
                "titulo": titulo,
                "desc": desc,
                "cat": cat,
                "img": img,
                "embed": embed,
                "dist": "gamedistribution",
                "score": score,
            })

        # Si esta página trajo menos que el máximo,
        # probablemente es la última.
        if len(items) < 40:
            print(
                f"   ✓ GD última página detectada: {page}"
            )
            break

        # Evita golpear demasiado rápido la API.
        time.sleep(0.15)

    print(
        f"   ✓ GameDistribution total: {len(out)} juegos"
    )

    return out


# ============================================================
# GAME MONETIZE
# ============================================================

def cargar_gm():
    if not requests:
        return []

    try:
        r = request_url(
            GM_FEED,
            timeout=120
        )

        if not r:
            return []

        try:
            data = r.json()
        except Exception:
            data = json.loads(r.text)

    except Exception as e:
        print(f"   ⚠️ Error GM: {e}")
        return []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = (
            data.get("games")
            or data.get("items")
            or data.get("data")
            or []
        )
    else:
        items = []

    out = []
    seen = set()

    total = len(items)

    for i, it in enumerate(items):

        if not isinstance(it, dict):
            continue

        raw = (
            get_nested(it, "id")
            or get_nested(it, "game_id")
            or get_nested(it, "gameId")
            or ""
        )

        raw = str(raw).strip()

        if not raw:
            continue

        gid = f"gm_{raw}"

        if gid in seen:
            continue

        seen.add(gid)

        titulo = clean_text(
            get_nested(it, "title")
            or get_nested(it, "name")
            or ""
        )

        desc = clean_text(
            get_nested(it, "description")
            or get_nested(it, "desc")
            or ""
        )[:220]

        category = (
            get_nested(it, "category")
            or get_nested(it, "categories")
            or ""
        )

        cat = cat_slug(category)

        img = normalize_url(
            get_nested(it, "thumb")
            or get_nested(it, "thumbnail")
            or get_nested(it, "image")
            or get_nested(it, "image_url")
            or ""
        )

        if not img:
            img = (
                f"https://img.gamemonetize.com/"
                f"{raw}/512x384.jpg"
            )

        embed = normalize_url(
            get_nested(it, "embed")
            or get_nested(it, "embed_url")
            or ""
        )

        if not embed:
            embed = (
                f"https://html5.gamemonetize.co/"
                f"{raw}/"
            )

        out.append({
            "gid": gid,
            "titulo": titulo,
            "desc": desc,
            "cat": cat,
            "img": img,
            "embed": embed,
            "dist": "gamemonetize",
            "score": modernidad(
                it,
                i,
                total
            ),
        })

    return out


# ============================================================
# ITCH.IO RSS
# ============================================================

def parse_itch_rss(content):
    """
    Convierte RSS de itch.io en juegos.
    No depende del API legacy.
    """

    try:
        root = ET.fromstring(content)
    except Exception as e:
        print(
            f"   ⚠️ itch RSS inválido: {e}"
        )
        return []

    items = root.findall(".//item")

    out = []

    for item in items:

        def get_text(tag):
            el = item.find(tag)

            if el is not None and el.text:
                return clean_text(el.text)

            # namespaces
            for child in item:
                if child.tag.lower().endswith("}" + tag.lower()):
                    if child.text:
                        return clean_text(child.text)

            return ""

        title = get_text("title")
        description = get_text("description")
        link = get_text("link")

        if not link:
            continue

        # Buscar imagen en media/content/enclosure
        image = ""

        for child in item:

            tag = child.tag.lower()

            if (
                "content" in tag
                or "thumbnail" in tag
                or "image" in tag
                or "enclosure" in tag
            ):
                image = (
                    child.attrib.get("url")
                    or child.attrib.get("href")
                    or child.text
                    or ""
                )

                if image:
                    break

        # ID estable basado en URL
        gid_raw = extract_id_from_url(link)

        if not gid_raw:
            continue

        gid = f"itch_{gid_raw}"

        out.append({
            "gid": gid,
            "titulo": title,
            "desc": description[:220],
            "cat": "arcade",
            "img": normalize_url(image),
            "embed": link,
            "dist": "itchio",
            "score": 0.0,
        })

    return out


def cargar_itch():
    """
    Descubrimiento público mediante RSS.
    itch.io ofrece RSS para páginas de juegos.
    """

    if not requests:
        return []

    out = []
    seen = set()

    print(
        "   🔎 itch.io mediante RSS público..."
    )

    # Recorremos varios rankings.
    # Esto reemplaza la búsqueda API que estaba devolviendo 0.
    for feed_base in ITCH_FEEDS:

        for page in range(1, ITCH_MAX_PAGES + 1):

            separator = "&" if "?" in feed_base else "?"

            if page == 1:
                url = feed_base
            else:
                url = (
                    f"{feed_base}"
                    f"{separator}page={page}"
                )

            r = request_url(
                url,
                timeout=60
            )

            if not r:
                break

            games = parse_itch_rss(
                r.content
            )

            if not games:
                break

            total = len(games)

            for i, game in enumerate(games):

                gid = game["gid"]

                if gid in seen:
                    continue

                seen.add(gid)

                # El RSS ya viene filtrado por HTML5/Web,
                # pero damos un score adicional.
                game["score"] = (
                    modernidad(
                        {
                            "id": gid,
                        },
                        i,
                        total
                    )
                )

                out.append(game)

            # RSS normalmente devuelve una cantidad limitada.
            if len(games) < 10:
                break

            time.sleep(0.2)

    print(
        f"   ✓ itch.io total: {len(out)} juegos"
    )

    return out


# ============================================================
# DEDUPLICACIÓN
# ============================================================

def deduplicar_juegos(juegos):
    """
    Elimina duplicados por ID y, cuando es posible,
    por URL de iframe.
    """

    resultado = []
    seen_ids = set()
    seen_urls = set()

    for game in juegos:

        gid = str(
            game.get("gid") or ""
        ).strip()

        embed = normalize_url(
            game.get("embed") or ""
        )

        if not gid:
            continue

        if gid in seen_ids:
            continue

        if embed and embed in seen_urls:
            continue

        seen_ids.add(gid)

        if embed:
            seen_urls.add(embed)

        resultado.append(game)

    return resultado


# ============================================================
# MAIN
# ============================================================

def main():

    if not requests:
        print(
            "❌ Falta requests."
        )
        print(
            "   Ejecuta: pip install requests"
        )
        return

    if not os.path.exists(DB):
        print(
            f"❌ No existe la base de datos: {DB}"
        )
        return

    # --------------------------------------------------------
    # BACKUP
    # --------------------------------------------------------

    bk = (
        f"juegos.db.backup_"
        f"{int(time.time())}"
    )

    shutil.copy2(
        DB,
        bk
    )

    print(
        f"🛡️  Backup: {bk}"
    )

    # --------------------------------------------------------
    # DB
    # --------------------------------------------------------

    conn = sqlite3.connect(DB)

    try:
        ensure_cols(conn)

        # ----------------------------------------------------
        # CARGAR FUENTES
        # ----------------------------------------------------

        print(
            "\n📥 GameDistribution..."
        )

        gd = cargar_gd()

        print(
            f"   → {len(gd)} juegos"
        )

        print(
            "\n📥 GameMonetize..."
        )

        gm = cargar_gm()

        print(
            f"   → {len(gm)} juegos"
        )

        print(
            "\n📥 itch.io..."
        )

        itch = cargar_itch()

        print(
            f"   → {len(itch)} juegos"
        )

        # ----------------------------------------------------
        # VALIDACIÓN DE FUENTES
        # ----------------------------------------------------

        fuentes_ok = 0

        if gd:
            fuentes_ok += 1

        if gm:
            fuentes_ok += 1

        if itch:
            fuentes_ok += 1

        print(
            f"\n🔎 Fuentes con resultados: "
            f"{fuentes_ok}/3"
        )

        # GM suele ser la fuente principal.
        # Si absolutamente todo falla, no tocamos la BD.
        if not gd and not gm and not itch:
            print(
                "\n❌ TODAS LAS FUENTES FALLARON."
            )
            print(
                "🛑 No se modificará la base de datos."
            )
            print(
                f"🛡️ El backup queda disponible en: {bk}"
            )
            return

        # ----------------------------------------------------
        # COMBINAR
        # ----------------------------------------------------

        todos = gd + gm + itch

        print(
            f"\n🔀 Combinado antes de deduplicar: "
            f"{len(todos)} juegos"
        )

        todos = deduplicar_juegos(
            todos
        )

        print(
            f"🔗 Después de deduplicar: "
            f"{len(todos)} juegos"
        )

        if not todos:
            print(
                "\n❌ No quedaron juegos válidos."
            )
            print(
                "🛑 No se modificará la base de datos."
            )
            return

        # ----------------------------------------------------
        # ORDENAR
        # ----------------------------------------------------

        todos.sort(
            key=lambda x: safe_float(
                x.get("score")
            ),
            reverse=True
        )

        top = todos[:TOP_TOTAL]

        # ----------------------------------------------------
        # ESTADÍSTICAS
        # ----------------------------------------------------

        from collections import Counter

        dist_count = Counter(
            g["dist"]
            for g in top
        )

        print(
            f"\n🏆 TOP {len(top)} seleccionado:"
        )

        for dist, count in dist_count.items():
            print(
                f"   • {dist}: {count}"
            )

        # ----------------------------------------------------
        # PROTECCIÓN CONTRA RESULTADOS INCOMPLETOS
        # ----------------------------------------------------

        # Si solamente una fuente respondió pero tenemos
        # una cantidad razonable, permitimos actualizar.
        #
        # Pero si una fuente principal devuelve 0 y las otras
        # también están prácticamente vacías, evitamos una
        # limpieza accidental.

        if len(top) < 100:
            print(
                "\n⚠️ Muy pocos juegos obtenidos:"
                f" {len(top)}"
            )

            print(
                "🛑 Para seguridad, no se reemplazará "
                "la colección actual."
            )

            print(
                f"🛡️ Backup: {bk}"
            )

            return

        # ----------------------------------------------------
        # CONTAR CURADOS
        # ----------------------------------------------------

        cur = conn.execute(
            """
            SELECT COUNT(*)
            FROM juegos
            WHERE fuente='curado'
            """
        ).fetchone()[0]

        # ----------------------------------------------------
        # TRANSACCIÓN
        # ----------------------------------------------------

        print(
            "\n🧹 Limpiando distribuidores "
            "y conservando curados..."
        )

        try:

            conn.execute(
                "BEGIN"
            )

            # EXACTAMENTE la lógica original:
            # curados quedan.
            conn.execute(
                """
                DELETE FROM juegos
                WHERE fuente != 'curado'
                   OR fuente IS NULL
                """
            )

            print(
                f"   ✓ Curados conservados: {cur}"
            )

            # ------------------------------------------------
            # INSERTAR
            # ------------------------------------------------

            print(
                f"\n💾 Insertando {len(top)} juegos..."
            )

            insertados = 0

            for g in top:

                conn.execute(
                    """
                    INSERT INTO juegos (
                        id,
                        titulo,
                        descripcion,
                        categoria,
                        imagen_url,
                        iframe_url,
                        distribuidor,
                        fuente,
                        score
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        g["gid"],
                        g["titulo"],
                        g["desc"],
                        g["cat"],
                        g["img"],
                        g["embed"],
                        g["dist"],
                        g["dist"],
                        safe_float(
                            g.get("score")
                        ),
                    )
                )

                insertados += 1

            conn.commit()

        except Exception as e:

            print(
                f"\n❌ Error actualizando BD: {e}"
            )

            print(
                "↩️ Haciendo ROLLBACK..."
            )

            try:
                conn.rollback()
            except Exception:
                pass

            print(
                "🛡️ La BD no se confirmó."
            )

            return

        # ----------------------------------------------------
        # RESULTADO FINAL
        # ----------------------------------------------------

        total = conn.execute(
            "SELECT COUNT(*) FROM juegos"
        ).fetchone()[0]

        cur_final = conn.execute(
            """
            SELECT COUNT(*)
            FROM juegos
            WHERE fuente='curado'
            """
        ).fetchone()[0]

        distribuidores = (
            total - cur_final
        )

        print(
            "\n🎉 ÉXITO:"
        )

        print(
            f"   • Total en BD: {total} juegos"
        )

        print(
            f"   • Curados: {cur_final}"
        )

        print(
            f"   • Distribuidores: {distribuidores}"
        )

        print(
            "\n📊 Fuentes insertadas:"
        )

        for dist, count in dist_count.items():
            print(
                f"   • {dist}: {count}"
            )

        print(
            f"\n🛡️ Backup disponible: {bk}"
        )

        print(
            "\n⚠️ IMPORTANTE:"
        )

        print(
            "   Si la API key de itch.io que "
            "aparecía en el código anterior "
            "era real, revócala y genera otra."
        )

    finally:

        conn.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()