# -*- coding: utf-8 -*-
"""逐城抓 OSM 兴趣点，只保留检索要用的 8 类标签。

相比上一版：
1. `out tags` 而不是 `out tags center`：不要坐标，省掉服务端拼几何、算中心点的开销；
2. 落盘前裁剪：只留白名单键，实测能砍掉约 80% 的字节（威尼斯 1204KB → 212KB）；
3. 不写 version/generator/osm3s 这些应答元信息；
4. 多镜像 + 冷却重试：连不上就冷一会儿再试，不会因为一次失败就整个退出；
5. 空结果一律当失败，绝不写空文件。

用法：python3 fetch_pois.py [城市数上限]
输出：data/pois/<geonameid>.json、data/crawl_log.jsonl
"""
import collections
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# 按可靠性排序
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]
UA = "CISC3014-DestiMatch/1.0 (course project)"
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT_DIR = os.path.join(BASE, "data", "pois")
LOG_PATH = os.path.join(BASE, "data", "crawl_log.jsonl")
CSV_PATH = os.path.join(ROOT, "01_城市清单", "cities_1000.csv")

SLEEP = 2.0            # 每次请求之间歇一下
MAX_RETRY = 2          # 同一个 endpoint 内的重试次数
TIMEOUT = 120          # 单次请求超时秒数
COOLDOWN_CONN = 90     # 连不上：冷 90 秒再来
COOLDOWN_BAD = 240     # 连续 3 次 5xx/空结果：冷 4 分钟
BAD_STRIKES = 3
PATIENCE = 1800        # 连续 30 分钟一个都没抓到就停，避免无限空转

# 落盘时保留的标签键；其余（name/addr:*/website/phone/opening_hours/panoramax…）一律丢弃
KEEP = ("tourism", "historic", "amenity", "natural", "leisure", "shop", "sport", "aerialway")

# 只抓这几类标签，避免把银行、停车场也抓回来
QUERY = """[out:json][timeout:180];
(
  nwr["tourism"](around:{r},{lat},{lon});
  nwr["historic"](around:{r},{lat},{lon});
  nwr["aerialway"](around:{r},{lat},{lon});
  nwr["leisure"~"^(park|garden|nature_reserve|stadium|marina|water_park|golf_course|spa|sauna)$"](around:{r},{lat},{lon});
  nwr["amenity"~"^(restaurant|cafe|bar|pub|nightclub|theatre|cinema|marketplace|arts_centre|casino|spa|place_of_worship)$"](around:{r},{lat},{lon});
  nwr["natural"~"^(beach|peak|waterfall|bay|hot_spring|cave_entrance|glacier)$"](around:{r},{lat},{lon});
  nwr["shop"~"^(gift|souvenir|mall|department_store|art|books|bakery|clothes|jewellery)$"](around:{r},{lat},{lon});
  nwr["sport"~"^(skiing|diving|surfing|golf|climbing|hiking|cycling)$"](around:{r},{lat},{lon});
);
out tags;"""


def log(rec):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def ep_name(url):
    return url.split("//")[1].split("/")[0]


def trim(raw):
    """只留白名单标签。返回 (精简后的记录, 原始元素数)。"""
    elements = raw.get("elements") or []
    kept = []
    for e in elements:
        tags = e.get("tags") or {}
        t = {k: v for k, v in tags.items() if k in KEEP}
        if t:
            kept.append({"id": e.get("id"), "tags": t})
    return {"elements": kept}, len(elements)


def probe(timeout=10):
    """开跑前看一眼谁活着，把活的排到前面（不排除任何人，镜像会抖）。"""
    alive = []
    for ep in ENDPOINTS:
        try:
            req = urllib.request.Request(ep.replace("/interpreter", "/status"),
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read(256)
            alive.append(ep)
        except urllib.error.HTTPError:
            alive.append(ep)      # 能连上就算活，只是 /status 路径不同
        except Exception:
            print(f"  镜像暂时不通 {ep_name(ep)}", flush=True)
    order = alive + [ep for ep in ENDPOINTS if ep not in alive]
    return order, alive


def cool(st, ep, seconds):
    st["until"][ep] = time.time() + seconds


def ready(st):
    now = time.time()
    return [ep for ep in st["order"] if st["until"].get(ep, 0) <= now]


def wait_ready(st, cap=120):
    """没有可用镜像时等到最早解冻的那个，最多等 cap 秒。"""
    now = time.time()
    nxt = min(st["until"].get(ep, 0) for ep in st["order"])
    time.sleep(max(1, min(nxt - now, cap)))


def fetch(city, st):
    """依次尝试可用镜像。成功返回 (json, endpoint, 秒, 字节)，全失败返回 (None, 原因, 0, 0)。"""
    q = QUERY.format(r=int(float(city["radius_km"]) * 1000),
                     lat=city["lat"], lon=city["lon"])
    body = urllib.parse.urlencode({"data": q}).encode()
    last = "没有可用镜像"

    for ep in ready(st):
        for attempt in range(MAX_RETRY):
            t0 = time.time()
            try:
                req = urllib.request.Request(ep, data=body, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    raw = resp.read()
                data = json.loads(raw)
                if not (data.get("elements") or []):
                    # 镜像活着但库里没数据，会返回空数组；当失败处理，绝不写空文件
                    last = f"{ep_name(ep)}: 返回 0 条"
                    st["bad"][ep] += 1
                    if st["bad"][ep] >= BAD_STRIKES:
                        st["bad"][ep] = 0
                        cool(st, ep, COOLDOWN_BAD)
                        print(f"    冷处理 {ep_name(ep)}：{last}", flush=True)
                    break
                st["bad"][ep] = 0
                return data, ep, round(time.time() - t0, 1), len(raw)
            except urllib.error.HTTPError as e:
                last = f"{ep_name(ep)}: HTTP {e.code}"
                if e.code == 429 or e.code >= 500:
                    st["bad"][ep] += 1
                    if st["bad"][ep] >= BAD_STRIKES:
                        st["bad"][ep] = 0
                        cool(st, ep, COOLDOWN_BAD)
                        print(f"    冷处理 {ep_name(ep)}：HTTP {e.code}", flush=True)
                        break
                    time.sleep(2 ** attempt * 3)
                    continue
                break
            except Exception as e:
                last = f"{ep_name(ep)}: {type(e).__name__}"
                cool(st, ep, COOLDOWN_CONN)
                break

    return None, last, 0, 0


def need_fetch(city):
    """返回 None 表示已抓到，否则返回需要重抓的原因。"""
    path = f"{OUT_DIR}/{city['geonameid']}.json"
    if not os.path.exists(path):
        return "缺"
    try:
        with open(path, encoding="utf-8") as f:
            if json.load(f).get("elements"):
                return None
        return "空文件"
    except Exception:
        return "损坏"


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    with open(CSV_PATH, encoding="utf-8") as f:
        cities = list(csv.DictReader(f))
    if limit:
        cities = cities[:limit]

    os.makedirs(OUT_DIR, exist_ok=True)

    by_id = {c["geonameid"]: c for c in cities}
    pending = [c["geonameid"] for c in cities if need_fetch(c)]
    print(f"清单 {len(cities)} 座，待抓 {len(pending)} 座", flush=True)

    order, alive = probe()
    # 探活失败的直接进冷却，避免循环里 1 秒空转
    st = {"order": order, "bad": collections.Counter(),
          "until": {ep: time.time() + COOLDOWN_CONN for ep in ENDPOINTS if ep not in alive}}
    if not alive:
        print("现在没有镜像能连上。会继续重试，最多等 30 分钟。", flush=True)

    ok = fail = 0
    saved_bytes = raw_bytes = 0
    queue = collections.deque(pending)
    tries = collections.Counter()
    last_ok = time.time()
    i = 0

    while queue:
        if time.time() - last_ok > PATIENCE:
            print(f"\n已经 {PATIENCE // 60} 分钟没抓到任何东西，先停下。"
                  f"剩下的 {len(queue)} 座下次接着跑（已抓的会跳过）。", flush=True)
            break

        if not ready(st):
            print("  所有镜像都在冷却，等一会儿 ...", flush=True)
            wait_ready(st)
            continue

        cid = queue.popleft()
        city = by_id[cid]
        i += 1
        print(f"[{i}] {city['name']} ({city['country']}) r={city['radius_km']}km", end=" ... ", flush=True)

        data, why, sec, nbytes = fetch(city, st)
        if data is None:
            fail += 1
            print(f"失败（{why}）", flush=True)
            log({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "city": city["name"],
                 "id": city["geonameid"], "status": 0, "error": why})
            # 放回队尾；同一座城最多试 3 次就留给下一轮运行
            tries[cid] += 1
            if tries[cid] < 3:
                queue.append(cid)
            else:
                print(f"    {city['name']} 放弃（留给下次运行）", flush=True)
        else:
            rec, n_raw = trim(data)
            if not rec["elements"]:
                print("空结果，丢弃", flush=True)
                log({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "city": city["name"],
                     "id": city["geonameid"], "status": 0, "error": "空结果"})
                tries[cid] += 1
                if tries[cid] < 3:
                    queue.append(cid)
                continue

            path = f"{OUT_DIR}/{city['geonameid']}.json"
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)

            size = os.path.getsize(path)
            ok += 1
            last_ok = time.time()
            raw_bytes += nbytes
            saved_bytes += size
            print(f"{len(rec['elements'])} 个 POI（{n_raw} 条原始记录），"
                  f"{nbytes / 1024:.0f}KB → {size / 1024:.0f}KB，{sec}s，{ep_name(why)}", flush=True)
            log({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "city": city["name"],
                 "id": city["geonameid"], "status": 200, "endpoint": ep_name(why),
                 "bytes": nbytes, "saved": size, "pois": len(rec["elements"]),
                 "sec": sec})

        time.sleep(SLEEP)

    left = sum(1 for c in cities if need_fetch(c) is not None)
    print(f"\n本次成功 {ok}，失败 {fail}，还差 {left} 座。", flush=True)
    if raw_bytes:
        print(f"下载 {raw_bytes / 2**20:.0f} MB，落盘 {saved_bytes / 2**20:.0f} MB"
              f"（省了 {100 * (1 - saved_bytes / raw_bytes):.0f}%）", flush=True)

    idx = os.path.join(BASE, "make_index.py")
    if os.path.exists(idx) and ok:
        print("正在更新 index.json ...", flush=True)
        os.system(f'"{sys.executable}" "{idx}"')


if __name__ == "__main__":
    main()
