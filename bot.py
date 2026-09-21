import asyncio
import random
import subprocess

ANUNCIO_URLS = ["http://www.tusitio.com/anuncio1", "http://www.tusitio.com/anuncio2"]
PROXIES = [
    "http://proxy1.example.com:8080",
    "http://proxy2.example.com:8080",
    "http://proxy3.example.com:8080",
    # Agrega más proxies aquí
]

async def visit_url(url, proxy=None):
    command = ["node", "script.js", url, proxy]
    process = await asyncio.create_subprocess_exec(*command)
    await process.wait()

async def main(num_visits):
    tasks = []
    for _ in range(num_visits):
        url = random.choice(ANUNCIO_URLS)
        proxy = random.choice(PROXIES) if PROXIES else None
        tasks.append(visit_url(url, proxy))
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    NUM_VISITS = 10  # Cambia este valor según sea necesario
    asyncio.run(main(NUM_VISITS))
