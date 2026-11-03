"""Check that the official bulk file contains every company of the 2026-10-26 sample report.

The sample (Norrköping, Linköping, Finspång; 108 companies) was built from a third-party copy
of Bolagsverket's file. This script proves or disproves it against the official download.
Only salted SHA-256 hashes of "orgnr|registreringsdatum" are stored in the repo, no company data.

usage: python validation/verify_sample.py <official bolagsverket_bulkfil.zip>
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nyabolag.bulkfile import iter_companies  # noqa: E402

SALT = "nyabolag-sample-2026-10-26"
HASHES = Path(__file__).with_name("sample-2026-10-26.sha256")


def h(orgnr: str, reg: str) -> str:
    return hashlib.sha256(f"{SALT}|{orgnr}|{reg}".encode()).hexdigest()


def main(path: str) -> int:
    expected = set(HASHES.read_text().split())
    found = set()
    for c in iter_companies(Path(path)):
        if c.reg_date:
            k = h(c.orgnr, c.reg_date.isoformat())
            if k in expected:
                found.add(k)
    missing = len(expected - found)
    print(f"{len(found)}/{len(expected)} sample companies found in the official file with the same "
          f"registration date; {missing} missing")
    if missing:
        print("Missing companies may have been deregistered since 2026-10-26 (check a few by hand), "
              "or the third-party copy differed from the official file.")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
