# The image the backend checks in .cnb.yml run in: what they need beyond Python, installed once. cnb builds it from
# this file, keeps it in the repository's artifact registry and rebuilds it only when this file changes, so a run
# no longer downloads the CJK fonts (apt caches are kept per build machine, which is rarely the same one). No ffmpeg:
# the tests that run it (marked codec) are left to the codec host, as scripts/check.py does.
FROM python:3.12-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.13.0
