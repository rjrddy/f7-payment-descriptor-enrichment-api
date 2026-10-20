"""Normalize synthetic merchant descriptors with an explicit unknown category and cache."""

import json
import random
import re
import time
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

CATALOG = [
    {"id": str(i), "name": f"Synthetic {name} {i:02d}", "category": category}
    for i, (name, category) in enumerate(
        [
            ("Juniper Cafe", "food"),
            ("Orion Tools", "hardware"),
            ("Meadow Books", "books"),
            ("Cedar Market", "groceries"),
        ]
        * 5
    )
]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"^(sq|tst|pos)\s*\*\s*", "", value)
    value = re.sub(r"\s*#\d+.*$", "", value)
    return " ".join(re.findall(r"[a-z0-9]+", value))


@lru_cache(maxsize=1024)
def enrich(descriptor: str) -> dict:
    key = normalize(descriptor)
    exact = [merchant for merchant in CATALOG if normalize(merchant["name"]) == key]
    if exact:
        return {**exact[0], "confidence": 1.0}
    ranked = sorted(
        [
            (SequenceMatcher(None, key, normalize(m["name"])).ratio(), i)
            for i, m in enumerate(CATALOG)
        ],
        reverse=True,
    )
    if ranked[0][0] >= 0.86 and ranked[0][0] - ranked[1][0] >= 0.02:
        return {**CATALOG[ranked[0][1]], "confidence": ranked[0][0]}
    return {"id": None, "name": None, "category": "unknown", "confidence": ranked[0][0]}


class Request(BaseModel):
    descriptor: str = Field(min_length=1, max_length=256)


app = FastAPI()


@app.post("/enrich")
def endpoint(request: Request) -> dict:
    return enrich(request.descriptor)


def sample() -> list[dict]:
    rng = random.Random(42)
    rows = []
    for i in range(500):
        merchant = CATALOG[i % len(CATALOG)]
        name = merchant["name"]
        if i % 5 == 0:
            name = name.replace("Juniper", "Junipre")
        descriptor = (
            rng.choice(["SQ* ", "TST* ", "POS* ", ""]) + name + f" #{rng.randint(10000, 99999)}"
        )
        rows.append({"descriptor": descriptor, "truth": merchant["id"]})
    rows.extend({"descriptor": f"UNLISTED VENDOR {i}", "truth": None} for i in range(100))
    return rows


def benchmark() -> dict:
    enrich.cache_clear()
    rows = sample()
    latencies = []
    correct = 0
    report = []
    with TestClient(app) as client:
        for row in rows:
            start = time.perf_counter()
            response = client.post("/enrich", json={"descriptor": row["descriptor"]})
            latencies.append((time.perf_counter() - start) * 1000)
            response.raise_for_status()
            actual = response.json()
            correct += actual["id"] == row["truth"]
            report.append({**row, "actual": actual})
        for row in rows[:50]:
            client.post("/enrich", json={"descriptor": row["descriptor"]}).raise_for_status()
    Path("evidence/labeled-results.json").write_text(json.dumps(report, indent=2))
    return {
        "labeled_descriptors": len(rows),
        "accuracy": correct / len(rows),
        "p99_api_ms": sorted(latencies)[int(0.99 * (len(latencies) - 1))],
        "cache_hits": enrich.cache_info().hits,
        "latencies_ms": latencies,
    }


if __name__ == "__main__":
    print(json.dumps(benchmark(), indent=2))
