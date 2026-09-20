import sqlite3
import os
import shutil
import time
import json
import re
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    requests = None

DB = "juegos.db"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

# ============================================================
# JUEGOS INDIVIDUALES CURADOS
# ============================================================
#
# Se guardan con:
#   fuente='curado'
#   distribuidor='manual'
#
# Así NO serán borrados por actualizar_juegos.py, que conserva
# los registros cuya fuente sea 'curado'.
#
# El script valida antes de insertar:
#   - HTTP 200
#   - X-Frame-Options
#   - CSP frame-ancestors
#   - respuestas de error comunes
#
# IMPORTANTE:
# Ninguna comprobación HTTP puede garantizar al 100% que una
# página funcionará dentro de iframe si usa bloqueo por JavaScript.
# Por eso este script también marca posibles frame-busters.
# ============================================================

JUEGOS = [
    {
        "id": "manual_2048",
        "titulo": "2048",
        "descripcion": "Clásico rompecabezas de combinar fichas hasta llegar a 2048.",
        "categoria": "puzzle",
        "url": "https://all2048.github.io/2048/",
        "score": 100.0,
    },
    {
        "id": "manual_breakout",
        "titulo": "Breakout",
        "descripcion": "Clásico arcade de romper bloques con una pelota y una plataforma.",
        "categoria": "arcade",
        "url": "https://cakebatterandsprinkles.github.io/breakout/",
        "score": 99.0,
    },
    {
        "id": "manual_snake",
        "titulo": "Snake",
        "descripcion": "Versión HTML5 del clásico Snake jugable directamente en el navegador.",
        "categoria": "arcade",
        "url": "https://parkminkyu.github.io/snake/",
        "score": 98.0,
    },
    {
        "id": "manual_pacman",
        "titulo": "Pac-Man",
        "descripcion": "Versión HTML5 del clásico Pac-Man para navegador.",
        "categoria": "arcade",
        "url": "https://harto.github.io/pacman/",
        "score": 97.0,
    },
    {
        "id": "manual_astray",
        "titulo": "Astray",
        "descripcion": "Juego de laberinto WebGL construido con Three.js y Box2dWeb.",
        "categoria": "aventuras",
        "url": "https://wwwtyro.github.io/Astray/",
        "score": 96.0,
    },
    {
        "id": "manual_reverse_snake",
        "titulo": "Reversed Snake",
        "descripcion": "Una variante de Snake donde juegas como la manzana y debes escapar.",
        "categoria": "arcade",
        "url": "https://imbios.github.io/lab-snake-reverse/",
        "score": 95.0,
    },
]


def normalizar(v):
    return str(v or "").strip()


def frame_ancestors_bloquea(csp):
    """
    Devuelve True cuando frame-ancestors bloquea claramente el uso
    en un dominio externo.
    """
    csp = normalizar(csp).lower()

    if not csp:
        return False

    match = re.search(r"(?:^|;)\s*frame-ancestors\s+([^;]+)", csp)

    if not match:
        return False

    rule = match.group(1).strip()

    if "'none'" in rule:
        return True

    # Si solo permite self, no puede embeberse desde Obito Games.
    tokens = rule.split()

    externos = [
        t for t in tokens
        if t not in ("'self'", "self")
    ]

    if not externos:
        return True

    # '*' permite cualquier origen.
    if "*" in externos:
        return False

    # Si hay orígenes explícitos pero no conocemos todavía el dominio
    # final de Obito Games, lo tratamos como bloqueado para ser estrictos.
    return True


def detectar_frame_buster(html_text):
    """
    Detección aproximada de JavaScript que intenta salir del iframe.
    No elimina el juego automáticamente, solo genera advertencia.
    """
    texto = (html_text or "").lower()

    patrones = (
        "top.location",
        "window.top.location",
        "top.location.href",
        "window.top !== window.self",
        "window.top != window.self",
        "self !== top",
        "self != top",
    )

    return any(p in texto for p in patrones)


def extraer_imagen(html_text, base_url):
    patrones = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ]

    for patron in patrones:
        m = re.search(patron, html_text or "", flags=re.I)
        if m:
            return urljoin(base_url, m.group(1).strip())

    return ""


def validar_juego(url):
    if not requests:
        return {
            "ok": False,
            "motivo": "Falta requests. Ejecuta: pip install requests",
        }

    try:
        r = requests.get(
            url,
            headers=UA,
            timeout=20,
            allow_redirects=True,
        )
    except Exception as e:
        return {
            "ok": False,
            "motivo": f"Error HTTP: {e}",
        }

    final_url = normalizar(r.url)

    if r.status_code != 200:
        return {
            "ok": False,
            "motivo": f"HTTP {r.status_code}",
            "final_url": final_url,
        }

    xfo = normalizar(r.headers.get("X-Frame-Options")).lower()
    csp = normalizar(r.headers.get("Content-Security-Policy"))

    if xfo:
        # DENY bloquea siempre.
        # SAMEORIGIN bloquea porque Obito Games está en otro origen.
        if "deny" in xfo or "sameorigin" in xfo:
            return {
                "ok": False,
                "motivo": f"X-Frame-Options={xfo}",
                "final_url": final_url,
            }

    if frame_ancestors_bloquea(csp):
        return {
            "ok": False,
            "motivo": "CSP frame-ancestors bloquea iframe externo",
            "final_url": final_url,
        }

    content_type = normalizar(r.headers.get("Content-Type")).lower()

    texto = r.text if "text" in content_type or "html" in content_type else ""

    texto_bajo = texto.lower()

    errores = (
        "game not found",
        "juego no encontrado",
        "please upload your game",
        "404 not found",
        "<title>404",
        "page not found",
    )

    if any(e in texto_bajo for e in errores):
        return {
            "ok": False,
            "motivo": "La página parece devolver un juego/página inexistente",
            "final_url": final_url,
        }

    return {
        "ok": True,
        "motivo": "OK",
        "final_url": final_url or url,
        "imagen": extraer_imagen(texto, final_url or url),
        "frame_buster": detectar_frame_buster(texto),
    }


def asegurar_columnas(conn):
    cols = {
        r[1]
        for r in conn.execute("PRAGMA table_info(juegos)").fetchall()
    }

    extras = (
        ("distribuidor", "TEXT"),
        ("tag", "TEXT"),
        ("fuente", "TEXT"),
        ("sources", "TEXT"),
        ("orientacion", "TEXT"),
        ("score", "REAL"),
    )

    for nombre, tipo in extras:
        if nombre not in cols:
            conn.execute(
                f"ALTER TABLE juegos ADD COLUMN {nombre} {tipo}"
            )

    conn.commit()


def main():
    if not os.path.exists(DB):
        print(f"❌ No existe {DB}")
        return

    if not requests:
        print("❌ Falta requests.")
        print("   Ejecuta: pip install requests")
        return

    backup = f"{DB}.backup_manual_{int(time.time())}"
    shutil.copy2(DB, backup)

    print(f"🛡️ Backup creado: {backup}")
    print()
    print("🎮 Validando juegos individuales...")
    print()

    conn = sqlite3.connect(DB)

    try:
        asegurar_columnas(conn)

        insertados = 0
        actualizados = 0
        omitidos = 0

        for i, game in enumerate(JUEGOS, 1):
            titulo = game["titulo"]
            url = game["url"]

            print(f"[{i}/{len(JUEGOS)}] {titulo}")
            print(f"   URL: {url}")

            resultado = validar_juego(url)

            if not resultado.get("ok"):
                print(f"   ❌ OMITIDO: {resultado.get('motivo')}")
                omitidos += 1
                print()
                continue

            final_url = resultado.get("final_url") or url
            imagen = resultado.get("imagen") or ""

            if resultado.get("frame_buster"):
                print("   ⚠️ Posible script anti-iframe detectado.")
                print("      Se insertará, pero conviene probarlo en el navegador.")

            existente = conn.execute(
                """
                SELECT id
                FROM juegos
                WHERE id = ?
                   OR iframe_url = ?
                LIMIT 1
                """,
                (
                    game["id"],
                    final_url,
                ),
            ).fetchone()

            sources = json.dumps(
                [final_url],
                ensure_ascii=False,
            )

            if existente:
                conn.execute(
                    """
                    UPDATE juegos
                    SET titulo = ?,
                        descripcion = ?,
                        categoria = ?,
                        imagen_url = CASE
                            WHEN ? != '' THEN ?
                            ELSE imagen_url
                        END,
                        iframe_url = ?,
                        distribuidor = 'manual',
                        fuente = 'curado',
                        tag = 'individual',
                        sources = ?,
                        score = ?
                    WHERE id = ?
                    """,
                    (
                        game["titulo"],
                        game["descripcion"],
                        game["categoria"],
                        imagen,
                        imagen,
                        final_url,
                        sources,
                        float(game.get("score", 100.0)),
                        existente[0],
                    ),
                )

                actualizados += 1
                print("   🔄 Actualizado en juegos.db")

            else:
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
                        tag,
                        sources,
                        score
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game["id"],
                        game["titulo"],
                        game["descripcion"],
                        game["categoria"],
                        imagen,
                        final_url,
                        "manual",
                        "curado",
                        "individual",
                        sources,
                        float(game.get("score", 100.0)),
                    ),
                )

                insertados += 1
                print("   ✅ Insertado en juegos.db")

            print(f"   Embed final: {final_url}")

            if imagen:
                print(f"   Imagen: {imagen[:120]}")

            print()

        conn.commit()

        total_manual = conn.execute(
            """
            SELECT COUNT(*)
            FROM juegos
            WHERE fuente='curado'
              AND distribuidor='manual'
            """
        ).fetchone()[0]

        print("=" * 60)
        print("✅ TERMINADO")
        print(f"   Nuevos:       {insertados}")
        print(f"   Actualizados: {actualizados}")
        print(f"   Omitidos:     {omitidos}")
        print(f"   Manuales en BD: {total_manual}")
        print(f"   Backup: {backup}")
        print()
        print("ℹ️ Se guardan como fuente='curado' para que")
        print("   actualizar_juegos.py NO los borre.")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        print(f"🛡️ Puedes restaurar: {backup}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
