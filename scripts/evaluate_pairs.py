import argparse
import csv
import json
import statistics
import time

from app.core.compare import compare_buffalo, compare_deepface


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate face comparison pairs from CSV.")
    parser.add_argument("--pairs", required=True, help="CSV with img_a,img_b,label columns. label: 1 same, 0 different")
    parser.add_argument("--engine", choices=["buffalo_l", "deepface"], required=True)
    parser.add_argument("--output", default="results.jsonl")
    parser.add_argument("--model-name", default="ArcFace")
    parser.add_argument("--detector-backend", default="retinaface")
    parser.add_argument("--distance-metric", default="cosine")
    return parser.parse_args()


def load_pairs(path):
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            yield {
                "img_a": row["img_a"],
                "img_b": row["img_b"],
                "label": int(row["label"]),
            }


def main():
    args = parse_args()
    scores = []
    latencies = []
    failures = 0

    with open(args.output, "w") as out:
        for pair in load_pairs(args.pairs):
            started = time.perf_counter()
            record = dict(pair)
            try:
                if args.engine == "buffalo_l":
                    result = compare_buffalo(pair["img_a"], pair["img_b"], threshold=None)
                    score = result["score"]
                    score_type = "similarity"
                else:
                    result = compare_deepface(
                        pair["img_a"],
                        pair["img_b"],
                        args.model_name,
                        args.detector_backend,
                        args.distance_metric,
                        threshold=None,
                    )
                    score = result["distance"]
                    score_type = "distance"
                elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                record.update(result)
                record.update({"ok": True, "score_value": score, "score_type": score_type, "elapsed_ms": elapsed_ms})
                scores.append({"score": score, "label": pair["label"], "score_type": score_type})
                latencies.append(elapsed_ms)
            except Exception as exc:
                failures += 1
                record.update({"ok": False, "error": str(exc)})
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = {
        "pairs": len(scores) + failures,
        "ok": len(scores),
        "failures": failures,
        "latency_ms_avg": round(statistics.mean(latencies), 2) if latencies else None,
        "latency_ms_p95": round(statistics.quantiles(latencies, n=20)[18], 2) if len(latencies) >= 20 else None,
        "output": args.output,
        "note": "Use the JSONL scores to choose thresholds and calculate FAR/FRR.",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
