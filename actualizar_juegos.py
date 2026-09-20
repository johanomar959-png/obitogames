import sqlite3
import os
import json
import shutil
import time
import random
import re
import html
import xml.etree.ElementTree as ET
from collections import Counter

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
    "Accept": "application/json, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# ============================================================
# BALANCEO DE FUENTES
# ============================================================

# Distribución deseada del TOP.
#
# GameDistribution = 45%
# GameMonetize     = 45%
# itch.io          = 10%
#
# IMPORTANTE:
# Si una fuente tiene menos juegos que su cuota,
# los espacios sobrantes se redistribuyen.
# ============================================================

SOURCE_PERCENTAGES = {
    "gamedistribution": 0.45,
    "gamemonetize": 0.45,
    "itchio": 0.10,
}


# ============================================================
# GAME DISTRIBUTION
# ============================================================

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


# ============================================================
# GAME MONETIZE
# ============================================================

GM_FEED = (
    "https://gamemonetize.com/"
    "feed.php?format=0&num=20000"
)


# ============================================================
# ITCH.IO
# ============================================================

ITCH_FEEDS = [
    "https://itch.io/games/top-rated/html5/platform-web.xml",
    "https://itch.io/games/new-and-popular/html5/platform-web.xml",
    "https://itch.io/games/most-recent/html5/platform-web.xml",
]

ITCH_MAX_PAGES = 5

ITCH_DELAY_MIN = 2.0
ITCH_DELAY_MAX = 4.0

ITCH_RETRIES = 3


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

    value = re.sub(
        r"<script.*?</script>",
        " ",
        value,
        flags=re.I | re.S
    )

    value = re.sub(
        r"<style.*?</style>",
        " ",
        value,
        flags=re.I | re.S
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value
    )

    value = html.unescape(value)

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        return float(
            str(value)
            .replace(",", "")
            .strip()
        )

    except Exception:
        return default


def safe_int(value, default=0):
    try:
        return int(
            float(
                str(value)
                .replace(",", "")
                .strip()
            )
        )
    except Exception:
        return default


def normalize_url(url):
    if not url:
        return ""

    url = html.unescape(
        str(url).strip()
    )

    url = url.replace(
        " ",
        ""
    )

    return url


def get_nested(data, *keys, default=None):
    if not isinstance(data, dict):
        return default

    for key in keys:

        if key in data:
            return data[key]

        wanted = str(key).lower()

        for real_key, value in data.items():

            if str(real_key).lower() == wanted:
                return value

    return default


def cat_slug(raw):
    raw = str(
        raw or ""
    ).strip().lower()

    if not raw:
        return "arcade"

    raw = re.split(
        r"[,|/]",
        raw
    )[0].strip()

    return CAT_MAP.get(
        raw,
        "arcade"
    )


def extract_id_from_url(url):
    if not url:
        return ""

    url = url.rstrip("/")

    last = url.split("/")[-1]

    last = last.split("?")[0]
    last = last.split("#")[0]

    return last


# ============================================================
# HTTP GENERAL
# ============================================================

def request_url(
    url,
    timeout=90,
    retries=2,
    delay=1.0
):
    if not requests:
        return None

    for attempt in range(retries + 1):

        try:

            r = requests.get(
                url,
                headers=UA,
                timeout=timeout
            )

            if r.status_code == 200:

                if not r.content:
                    print(
                        "   ⚠️ Respuesta vacía"
                    )
                    return None

                return r

            if r.status_code == 429:

                retry_after = r.headers.get(
                    "Retry-After"
                )

                if retry_after:
                    try:
                        wait = float(
                            retry_after
                        )
                    except Exception:
                        wait = 5.0
                else:
                    wait = (
                        delay *
                        (attempt + 1)
                    )

                print(
                    f"   ⚠️ HTTP 429 "
                    f"→ esperando {wait:.1f}s..."
                )

                time.sleep(wait)

                continue

            print(
                f"   ⚠️ HTTP {r.status_code}: "
                f"{url[:150]}"
            )

            if attempt < retries:
                time.sleep(
                    delay *
                    (attempt + 1)
                )

        except requests.RequestException as e:

            print(
                f"   ⚠️ Error HTTP: {e}"
            )

            if attempt < retries:
                time.sleep(
                    delay *
                    (attempt + 1)
                )

        except Exception as e:

            print(
                f"   ⚠️ Error: {e}"
            )

            break

    return None


# ============================================================
# GAME DISTRIBUTION
# ============================================================

def parse_gd_items(data):

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

                subvalue = value.get(
                    subkey
                )

                if isinstance(
                    subvalue,
                    list
                ):
                    return subvalue

    return []


def parse_gd_xml(content):

    try:

        root = ET.fromstring(
            content
        )

    except Exception as e:

        print(
            f"   ⚠️ GD XML inválido: {e}"
        )

        return []

    items = (
        root.findall(".//item")
        or root.findall(".//channel/item")
    )

    parsed = []

    for it in items:

        def xtag(tag):

            el = it.find(tag)

            if el is None:
                el = it.find(
                    ".//" + tag
                )

            if (
                el is not None
                and el.text
            ):
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

    return parsed


def cargar_gd():

    if not requests:
        return []

    print(
        "   🔎 GameDistribution "
        "JSON paginado..."
    )

    out = []
    seen = set()

    for page in range(1, 501):

        url = GD_JSON.format(
            page=page
        )

        r = request_url(
            url,
            timeout=90,
            retries=2,
            delay=2
        )

        if not r:
            print(
                f"   ⚠️ GD terminó "
                f"en página {page}"
            )
            break

        items = []

        try:

            data = r.json()

            items = parse_gd_items(
                data
            )

        except Exception:

            print(
                f"   ⚠️ GD página {page}: "
                "JSON inválido, intentando XML..."
            )

            xml_url = GD_XML.format(
                page=page
            )

            rx = request_url(
                xml_url,
                timeout=90,
                retries=1,
                delay=2
            )

            if rx:

                items = parse_gd_xml(
                    rx.content
                )

        if not items:

            print(
                f"   ✓ GD terminó "
                f"en página {page - 1}"
            )

            break

        for it in items:

            if not isinstance(
                it,
                dict
            ):
                continue

            raw_id = (
                get_nested(
                    it,
                    "id"
                )
                or get_nested(
                    it,
                    "game_id"
                )
                or get_nested(
                    it,
                    "AssetId"
                )
                or get_nested(
                    it,
                    "asset_id"
                )
                or ""
            )

            link = normalize_url(
                get_nested(
                    it,
                    "link"
                )
                or get_nested(
                    it,
                    "url"
                )
                or ""
            )

            if not raw_id and link:
                raw_id = extract_id_from_url(
                    link
                )

            raw_id = str(
                raw_id
            ).strip()

            if not raw_id:
                continue

            gid = raw_id

            if gid in seen:
                continue

            seen.add(gid)

            titulo = clean_text(
                get_nested(
                    it,
                    "title"
                )
                or get_nested(
                    it,
                    "name"
                )
                or ""
            )

            desc = clean_text(
                get_nested(
                    it,
                    "description"
                )
                or get_nested(
                    it,
                    "desc"
                )
                or ""
            )[:220]

            category = (
                get_nested(
                    it,
                    "category"
                )
                or get_nested(
                    it,
                    "categories"
                )
                or ""
            )

            cat = cat_slug(
                category
            )

            img = normalize_url(
                get_nested(
                    it,
                    "image"
                )
                or get_nested(
                    it,
                    "image_url"
                )
                or get_nested(
                    it,
                    "thumb"
                )
                or get_nested(
                    it,
                    "thumbnail"
                )
                or ""
            )

            if not img:

                img = (
                    "https://img.gamedistribution.com/"
                    f"{gid}.jpg"
                )

            embed = normalize_url(
                get_nested(
                    it,
                    "embed"
                )
                or get_nested(
                    it,
                    "embed_url"
                )
                or ""
            )

            if not embed:

                embed = (
                    "https://html5.gamedistribution.com/"
                    f"{gid}/"
                )

            out.append({
                "gid": gid,
                "titulo": titulo,
                "desc": desc,
                "cat": cat,
                "img": img,
                "embed": embed,
                "dist": "gamedistribution",

                "raw_views": safe_float(
                    get_nested(
                        it,
                        "views",
                        "plays",
                        "play_count",
                        "playCount"
                    )
                ),

                "raw_downloads": safe_float(
                    get_nested(
                        it,
                        "downloads",
                        "downloads_count"
                    )
                ),

                "raw_rating": safe_float(
                    get_nested(
                        it,
                        "rating",
                        "rate",
                        "stars"
                    )
                ),

                "raw_id": safe_float(
                    raw_id
                ),
            })

        if len(items) < 40:
            break

        time.sleep(
            random.uniform(
                0.10,
                0.30
            )
        )

    print(
        f"   ✓ GameDistribution total: "
        f"{len(out)} juegos"
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
            timeout=120,
            retries=3,
            delay=2
        )

        if not r:
            return []

        try:
            data = r.json()
        except Exception:
            data = json.loads(
                r.text
            )

    except Exception as e:

        print(
            f"   ⚠️ Error GM: {e}"
        )

        return []

    if isinstance(
        data,
        list
    ):
        items = data

    elif isinstance(
        data,
        dict
    ):

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
    sin_url_real = 0

    for it in items:

        if not isinstance(
            it,
            dict
        ):
            continue

        raw = (
            get_nested(
                it,
                "id"
            )
            or get_nested(
                it,
                "game_id"
            )
            or get_nested(
                it,
                "gameId"
            )
            or ""
        )

        raw = str(
            raw
        ).strip()

        if not raw:
            continue

        gid = f"gm_{raw}"

        if gid in seen:
            continue

        seen.add(gid)

        titulo = clean_text(
            get_nested(
                it,
                "title"
            )
            or get_nested(
                it,
                "name"
            )
            or ""
        )

        desc = clean_text(
            get_nested(
                it,
                "description"
            )
            or get_nested(
                it,
                "desc"
            )
            or ""
        )[:220]

        category = (
            get_nested(
                it,
                "category"
            )
            or get_nested(
                it,
                "categories"
            )
            or ""
        )

        cat = cat_slug(
            category
        )

        img = normalize_url(
            get_nested(
                it,
                "thumb"
            )
            or get_nested(
                it,
                "thumbnail"
            )
            or get_nested(
                it,
                "image"
            )
            or get_nested(
                it,
                "image_url"
            )
            or ""
        )

        if not img:

            img = (
                "https://img.gamemonetize.com/"
                f"{raw}/512x384.jpg"
            )

        # GameMonetize entrega la URL REAL del juego en el feed.
        # IMPORTANTE: el campo numérico `id` del catálogo NO es el hash
        # del reproductor HTML5, por lo que nunca debemos fabricar
        # https://html5.gamemonetize.co/<id>/.
        embed = normalize_url(
            get_nested(
                it,
                "embed"
            )
            or get_nested(
                it,
                "embed_url"
            )
            or get_nested(
                it,
                "url"
            )
            or get_nested(
                it,
                "game_url"
            )
            or get_nested(
                it,
                "gameUrl"
            )
            or ""
        )

        # Sin una URL real proporcionada por GameMonetize no insertamos
        # el juego. Esto evita llenar la BD con enlaces inventados que
        # muestran "Game not found".
        if not embed or not embed.startswith(("http://", "https://")):
            sin_url_real += 1
            continue

        out.append({
            "gid": gid,
            "titulo": titulo,
            "desc": desc,
            "cat": cat,
            "img": img,
            "embed": embed,
            "dist": "gamemonetize",

            "raw_views": safe_float(
                get_nested(
                    it,
                    "views",
                    "plays",
                    "play_count",
                    "playCount"
                )
            ),

            "raw_downloads": safe_float(
                get_nested(
                    it,
                    "downloads",
                    "downloads_count"
                )
            ),

            "raw_rating": safe_float(
                get_nested(
                    it,
                    "rating",
                    "rate",
                    "stars"
                )
            ),

            "raw_id": safe_float(
                raw
            ),
        })

    print(
        f"   ✓ GameMonetize válidos: {len(out)} juegos"
    )

    if sin_url_real:
        print(
            f"   ⚠️ GameMonetize descartados sin URL real: {sin_url_real}"
        )

    return out


# ============================================================
# ITCH.IO RSS
# ============================================================

def parse_itch_rss(
    content
):

    try:

        root = ET.fromstring(
            content
        )

    except Exception as e:

        print(
            f"   ⚠️ itch RSS inválido: {e}"
        )

        return []

    items = root.findall(
        ".//item"
    )

    out = []

    for item in items:

        def get_text(tag):

            el = item.find(
                tag
            )

            if (
                el is not None
                and el.text
            ):
                return clean_text(
                    el.text
                )

            for child in item:

                if child.tag.lower().endswith(
                    "}" + tag.lower()
                ):

                    if child.text:
                        return clean_text(
                            child.text
                        )

            return ""

        title = get_text(
            "title"
        )

        description = get_text(
            "description"
        )

        link = get_text(
            "link"
        )

        if not link:
            continue

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
                    child.attrib.get(
                        "url"
                    )
                    or child.attrib.get(
                        "href"
                    )
                    or child.text
                    or ""
                )

                if image:
                    break

        gid_raw = extract_id_from_url(
            link
        )

        if not gid_raw:
            continue

        gid = f"itch_{gid_raw}"

        out.append({
            "gid": gid,
            "titulo": title,
            "desc": description[:220],
            "cat": "arcade",
            "img": normalize_url(
                image
            ),
            "embed": normalize_url(
                link
            ),
            "dist": "itchio",

            "raw_views": 0,
            "raw_downloads": 0,
            "raw_rating": 0,

            "raw_id": 0,
        })

    return out


def cargar_itch():

    if not requests:
        return []

    print(
        "   🔎 itch.io mediante RSS público..."
    )

    out = []
    seen = set()

    for feed_index, feed_base in enumerate(
        ITCH_FEEDS
    ):

        print(
            f"   • Feed {feed_index + 1}/"
            f"{len(ITCH_FEEDS)}"
        )

        for page in range(
            1,
            ITCH_MAX_PAGES + 1
        ):

            if page == 1:
                url = feed_base
            else:
                separator = (
                    "&"
                    if "?" in feed_base
                    else "?"
                )

                url = (
                    f"{feed_base}"
                    f"{separator}page={page}"
                )

            if page > 1:

                delay = random.uniform(
                    ITCH_DELAY_MIN,
                    ITCH_DELAY_MAX
                )

                time.sleep(
                    delay
                )

            r = None

            for attempt in range(
                ITCH_RETRIES + 1
            ):

                try:

                    r = requests.get(
                        url,
                        headers=UA,
                        timeout=60
                    )

                except requests.RequestException as e:

                    print(
                        f"   ⚠️ itch error: {e}"
                    )

                    time.sleep(
                        3 + attempt * 2
                    )

                    continue

                if r.status_code == 200:
                    break

                if r.status_code == 429:

                    retry_after = (
                        r.headers.get(
                            "Retry-After"
                        )
                    )

                    if retry_after:

                        try:
                            wait = float(
                                retry_after
                            )
                        except Exception:
                            wait = 10

                    else:

                        wait = (
                            8
                            + attempt * 8
                        )

                    print(
                        f"   ⚠️ itch HTTP 429 "
                        f"→ esperando "
                        f"{wait:.1f}s "
                        f"(intento "
                        f"{attempt + 1}/"
                        f"{ITCH_RETRIES + 1})"
                    )

                    time.sleep(
                        wait
                    )

                    continue

                print(
                    f"   ⚠️ itch HTTP "
                    f"{r.status_code}"
                )

                break

            if not r:
                break

            if r.status_code != 200:
                break

            games = parse_itch_rss(
                r.content
            )

            if not games:
                break

            for game in games:

                gid = game["gid"]

                if gid in seen:
                    continue

                seen.add(gid)

                out.append(
                    game
                )

            if len(games) < 10:
                break

        if feed_index < len(
            ITCH_FEEDS
        ) - 1:

            time.sleep(
                random.uniform(
                    4,
                    7
                )
            )

    print(
        f"   ✓ itch.io total: "
        f"{len(out)} juegos"
    )

    return out


# ============================================================
# NORMALIZACIÓN DEL SCORE
# ============================================================

def normalize_values(
    games,
    field
):

    values = []

    for game in games:

        value = safe_float(
            game.get(field)
        )

        if value > 0:
            values.append(
                value
            )

    if not values:
        for game in games:
            game[
                f"_norm_{field}"
            ] = 0.0
        return

    values_sorted = sorted(
        values
    )

    low_index = int(
        len(values_sorted) * 0.05
    )

    high_index = int(
        len(values_sorted) * 0.95
    )

    low = values_sorted[
        min(
            low_index,
            len(values_sorted) - 1
        )
    ]

    high = values_sorted[
        min(
            high_index,
            len(values_sorted) - 1
        )
    ]

    if high <= low:
        high = max(
            low + 1,
            max(values_sorted)
        )

    import math

    log_low = math.log1p(
        max(
            0,
            low
        )
    )

    log_high = math.log1p(
        max(
            0,
            high
        )
    )

    denominator = (
        log_high - log_low
    )

    for game in games:

        value = safe_float(
            game.get(field)
        )

        if value <= 0:

            game[
                f"_norm_{field}"
            ] = 0.0

            continue

        value = max(
            low,
            min(
                value,
                high
            )
        )

        log_value = math.log1p(
            value
        )

        if denominator <= 0:

            normalized = 0.5

        else:

            normalized = (
                log_value
                - log_low
            ) / denominator

        game[
            f"_norm_{field}"
        ] = max(
            0.0,
            min(
                1.0,
                normalized
            )
        )


def calcular_score_global(
    games
):

    if not games:
        return

    normalize_values(
        games,
        "raw_views"
    )

    normalize_values(
        games,
        "raw_downloads"
    )

    normalize_values(
        games,
        "raw_rating"
    )

    normalize_values(
        games,
        "raw_id"
    )

    for game in games:

        views = game.get(
            "_norm_raw_views",
            0.0
        )

        downloads = game.get(
            "_norm_raw_downloads",
            0.0
        )

        rating = game.get(
            "_norm_raw_rating",
            0.0
        )

        recency = game.get(
            "_norm_raw_id",
            0.0
        )

        popularity = (
            views * 0.65
            + downloads * 0.35
        )

        metadata = 0.0

        if game.get(
            "titulo"
        ):
            metadata += 0.30

        if game.get(
            "desc"
        ):
            metadata += 0.20

        if game.get(
            "img"
        ):
            metadata += 0.20

        if game.get(
            "embed"
        ):
            metadata += 0.30

        score = (
            popularity * 45.0
            + rating * 25.0
            + recency * 20.0
            + metadata * 10.0
        )

        dist = game.get(
            "dist"
        )

        if dist == "gamedistribution":
            score += 1.5

        elif dist == "itchio":
            score += 1.0

        game[
            "score"
        ] = score


# ============================================================
# DEDUPLICACIÓN
# ============================================================

def deduplicar_juegos(
    juegos
):

    resultado = []

    seen_ids = set()
    seen_urls = set()

    for game in juegos:

        gid = str(
            game.get(
                "gid"
            )
            or ""
        ).strip()

        embed = normalize_url(
            game.get(
                "embed"
            )
            or ""
        )

        if not gid:
            continue

        if gid in seen_ids:
            continue

        if (
            embed
            and embed in seen_urls
        ):
            continue

        seen_ids.add(
            gid
        )

        if embed:
            seen_urls.add(
                embed
            )

        resultado.append(
            game
        )

    return resultado


# ============================================================
# SELECCIÓN BALANCEADA DEL TOP
# ============================================================

def seleccionar_top_balanceado(
    juegos,
    total
):
    """
    Selecciona el TOP garantizando representación
    de las fuentes.

    Cuotas iniciales:

        GD  = 45%
        GM  = 45%
        itch = 10%

    Si una fuente no tiene suficientes juegos,
    los espacios sobrantes se redistribuyen.

    Dentro de cada fuente se utilizan los mejores
    juegos según el score calculado.
    """

    if not juegos:
        return []

    # --------------------------------------------------------
    # Agrupar
    # --------------------------------------------------------

    grupos = {
        "gamedistribution": [],
        "gamemonetize": [],
        "itchio": [],
    }

    otros = []

    for game in juegos:

        dist = str(
            game.get(
                "dist",
                ""
            )
        ).lower().strip()

        if dist in grupos:
            grupos[dist].append(
                game
            )
        else:
            otros.append(
                game
            )

    # --------------------------------------------------------
    # Ordenar cada fuente por score
    # --------------------------------------------------------

    for dist in grupos:

        grupos[dist].sort(
            key=lambda x: (
                safe_float(
                    x.get(
                        "score",
                        0
                    )
                ),
                safe_float(
                    x.get(
                        "raw_views",
                        0
                    )
                ),
                safe_float(
                    x.get(
                        "raw_rating",
                        0
                    )
                ),
            ),
            reverse=True
        )

    otros.sort(
        key=lambda x: safe_float(
            x.get(
                "score",
                0
            )
        ),
        reverse=True
    )

    # --------------------------------------------------------
    # CUOTAS INICIALES
    # --------------------------------------------------------

    cuotas = {}

    for dist, porcentaje in (
        SOURCE_PERCENTAGES.items()
    ):

        cuota = int(
            total * porcentaje
        )

        disponibles = len(
            grupos[dist]
        )

        cuotas[dist] = min(
            cuota,
            disponibles
        )

    # --------------------------------------------------------
    # REDISTRIBUIR ESPACIOS VACÍOS
    # --------------------------------------------------------

    usados = sum(
        cuotas.values()
    )

    faltan = (
        total
        - usados
    )

    while faltan > 0:

        candidatos = []

        for dist in grupos:

            disponibles = len(
                grupos[dist]
            )

            if cuotas[dist] < disponibles:

                siguiente = grupos[
                    dist
                ][
                    cuotas[dist]
                ]

                candidatos.append(
                    (
                        safe_float(
                            siguiente.get(
                                "score",
                                0
                            )
                        ),
                        dist
                    )
                )

        if otros:

            candidatos.append(
                (
                    safe_float(
                        otros[0].get(
                            "score",
                            0
                        )
                    ),
                    "otros"
                )
            )

        if not candidatos:
            break

        # El espacio sobrante se asigna al mejor
        # juego que todavía no ha sido seleccionado.
        candidatos.sort(
            reverse=True
        )

        _, ganador = candidatos[0]

        if ganador == "otros":

            otros.pop(0)

        else:

            cuotas[
                ganador
            ] += 1

        faltan -= 1

    # --------------------------------------------------------
    # SELECCIONAR
    # --------------------------------------------------------

    top = []

    for dist in (
        "gamedistribution",
        "gamemonetize",
        "itchio",
    ):

        cantidad = cuotas[
            dist
        ]

        top.extend(
            grupos[
                dist
            ][
                :cantidad
            ]
        )

    # --------------------------------------------------------
    # Otras fuentes
    # --------------------------------------------------------

    if len(top) < total:

        espacio = (
            total
            - len(top)
        )

        top.extend(
            otros[
                :espacio
            ]
        )

    # --------------------------------------------------------
    # Orden FINAL por score
    #
    # Esto NO elimina la diversidad.
    # Los cupos ya fueron garantizados arriba.
    # --------------------------------------------------------

    top.sort(
        key=lambda x: (
            safe_float(
                x.get(
                    "score",
                    0
                )
            ),
            safe_float(
                x.get(
                    "raw_views",
                    0
                )
            ),
        ),
        reverse=True
    )

    return top[
        :total
    ]


# ============================================================
# LIMPIAR CAMPOS TEMPORALES
# ============================================================

def limpiar_campos_temporales(
    games
):

    for game in games:

        for key in (
            "raw_views",
            "raw_downloads",
            "raw_rating",
            "raw_id",

            "_norm_raw_views",
            "_norm_raw_downloads",
            "_norm_raw_rating",
            "_norm_raw_id",
        ):

            game.pop(
                key,
                None
            )


# ============================================================
# MAIN
# ============================================================

def main():

    if not requests:

        print(
            "❌ Falta requests."
        )

        print(
            "   Ejecuta:"
        )

        print(
            "   pip install requests"
        )

        return

    if not os.path.exists(DB):

        print(
            f"❌ No existe la BD: {DB}"
        )

        return

    # ========================================================
    # BACKUP
    # ========================================================

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

    conn = sqlite3.connect(
        DB
    )

    try:

        # ====================================================
        # COLUMNAS
        # ====================================================

        cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(juegos)"
            )
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
                        f"""
                        ALTER TABLE juegos
                        ADD COLUMN {col} {typ}
                        """
                    )

                except Exception:
                    pass

        conn.commit()

        # ====================================================
        # GAME DISTRIBUTION
        # ====================================================

        print(
            "\n📥 GameDistribution..."
        )

        gd = cargar_gd()

        print(
            f"   → {len(gd)} juegos"
        )

        # ====================================================
        # GAME MONETIZE
        # ====================================================

        print(
            "\n📥 GameMonetize..."
        )

        gm = cargar_gm()

        print(
            f"   → {len(gm)} juegos"
        )

        # ====================================================
        # ITCH
        # ====================================================

        print(
            "\n📥 itch.io..."
        )

        itch = cargar_itch()

        print(
            f"   → {len(itch)} juegos"
        )

        # ====================================================
        # FUENTES
        # ====================================================

        fuentes_ok = sum(
            bool(x)
            for x in (
                gd,
                gm,
                itch
            )
        )

        print(
            f"\n🔎 Fuentes con resultados: "
            f"{fuentes_ok}/3"
        )

        if not gd and not gm and not itch:

            print(
                "\n❌ TODAS LAS FUENTES FALLARON."
            )

            print(
                "🛑 No se modificará la BD."
            )

            print(
                f"🛡️ Backup: {bk}"
            )

            return

        # ====================================================
        # COMBINAR
        # ====================================================

        todos = (
            gd
            + gm
            + itch
        )

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
                "\n❌ No quedaron juegos."
            )

            return

        # ====================================================
        # SCORE
        # ====================================================

        print(
            "\n🧮 Calculando ranking global..."
        )

        calcular_score_global(
            todos
        )

        # ====================================================
        # TOP BALANCEADO
        # ====================================================

        top = seleccionar_top_balanceado(
            todos,
            TOP_TOTAL
        )

        # ====================================================
        # ESTADÍSTICAS
        # ====================================================

        dist_count = Counter(
            game.get(
                "dist"
            )
            for game in top
        )

        print(
            f"\n🏆 TOP {len(top)} seleccionado:"
        )

        print(
            "   ─────────────────────────────"
        )

        for dist, count in (
            dist_count.most_common()
        ):

            percentage = (
                count
                / max(
                    len(top),
                    1
                )
                * 100
            )

            print(
                f"   • {dist}: "
                f"{count} "
                f"({percentage:.1f}%)"
            )

        # ====================================================
        # SEGURIDAD
        # ====================================================

        if len(top) < 100:

            print(
                "\n⚠️ Se obtuvieron "
                f"solamente {len(top)} juegos."
            )

            print(
                "🛑 No se reemplazará la colección."
            )

            print(
                f"🛡️ Backup: {bk}"
            )

            return

        # ====================================================
        # CURADOS
        # ====================================================

        cur = conn.execute(
            """
            SELECT COUNT(*)
            FROM juegos
            WHERE fuente='curado'
            """
        ).fetchone()[0]

        # ====================================================
        # TRANSACCIÓN
        # ====================================================

        try:

            conn.execute(
                "BEGIN"
            )

            # ------------------------------------------------
            # ELIMINAR DISTRIBUIDORES
            # ------------------------------------------------

            print(
                "\n🧹 Limpiando distribuidores "
                "y conservando curados..."
            )

            conn.execute(
                """
                DELETE FROM juegos
                WHERE fuente != 'curado'
                   OR fuente IS NULL
                """
            )

            print(
                f"   ✓ Curados conservados: "
                f"{cur}"
            )

            # ------------------------------------------------
            # INSERTAR TOP
            # ------------------------------------------------

            print(
                f"\n💾 Insertando "
                f"{len(top)} juegos..."
            )

            for game in top:

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
                    VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    )
                    """,
                    (
                        game.get(
                            "gid",
                            ""
                        ),

                        game.get(
                            "titulo",
                            ""
                        ),

                        game.get(
                            "desc",
                            ""
                        ),

                        game.get(
                            "cat",
                            "arcade"
                        ),

                        game.get(
                            "img",
                            ""
                        ),

                        game.get(
                            "embed",
                            ""
                        ),

                        game.get(
                            "dist",
                            ""
                        ),

                        game.get(
                            "dist",
                            ""
                        ),

                        safe_float(
                            game.get(
                                "score",
                                0
                            )
                        ),
                    )
                )

            conn.commit()

        except Exception as e:

            print(
                f"\n❌ Error actualizando BD: "
                f"{e}"
            )

            print(
                "↩️ Ejecutando ROLLBACK..."
            )

            try:
                conn.rollback()
            except Exception:
                pass

            print(
                "🛑 No se confirmó la actualización."
            )

            print(
                f"🛡️ Backup: {bk}"
            )

            return

        # ====================================================
        # RESULTADO
        # ====================================================

        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM juegos
            """
        ).fetchone()[0]

        cur_final = conn.execute(
            """
            SELECT COUNT(*)
            FROM juegos
            WHERE fuente='curado'
            """
        ).fetchone()[0]

        distribuidores = (
            total
            - cur_final
        )

        # ====================================================
        # RESULTADO FINAL
        # ====================================================

        print(
            "\n🎉 ÉXITO:"
        )

        print(
            f"   • Total en BD: "
            f"{total} juegos"
        )

        print(
            f"   • Curados: "
            f"{cur_final}"
        )

        print(
            f"   • Distribuidores: "
            f"{distribuidores}"
        )

        print(
            "\n📊 Fuentes insertadas:"
        )

        for dist, count in (
            dist_count.most_common()
        ):

            print(
                f"   • {dist}: {count}"
            )

        print(
            "\n📈 Distribución del TOP:"
        )

        total_top = max(
            len(top),
            1
        )

        for dist, count in (
            dist_count.most_common()
        ):

            percentage = (
                count
                / total_top
                * 100
            )

            print(
                f"   • {dist}: "
                f"{count} "
                f"({percentage:.1f}%)"
            )

        print(
            "\n⚖️ Balance aplicado:"
        )

        print(
            "   • GameDistribution: 45%"
        )

        print(
            "   • GameMonetize: 45%"
        )

        print(
            "   • itch.io: 10%"
        )

        print(
            "   • Los cupos faltantes se redistribuyen"
        )

        print(
            "   • El score decide los mejores juegos"
            " dentro de cada fuente"
        )

        print(
            f"\n🛡️ Backup disponible: {bk}"
        )

        print(
            "\n⚠️ Si la API key de itch.io "
            "anterior era real y fue expuesta, "
            "revócala."
        )

    finally:

        conn.close()


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":
    main()