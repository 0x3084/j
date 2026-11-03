"""Download, validate and store all research data.  Usage: python -m scripts.ingest"""
import json
import time

from qrs.data.store import ingest_all

if __name__ == "__main__":
    t = time.time()
    q = ingest_all()
    print(json.dumps(q["cross_checks"], indent=1))
    print(f"done in {time.time() - t:.0f}s -> reports/data_quality.md")
