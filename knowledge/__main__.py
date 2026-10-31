"""Validate a local contribution: python -m knowledge path/to/catalog.json."""
import argparse
from pathlib import Path
from pydantic import ValidationError
from .models import Catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('catalog', type=Path)
    args = parser.parse_args()
    try:
        catalog = Catalog.model_validate_json(args.catalog.read_text(encoding='utf-8'))
    except (OSError, ValidationError) as exc:
        parser.exit(1, f'Invalid catalog: {exc}\n')
    print(f'Valid schema 1.0 catalog: {len(catalog.records)} records (not a factual review).')


if __name__ == '__main__':
    main()
