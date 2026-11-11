# -*- coding: utf-8 -*-
"""扫描 data/pois/*.json，汇总成机器可读的索引：index.json。

抓取可以随时中断、随时重跑本脚本，索引按当前目录内容重建。

用法：python3 make_index.py
输出：02_抓取POI/index.json
"""
import collections
import csv
import glob
import json
import os
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
POI_DIR = os.path.join(BASE, "data", "pois")
OUT = os.path.join(BASE, "index.json")

KEYS = ("tourism", "historic", "amenity", "natural", "leisure", "shop", "sport", "aerialway")

meta = {}
with open(os.path.join(ROOT, "01_城市清单", "cities_1000.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        meta[r["geonameid"]] = (r["name"], r["country"])

cities = {}
for path in sorted(glob.glob(os.path.join(POI_DIR, "*.json"))):
    cid = os.path.basename(path)[:-5]
    name, cc = meta.get(cid, (cid, "?"))
    counts = collections.Counter()
    n = 0
    try:
        with open(path, encoding="utf-8") as f:
            for poi in json.load(f).get("elements", []):
                n += 1
                tags = poi.get("tags", {})
                for k in KEYS:
                    if k in tags:
                        counts[f"{k}={tags[k]}"] += 1
    except Exception as e:
        print(f"读取失败 {path}: {e}")
        continue
    cities[cid] = {
        "name": name,
        "country": cc,
        "pois": n,
        "bytes": os.path.getsize(path),
        "terms": dict(counts.most_common()),
    }

index = {
    "generated": time.strftime("%Y-%m-%d %H:%M"),
    "source": "data/pois/<geonameid>.json",
    "note": "terms 是「词项 → POI 数」，直接就是检索矩阵的一行",
    "cities_total": len(cities),
    "pois_total": sum(c["pois"] for c in cities.values()),
    "terms_total": len({t for c in cities.values() for t in c["terms"]}),
    "keys": list(KEYS),
    "cities": cities,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(index, f, ensure_ascii=False, indent=1)

print(f"{OUT}\n城市 {index['cities_total']} 座，POI {index['pois_total']:,} 个，"
      f"词项 {index['terms_total']} 个，{os.path.getsize(OUT) / 1024:.0f} KB")
