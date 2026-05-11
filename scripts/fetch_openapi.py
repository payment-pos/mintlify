#!/usr/bin/env python3
"""
OpenAPI fetcher for Payven Mintlify docs.

Composer'lardan canli OpenAPI spec'lerini indirir ve
`mintlify/api-reference/<service>/openapi.json` dosyalarina yazar.

Tipik kullanim:

    python scripts/fetch_openapi.py                 # default: sandbox
    python scripts/fetch_openapi.py --env local     # localhost dev portlari
    python scripts/fetch_openapi.py --env prod      # production
    python scripts/fetch_openapi.py --service sanal-pos

Sonra enrich script'i calistir:

    python scripts/enrich_openapi.py

Idempotent: HTTP 200 + valid JSON donen her endpoint icin spec'i overwrite eder.
Bir endpoint dustugunde digerlerine devam eder, exit code o noktada non-zero olur.

Dependency: yalniz Python 3 stdlib (urllib).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Composer host'lari ve mintlify spec output yollari.
SERVICES = {
    "sanal-pos": ROOT / "api-reference/sanal-pos/openapi.json",
    "transfer": ROOT / "api-reference/transfer/openapi.json",
    "identity": ROOT / "api-reference/identity/openapi.json",
    "fraud":    ROOT / "api-reference/fraud/openapi.json",
}

ENV_HOSTS = {
    "sandbox": {
        "sanal-pos": "https://vpos-sandbox.payven.com.tr",
        "transfer":  "https://transfer-sandbox.payven.com.tr",
        "identity":  "https://identity-sandbox.payven.com.tr",
        "fraud":     "https://fraud-sandbox.payven.com.tr",
    },
    "prod": {
        "sanal-pos": "https://vpos.payven.com.tr",
        "transfer":  "https://transfer.payven.com.tr",
        "identity":  "https://identity.payven.com.tr",
        "fraud":     "https://fraud.payven.com.tr",
    },
    "local": {
        "sanal-pos": "http://localhost:5001",
        "transfer":  "http://localhost:5000",
        "identity":  "http://localhost:5101",
        "fraud":     "http://localhost:5102",
    },
}

# Composer Swagger endpoint'i — versioned API icin v1.
SWAGGER_PATH = "/swagger/v1/swagger.json"

# Network timeout (saniye).
TIMEOUT = 30


def fetch_spec(host: str) -> dict:
    """HTTP GET <host>/swagger/v1/swagger.json. Raises on non-200 or invalid JSON."""
    url = host.rstrip("/") + SWAGGER_PATH
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            raise RuntimeError(f"{url} -> HTTP {resp.status}")
        body = resp.read().decode("utf-8")
    return json.loads(body)  # raises ValueError on invalid JSON


def write_spec(spec: dict, dest: Path) -> None:
    """Pretty-print + 2-space indent (enrich_openapi.py ile ayni format)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch composer OpenAPI specs.")
    parser.add_argument(
        "--env",
        choices=sorted(ENV_HOSTS.keys()),
        default="sandbox",
        help="Hangi ortamdan cekilecek (default: sandbox).",
    )
    parser.add_argument(
        "--service",
        choices=sorted(SERVICES.keys()),
        action="append",
        help="Belirli servis(ler)i cek; tekrarlanabilir. Bos = hepsi.",
    )
    args = parser.parse_args()

    targets = args.service or list(SERVICES.keys())
    hosts = ENV_HOSTS[args.env]

    failures: list[tuple[str, str]] = []
    for service in targets:
        host = hosts[service]
        dest = SERVICES[service]
        url = host + SWAGGER_PATH
        print(f"[{service}] GET {url}")
        try:
            spec = fetch_spec(host)
            write_spec(spec, dest)
            paths = len(spec.get("paths", {}))
            print(f"[{service}]   wrote {dest.relative_to(ROOT)} ({paths} paths)")
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, ValueError, OSError) as exc:
            msg = f"{type(exc).__name__}: {exc}"
            print(f"[{service}]   FAILED — {msg}", file=sys.stderr)
            failures.append((service, msg))

    if failures:
        print(file=sys.stderr)
        print(f"{len(failures)} servis spec'i indirilemedi:", file=sys.stderr)
        for service, msg in failures:
            print(f"  - {service}: {msg}", file=sys.stderr)
        print(file=sys.stderr)
        print("Sonraki adim: enrich script'i yine calistir (basari ile inenler enrich edilir):", file=sys.stderr)
        print("    python scripts/enrich_openapi.py", file=sys.stderr)
        return 1

    print()
    print(f"Tum {len(targets)} spec basariyla indirildi. Sonraki adim:")
    print("    python scripts/enrich_openapi.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
