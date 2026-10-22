#!/usr/bin/env python3
"""Fail unless daw serves the release that was just deployed.

Runs in the cnb `deploy-daw` job after deploy_via_tat.py. That script once ended with exit 0 halfway through the
upload (chunk 240/368): the job showed green and daw kept the old release. So the job's colour comes from what
https://daw.xjjk.com/twin/ says it runs: the web page's `X-Twin-Release` header carries the commit the release
archive was built from (src/twin/web/RELEASE, filled in by `git archive`), and it must be the deployed commit.
"""

from __future__ import annotations

import argparse
import time
import urllib.request

HEADER = "X-Twin-Release"


def served_release(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return response.headers.get(HEADER) or f"没有 {HEADER} 响应头"
    except OSError as error:
        return f"无法访问（{error}）"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit", help="the commit that was deployed")
    parser.add_argument("--url", default="https://daw.xjjk.com/twin/")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--interval", type=float, default=10)
    args = parser.parse_args()
    for attempt in range(1, args.attempts + 1):
        served = served_release(args.url)
        if served == args.commit:
            print(f"daw 已切换到本次发布：{args.url} 运行 {served[:8]}")
            return
        if attempt < args.attempts:
            time.sleep(args.interval)
    raise SystemExit(f"daw 没有切换到本次发布 {args.commit[:8]}：{args.url} 运行的是 {served}")


if __name__ == "__main__":
    main()
