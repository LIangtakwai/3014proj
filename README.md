# DestiMatch — 项目目录

按「构建检索系统的顺序」排列，编号即执行顺序。

```
01_城市清单/    选出要研究的城市
02_抓取POI/     每座城市的设施数据
03_表示与矩阵/  标签 → 词项 → 计数矩阵 → TF-IDF
04_检索/        余弦打分、排序、理由
05_增强与多跳/  LLM 查询增强、两跳过滤
06_评测/        三组查询、指标、显著性与失败归因
```

## 当前进度

| 阶段 | 状态 | 产物 |
|---|---|---|
| 01 城市清单 | ✅ 完成 | `cities_1000.csv`（1000 座 / 166 国） |
| 02 抓取 POI | 🔄 885 / 1000 座 | `data/pois/*.json`（已裁到 8 类标签，162 MB / 352 万 POI） |
| 03 表示与矩阵 | ⬜ 待写 | — |
| 04 检索 | ⬜ 待写 | — |
| 05 增强与多跳 | ⬜ 待写 | — |
| 06 评测 | ⬜ 待写 | — |

## 怎么跑

```bash
# 第一步：从 GeoNames 原始文件里挑 1000 座城市
python3 01_城市清单/pick_cities.py

# 第二步：抓 POI（先跑 5 座试水，去掉数字就是全量）
python3 02_抓取POI/fetch_pois.py 5
```

两个脚本都按自身位置定位文件，在哪个目录运行都可以；断了直接重跑，已抓过的会跳过。

## 数据流向

```
cities15000.txt ──pick_cities.py──> cities_1000.csv
cities_1000.csv ──fetch_pois.py──> data/pois/<geonameid>.json
                                   data/crawl_log.jsonl
data/pois/*.json ──make_index.py──> index.json（城市×词项 计数，03 的输入）
data/pois/*.json ──(03 待写)──> data/counts.csv ──> TF-IDF 矩阵
```

## 说明

- `cities_1000.csv` 的 `why` 列：`curated` 是人工挑的旅游城市，`population` 是按人口补足的。
- 想增删城市直接改这个 CSV，再重跑 `fetch_pois.py` 即可。
- 抓取限速 2 秒/次；但真正慢的是服务端：单城应答中位 48 秒、1–20 MB。
- 落盘只留 8 个白名单标签（`tourism/historic/amenity/natural/leisure/shop/sport/aerialway`），
  实测砍掉约 95% 的无用字段（name/addr:*/website/phone/opening_hours…），885 城共 162 MB，
  按此推算 1000 城约 183 MB。历史胖文件用 `python3 02_抓取POI/trim_pois.py --apply` 瘦身。
- `fetch_pois.py` 内置多镜像轮换（overpass-api.de / kumi / mail.ru / osm.ch），
  开跑前先探活；镜像连不上会冷却重试，失败的城市放回队尾，连续 30 分钟一无所获才停（已抓的照样跳过）。
