"""Compare Toto 2.0 checkpoint sizes as node encoders.

Answers three questions, in order of how much they actually matter:

1. **Does it run?** Parameters, load time, peak device memory.
2. **Does it encode usefully?** A checkpoint that is slower and bigger but produces
   degenerate embeddings is not an upgrade. Three probes, each targeting a property
   the graph model depends on:
     * *discrimination* -- distinct series must not collapse onto one vector;
     * *similarity preservation* -- a series and a lightly perturbed copy of it must
       sit closer together than two unrelated series, or the embedding carries no
       metric structure for the graph to use;
     * *level sensitivity* -- a pure level shift must move the embedding, since a
       level-driven risk signal is exactly what a risk system watches.
3. **What does it cost?** Encoding latency per node, so the size decision is made
   against a number rather than an impression.

Nothing downloads. Each checkpoint is loaded with ``local_files_only`` and skipped
if it is not already on disk, so this is safe to run repeatedly.

Usage::

    python -m backend.scripts.compare_encoder_sizes
    python -m backend.scripts.compare_encoder_sizes --models Datadog/Toto-2.0-313m
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

DEFAULT_MODELS = [
    "Datadog/Toto-2.0-313m",
    "Datadog/Toto-2.0-1B",
    "Datadog/Toto-2.0-2.5B",
]


def _cached(repo: str) -> bool:
    root = Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + repo.replace("/", "--"))
    return root.is_dir()


def _panel(n_series: int, n_steps: int, seed: int) -> np.ndarray:
    """A panel of random walks, which is roughly what a node series looks like."""
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(scale=0.5, size=(n_series, n_steps)), axis=1) + 100.0


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0.0:
        return 0.0
    return float(1.0 - float(np.dot(a, b)) / denominator)


def _mean_pairwise(embeddings: np.ndarray) -> float:
    n = embeddings.shape[0]
    if n < 2:
        return 0.0
    distances = [
        _cosine_distance(embeddings[i], embeddings[j])
        for i in range(n)
        for j in range(i + 1, n)
    ]
    return float(np.mean(distances))


def probe(model_id: str, *, n_series: int, n_steps: int, batch_size: int) -> Dict[str, Any]:
    """Measure one checkpoint. Returns a record, or a skip reason."""
    from backend.modules.engine.foundation_encoders import TotoEncoder, compose_input

    if not _cached(model_id):
        return {"model": model_id, "status": "not on disk (skipped, nothing downloaded)"}

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    context = max(64, (n_steps // 32) * 32)
    started = time.time()
    try:
        encoder = TotoEncoder(
            model_id=model_id,
            device=device,
            dtype="float32",
            batch_size=batch_size,
            context_length=context,
        )
    except Exception as error:
        return {"model": model_id, "status": f"load failed: {type(error).__name__}: {error}"}
    load_seconds = time.time() - started

    panel = _panel(n_series, n_steps, seed=11)
    data = compose_input(panel)

    started = time.time()
    embeddings = encoder.encode(data)
    encode_seconds = time.time() - started

    peak_bytes: Optional[int] = None
    if device == "cuda":
        peak_bytes = int(torch.cuda.max_memory_allocated())

    # -- probe 1: discrimination
    distinct = len({tuple(np.round(row, 6)) for row in embeddings})
    mean_pairwise = _mean_pairwise(embeddings)

    # -- probe 2: similarity preservation. A lightly perturbed copy of series 0
    #    must be closer to series 0 than series 1 is.
    rng = np.random.default_rng(99)
    near = panel[0] + rng.normal(scale=0.05, size=panel.shape[1])
    pair = compose_input(np.vstack([panel[0], near, panel[1]]))
    pair_embeddings = encoder.encode(pair)
    distance_to_copy = _cosine_distance(pair_embeddings[0], pair_embeddings[1])
    distance_to_other = _cosine_distance(pair_embeddings[0], pair_embeddings[2])

    # -- probe 3: level sensitivity
    shifted = compose_input(np.vstack([panel[0], panel[0] + 500.0]))
    shifted_embeddings = encoder.encode(shifted)
    level_distance = _cosine_distance(shifted_embeddings[0], shifted_embeddings[1])

    return {
        "model": model_id,
        "status": "ok",
        "n_parameters": encoder.n_parameters(),
        "embed_dim": encoder.embed_dim,
        "device": device,
        "load_seconds": round(load_seconds, 2),
        "encode_seconds": round(encode_seconds, 3),
        "seconds_per_node": round(encode_seconds / max(n_series, 1), 4),
        "peak_device_gb": None if peak_bytes is None else round(peak_bytes / 1e9, 2),
        "distinct_embeddings": f"{distinct}/{n_series}",
        "mean_pairwise_cosine_distance": round(mean_pairwise, 4),
        "similarity_preserved": bool(distance_to_copy < distance_to_other),
        "distance_to_copy": round(distance_to_copy, 4),
        "distance_to_unrelated": round(distance_to_other, 4),
        "level_shift_moves_embedding": bool(level_distance > 1e-6),
        "level_shift_distance": round(level_distance, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    parser.add_argument("--series", type=int, default=8)
    parser.add_argument("--steps", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--json", type=Path, default=None, help="write results here")
    args = parser.parse_args()

    records: List[Dict[str, Any]] = []
    for model_id in args.models:
        print(f"[{model_id}] ...", flush=True)
        record = probe(
            model_id, n_series=args.series, n_steps=args.steps, batch_size=args.batch_size
        )
        records.append(record)
        if record.get("status") != "ok":
            print(f"    {record['status']}")
            continue
        print(
            f"    params={record['n_parameters']:,}  dim={record['embed_dim']}  "
            f"load={record['load_seconds']}s  "
            f"{record['seconds_per_node']}s/node  peak={record['peak_device_gb']}GB"
        )
        print(
            f"    distinct={record['distinct_embeddings']}  "
            f"similarity_preserved={record['similarity_preserved']}  "
            f"level_sensitive={record['level_shift_moves_embedding']}"
        )

    if args.json:
        args.json.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
