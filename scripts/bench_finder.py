"""Latency of asking the whole team "who knows about this" (``twin.finder``), on made-up twins.

    uv run python scripts/bench_finder.py [--twins 41] [--items 300] [--dim 1024]

Builds ``--twins`` twin databases of ``--items`` items each, with vectors of ``--dim`` numbers (the size of bge-m3's),
then times one question to all of them: the first time (every twin's vectors read from its database and its coverage
worked out), asked again (everything in memory, only each database's mark looked at), and after one twin's memories
changed (that twin read again, the others not). The model's own time to embed the question is not included: it is one
call, whatever the team's size. Prints the numbers; nothing is written outside a temporary directory."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import statistics
import tempfile
import time
from pathlib import Path

import numpy as np

from twin.config import Settings
from twin.finder import Finder, TwinRef
from twin.persona.chat import index_persona
from twin.persona.dimensions import FACETS
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.store import PersonaStore
from twin.teamdb import TeamDB


class RandomEmbedder:
    """A unit vector for each text, the same each time; a question like an item it was made from is near it."""

    name = "random:bench"
    cluster_threshold = 0.5

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            seed = int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "little")
            vector = np.random.default_rng(seed).standard_normal(self.dim).astype(np.float32)
            out[row] = vector / np.linalg.norm(vector)
        return out


def make_items(twin: int, count: int) -> list[PersonaItem]:
    return [
        PersonaItem(
            item_id=f"pi_{twin}_{n}",
            facet_id=FACETS[n % len(FACETS)].facet_id,
            statement=f"第{twin}个人的第{n}条看法",
            evidence=[
                PEvidence(
                    expression_id=f"e_{twin}_{n}_{k}#00000",
                    source_id=f"s_{twin}_{n}_{k}",
                    source_kind=SourceKind.CHAT,
                    evidence_class=EvidenceClass.SELF_REPORT,
                    date=dt.date(2026, 9, 1) + dt.timedelta(days=k),
                    quote="原话",
                )
                for k in range(3)
            ],
        )
        for n in range(count)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--twins", type=int, default=41)
    parser.add_argument("--items", type=int, default=300)
    parser.add_argument("--dim", type=int, default=1024)
    args = parser.parse_args()
    embedder = RandomEmbedder(args.dim)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        started = time.perf_counter()
        twins: list[TwinRef] = []
        for n in range(args.twins):
            path = root / f"p{n}" / "twin.db"
            path.parent.mkdir()
            with PersonaStore(path) as store:
                store.set_meta("built_at", "2026-01-01")
                items = make_items(n, args.items)
                for facet in sorted({i.facet_id for i in items}):
                    store.replace_facet_items(facet, [i for i in items if i.facet_id == facet])
                index_persona(store, embedder, Settings(db_path=path))  # type: ignore[arg-type]
            twins.append(TwinRef(f"p{n}", f"人{n}", path, f"u{n}@x.com", True))
        print(f"made {args.twins} twins x {args.items} items in {time.perf_counter() - started:.1f}s")
        with TeamDB(root / "team" / "team.db") as team:
            finder = Finder(team)
            # Worded as one of the items is, so that the question finds it (the model's embedding of it is one call).
            question = f"{FACETS[7 % len(FACETS)].name}：第3个人的第7条看法"

            def timed() -> tuple[float, int]:
                begun = time.perf_counter()
                found = finder.recommend(question, embedder, twins, "someone@x.com")  # type: ignore[arg-type]
                return (time.perf_counter() - begun) * 1000, len(found)

            cold, found = timed()
            warm = [timed()[0] for _ in range(20)]
            with PersonaStore(twins[0].path) as store:
                store.set_meta("built_at", "2026-02-02")
            changed, _ = timed()
            print(f"first question (read every twin's vectors, work out coverage): {cold:7.0f} ms ({found} found)")
            print(f"asked again, in memory:  median {statistics.median(warm):6.1f} ms, worst {max(warm):6.1f} ms")
            print(f"after one twin changed:  {changed:7.1f} ms")
            held = sum(v.matrix.nbytes for v in finder._vectors.values())
            print(f"vectors held in memory: {held / 1024**2:.0f} MiB")


if __name__ == "__main__":
    main()
