import json, os, requests
UA = {"User-Agent": "Mozilla/5.0"}
r = requests.get("https://gamemonetize.com/feed.php?format=0&num=38000", headers=UA, timeout=60)
data = json.loads(r.text)
items = data if isinstance(data, list) else data.get("games", data.get("items", []))
rank = {}
for i, it in enumerate(items):
    gid = str(it.get("id") or it.get("game_id") or "")
    if gid: rank[gid] = i
with open("gm_ranking.json", "w") as f: json.dump(rank, f)
print(f"✅ Ranking guardado: {len(rank)} juegos")