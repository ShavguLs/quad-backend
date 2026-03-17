#!/usr/bin/env python3
"""Helper script to load catalog for GitHub Actions.

Outputs GitHub Actions compatible key=value pairs for catalog metadata.
"""
import json
import sys

def main():
    try:
        catalog = json.load(open('apps/books/tests/fixtures/regression/catalog.json'))
        print(f"catalog_version={catalog['version']}")
        print(f"fixture_count={len(catalog['tiers']['regression']['fixtures'])}")
        critical = [f['id'] for f in catalog['tiers']['regression']['fixtures'] if f['priority'] == 'critical']
        print(f"critical_fixtures={','.join(critical)}")
        return 0
    except Exception as e:
        print(f"Error loading catalog: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
