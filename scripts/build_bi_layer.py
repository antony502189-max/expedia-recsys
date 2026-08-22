"""Build Stage 2 dashboard-specific BI Parquet marts from accepted Stage 1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from expedia_analytics.bi_dashboard import SOURCE_BUILD_ID, build_bi_layer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--build-id", default=SOURCE_BUILD_ID)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the existing BI exports for this accepted source build.",
    )
    args = parser.parse_args()
    manifest = build_bi_layer(args.root, build_id=args.build_id, replace=args.replace)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
