# -*- coding: utf-8 -*-
"""把已经抓下来的肥文件就地瘦身：只留 8 个白名单标签。

新抓的城市由 fetch_pois.py 直接写瘦文件，本脚本只处理历史遗留的胖文件。
每个文件裁剪前后逐词项核对计数，不一致就拒绝替换（宁可保留原文件）。

用法：
    python3 trim_pois.py            # 只看能省多少，不改文件
    python3 trim_pois.py --apply    # 真的改
"""
import collections
import glob
import json
import os
import sys

from fetch_pois import KEEP, OUT_DIR

APPLY = "--apply" in sys.argv


def counts(elements):
    c = collections.Counter()
    for e in elements:
        for k, v in (e.get("tags") or {}).items():
            if k in KEEP:
                c[f"{k}={v}"] += 1
    return c


def main():
    files = sorted(glob.glob(os.path.join(OUT_DIR, "*.json")))
    before = after = 0
    done = skipped = 0

    for path in files:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        elements = raw.get("elements") or []
        c_old = counts(elements)

        kept = []
        for e in elements:
            tags = e.get("tags") or {}
            t = {k: v for k, v in tags.items() if k in KEEP}
            if t:
                kept.append({"id": e.get("id"), "tags": t})
        rec = {"elements": kept}

        # 核对：元素数与每个「键=值」的计数都必须完全一致
        if len(kept) != len(elements) or counts(kept) != c_old:
            print(f"跳过 {os.path.basename(path)}：裁剪后对不上")
            skipped += 1
            continue

        old_size = os.path.getsize(path)
        payload = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        new_size = len(payload.encode("utf-8"))
        before += old_size
        after += new_size

        if APPLY:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, path)
        done += 1

    print(f"\n文件 {len(files)} 个：处理 {done}，跳过 {skipped}")
    print(f"{'已改写' if APPLY else '预览'}："
          f"{before / 2**20:.0f} MB → {after / 2**20:.0f} MB"
          f"（省 {100 * (1 - after / before):.0f}%）")
    if not APPLY:
        print("加 --apply 才会真的写盘")


if __name__ == "__main__":
    main()
