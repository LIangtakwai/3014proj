# -*- coding: utf-8 -*-
"""从 GeoNames cities15000.txt 里挑 1000 座城市。

规则：
1. 先放一批公认的旅游城市（CURATED），文件里没有的自动跳过；
2. 剩下的名额按「人口 × 行政级别权重」补足；
3. 每个国家最多 20 座，避免被个别大国包场。

用法：python3 pick_cities.py
输出：cities_1000.csv
"""
import collections
import csv
import os
import unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "cities15000.txt")
DST = os.path.join(BASE, "cities_1000.csv")

# ---------------------------------------------------------------- 旅游城市名单
# 逗号分隔（名字里可能有空格，比如 New York City、Chiang Mai）
CURATED = """
Venice, Florence, Rome, Milan, Naples, Verona, Siena, Pisa, Bologna, Turin, Genoa, Palermo, Catania,
Bari, Lecce, Perugia, Trieste,
Barcelona, Madrid, Sevilla, Granada, Valencia|ES, Bilbao, San Sebastian, Toledo|ES, Salamanca|ES,
Santiago de Compostela,
Paris, Nice, Lyon, Marseille, Bordeaux, Strasbourg, Colmar, Annecy, Avignon,
Prague, Vienna, Salzburg, Innsbruck, Graz,
Amsterdam, Rotterdam, Brugge, Brussels, Gent, Antwerp,
Lisbon, Porto, Sintra, Coimbra, Faro,
Athens, Thessaloniki, Mykonos, Chania, Rhodes,
Istanbul, Izmir, Antalya, Bodrum,
Dubrovnik, Split, Zadar, Sarajevo, Mostar, Ljubljana, Zagreb,
Budapest, Krakow, Warsaw, Gdansk, Wroclaw, Poznan,
Berlin, Munich, Hamburg, Heidelberg, Koln, Dresden, Nuremberg,
Zurich, Luzern, Geneva, Bern, Lausanne,
Kyoto, Nara-shi|JP, Kanazawa, Osaka, Tokyo, Sapporo, Fukuoka, Hiroshima, Nagoya, Kobe, Takayama, Matsumoto,
Bangkok, Chiang Mai, Phuket, Krabi, Pattaya, Phra Nakhon Si Ayutthaya,
Hanoi, Ho Chi Minh City, Hoi An, Hue, Da Nang, Haiphong,
Siem Reap, Phnom Penh, Luang Prabang, Vientiane,
Yangon, Mandalay, Denpasar, Ubud, Yogyakarta, Semarang, Surabaya,
Singapore, Hong Kong, Macau, Taipei, Kaohsiung, Tainan, Hualien City,
Seoul, Busan, Incheon, Gyeongju, Jeju City,
Beijing, Shanghai, Xian, Chengdu, Guilin, Lhasa, Lijiang, Hangzhou, Suzhou, Kunming, Guangzhou,
Shenzhen, Xiamen, Qingdao, Harbin, Dalian,
Marrakesh, Fes, Chefchaouen, Casablanca, Rabat, Tangier, Essaouira,
Cairo, Luxor, Aswan, Alexandria,
Cape Town, Johannesburg, Durban, Nairobi, Zanzibar, Arusha,
Wadi Musa, Amman, Dubai, Abu Dhabi, Doha, Muscat,
New York City, Los Angeles, San Francisco, Las Vegas, Miami, New Orleans, Chicago, Boston, Seattle,
Washington, Denver, Nashville, Austin, San Diego, Philadelphia, Phoenix,
Vancouver, Toronto, Montreal, Quebec, Ottawa, Calgary,
Mexico City, Oaxaca, San Miguel de Allende, Cancun, Guadalajara, Merida, Playa del Carmen, Havana,
Cartagena|CO, Medellin, Bogota, Cusco, Lima, Quito, Guayaquil, La Paz|BO, Santiago, Valparaiso,
Buenos Aires, Rio de Janeiro, Salvador, Recife, Manaus, Florianopolis, Sao Paulo, Brasilia,
Sydney, Melbourne, Brisbane, Perth, Cairns, Auckland, Queenstown, Wellington, Christchurch, Honolulu,
Reykjavik, Copenhagen, Stockholm, Oslo, Bergen, Helsinki, Tallinn, Riga, Vilnius, Bucharest, Sofia,
Belgrade, Valletta, Nicosia, Dublin, Edinburgh, Glasgow, Bath, Oxford, Cambridge, York, Belfast,
Liverpool
"""


def norm(s):
    """去掉重音与标点再比对：Zürich→zurich、Xi’an→xian、Köln→koln。"""
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(ch for ch in s if ch.isalnum())


SKIP_CODES = {"PPLX", "PPLQ", "PPLH", "PPLW", "PPLF", "PPLR", "PPLL"}
WEIGHT = {"PPLC": 3.0, "PPLA": 1.5}
COUNTRY_CAP = 20
TARGET = 1000

rows, index = [], {}
with open(SRC, encoding="utf-8") as f:
    for line in f:
        c = line.rstrip("\n").split("\t")
        if len(c) < 19 or c[7] in SKIP_CODES:
            continue
        r = {
            "id": c[0], "name": c[1], "ascii": c[2], "lat": c[4], "lon": c[5],
            "code": c[7], "cc": c[8], "pop": int(c[14]) if c[14].isdigit() else 0,
        }
        r["score"] = max(r["pop"], 1) * WEIGHT.get(r["code"], 1.0)
        rows.append(r)
        index.setdefault(norm(r["ascii"]), []).append(r)
        index.setdefault(norm(r["name"]), []).append(r)

# 1) 旅游城市优先
names = [n.strip() for n in CURATED.replace("\n", " ").split(",") if n.strip()]
picked, seen, missed = [], set(), []
for raw in dict.fromkeys(names):
    name, _, want_cc = raw.partition("|")      # 支持 "Valencia|ES" 限定国家
    cands = index.get(norm(name)) or []
    if want_cc:
        cands = [c for c in cands if c["cc"] == want_cc.strip().upper()]
    if not cands:
        missed.append(raw)
        continue
    best = max(cands, key=lambda r: r["score"])
    if best["id"] not in seen:
        seen.add(best["id"])
        picked.append(dict(best, why="curated"))

# 2) 剩余名额按分数补
per_country = collections.Counter(r["cc"] for r in picked)
for r in sorted(rows, key=lambda r: -r["score"]):
    if len(picked) >= TARGET:
        break
    if r["id"] in seen or per_country[r["cc"]] >= COUNTRY_CAP:
        continue
    picked.append(dict(r, why="population"))
    seen.add(r["id"])
    per_country[r["cc"]] += 1


def radius(p):
    return 10 if p < 1_000_000 else (15 if p < 5_000_000 else 20)


with open(DST, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["rank", "geonameid", "name", "country", "lat", "lon",
                "population", "code", "radius_km", "why"])
    for i, r in enumerate(picked, 1):
        w.writerow([i, r["id"], r["ascii"], r["cc"], r["lat"], r["lon"],
                    r["pop"], r["code"], radius(r["pop"]), r["why"]])

n_cur = sum(1 for r in picked if r["why"] == "curated")
print(f"共选出 {len(picked)} 座（旅游城市 {n_cur} + 人口补足 {len(picked) - n_cur}）")
print(f"覆盖国家 {len(set(r['cc'] for r in picked))} 个")
print("国家 TOP10:", per_country.most_common(10))
if missed:
    print(f"\n名单里有 {len(missed)} 个名字在文件中找不到（小城通常不在 cities15000）：")
    print("  " + ", ".join(missed))
