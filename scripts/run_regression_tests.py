#!/usr/bin/env python3
"""Regression test runner with fixture-level reporting.

This script provides a CLI wrapper around pytest for running regression tests
with detailed reporting, fixture filtering, and golden file management.

Usage:
    python scripts/run_regression_tests.py --list
    python scripts/run_regression_tests.py --fixtures list-simple,heading-hierarchy
    python scripts/run_regression_tests.py --verbose
    python scripts/run_regression_tests.py --update
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Path to catalog file (relative to api/ directory)
CATALOG_PATH = Path("apps/books/tests/fixtures/regression/catalog.json")


def load_catalog() -> dict[str, Any]:
    """Load the fixture catalog from JSON.
    
    Returns:
        Dict containing the full catalog structure.
        
    Raises:
        FileNotFoundError: If catalog file doesn't exist.
        json.JSONDecodeError: If catalog JSON is invalid.
    """
    if not CATALOG_PATH.exists():
        print(f"Error: Catalog file not found at {CATALOG_PATH}")
        print("Run this script from the api/ directory.")
        sys.exit(2)
    
    with open(CATALOG_PATH) as f:
        return json.load(f)


def get_fixture_ids(catalog: dict[str, Any], filter_ids: list[str] | None = None) -> list[str]:
    """Get list of fixture IDs, optionally filtered.
    
    Args:
        catalog: The loaded catalog dict.
        filter_ids: Optional list of specific fixture IDs to include.
        
    Returns:
        List of fixture ID strings.
    """
    all_fixtures = catalog["tiers"]["regression"]["fixtures"]
    all_ids = [f["id"] for f in all_fixtures]
    
    if filter_ids:
        # Validate that requested fixtures exist
        invalid = set(filter_ids) - set(all_ids)
        if invalid:
            print(f"Error: Unknown fixture IDs: {', '.join(invalid)}")
            print(f"Available fixtures: {', '.join(all_ids)}")
            sys.exit(2)
        return filter_ids
    
    return all_ids


def get_fixture_metadata(catalog: dict[str, Any], fixture_id: str) -> dict[str, Any]:
    """Get metadata for a specific fixture.
    
    Args:
        catalog: The loaded catalog dict.
        fixture_id: The fixture ID to look up.
        
    Returns:
        Fixture metadata dict.
    """
    for fixture in catalog["tiers"]["regression"]["fixtures"]:
        if fixture["id"] == fixture_id:
            return fixture
    raise ValueError(f"Fixture not found: {fixture_id}")


def list_fixtures(catalog: dict[str, Any]) -> None:
    """Print a formatted list of all fixtures.
    
    Args:
        catalog: The loaded catalog dict.
    """
    print("=" * 60)
    print("REGRESSION FIXTURE CATALOG")
    print("=" * 60)
    print(f"Version: {catalog['version']}")
    print(f"Last Updated: {catalog['lastUpdated']}")
    print()
    
    fixtures = catalog["tiers"]["regression"]["fixtures"]
    
    # Group by priority
    critical = [f for f in fixtures if f["priority"] == "critical"]
    high = [f for f in fixtures if f["priority"] == "high"]
    medium = [f for f in fixtures if f["priority"] == "medium"]
    
    if critical:
        print(f"CRITICAL ({len(critical)}) - Must pass in CI:")
        for f in critical:
            print(f"  [OK] {f['id']}: {f['name']}")
            print(f"       Category: {f['category']} | {f['description'][:50]}...")
        print()
    
    if high:
        print(f"HIGH ({len(high)}) - Should pass in CI:")
        for f in high:
            print(f"  [ok] {f['id']}: {f['name']}")
            print(f"       Category: {f['category']} | {f['description'][:50]}...")
        print()
    
    if medium:
        print(f"MEDIUM ({len(medium)}) - Best effort:")
        for f in medium:
            print(f"  [-] {f['id']}: {f['name']}")
        print()
    
    print("=" * 60)
    print(f"Total fixtures: {len(fixtures)}")
    print("=" * 60)
    print()
    print("Usage:")
    print("  Run all tests:      python scripts/run_regression_tests.py")
    print("  Run specific:       python scripts/run_regression_tests.py --fixtures list-simple")
    print("  Update golden:      python scripts/run_regression_tests.py --update")


def run_pytest(fixture_ids: list[str] | None = None, 
               verbose: bool = False,
               update: bool = False) -> int:
    """Execute pytest subprocess with appropriate arguments.
    
    Args:
        fixture_ids: Optional list of specific fixture IDs to test.
        verbose: Whether to run with verbose output.
        update: Whether to regenerate golden files (--force-regen).
        
    Returns:
        Exit code from pytest (0=pass, 1=fail, 2=config error).
    """
    cmd = ["python", "-m", "pytest", "-m", "regression"]
    
    if verbose:
        cmd.append("-v")
    else:
        cmd.append("--tb=short")
    
    if update:
        cmd.append("--force-regen")
        print("WARNING: Regenerating golden files!")
        print("       This will update expected outputs. Only do this if you've")
        print("       intentionally changed casting behavior and verified correctness.\n")
    
    # If specific fixtures requested, filter tests
    if fixture_ids:
        # Build test selection based on fixture IDs
        test_names = []
        for fid in fixture_ids:
            # Map fixture IDs to test function names
            if fid == "list-simple":
                test_names.append("test_list_simple_structure")
            elif fid == "heading-hierarchy":
                test_names.append("test_heading_hierarchy")
            elif fid == "mixed-content":
                test_names.append("test_mixed_content_flow")
            elif fid == "style-preservation":
                test_names.append("test_style_preservation")
            else:
                test_names.append(f"test_{fid.replace('-', '_')}")
        
        # Use -k to filter tests
        cmd.extend(["-k", " or ".join(test_names)])
    
    print(f"Running: {' '.join(cmd)}\n")
    
    result = subprocess.run(cmd)
    return result.returncode


def report_results(exit_code: int, fixture_ids: list[str] | None = None) -> None:
    """Print formatted summary report.
    
    Args:
        exit_code: The pytest exit code.
        fixture_ids: Optional list of fixtures that were tested.
    """
    print("\n" + "=" * 60)
    print("REGRESSION TEST SUMMARY")
    print("=" * 60)
    
    if exit_code == 0:
        print("[PASS] All regression tests PASSED")
        if fixture_ids:
            print(f"       Fixtures tested: {', '.join(fixture_ids)}")
        print("\n       PDF casting fidelity is preserved.")
        print("       No changes detected in output structure.")
    elif exit_code == 1:
        print("[FAIL] Some regression tests FAILED")
        if fixture_ids:
            print(f"       Fixtures tested: {', '.join(fixture_ids)}")
        print("\n       WARNING: CRITICAL FIXTURE FAILURES block CI")
        print("\n       If these failures are expected (intentional changes):")
        print("       1. Review the failures carefully")
        print("       2. Verify new output is correct")
        print("       3. Run: python scripts/run_regression_tests.py --update")
        print("\n       If these failures are NOT expected:")
        print("       - This indicates a regression in PDF casting")
        print("       - Investigate the converter changes")
        print("       - Fix the underlying issue, don't update golden files")
    elif exit_code == 2:
        print("[ERROR] Test configuration ERROR")
        print("        Check that pytest and pytest-regressions are installed")
        print("        Run: pip install pytest pytest-regressions")
    elif exit_code == 3:
        print("[WARN] No tests collected")
        print("       No regression tests matched the criteria")
    else:
        print(f"[ERROR] Unexpected exit code: {exit_code}")
    
    print("=" * 60)


def main() -> int:
    """Main entry point.
    
    Returns:
        Exit code (0=success, 1=fail, 2=config error).
    """
    parser = argparse.ArgumentParser(
        description="Run regression tests for PDF casting fidelity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  List all fixtures:
    python scripts/run_regression_tests.py --list

  Run all regression tests:
    python scripts/run_regression_tests.py

  Run specific fixtures:
    python scripts/run_regression_tests.py --fixtures list-simple,heading-hierarchy

  Run with verbose output:
    python scripts/run_regression_tests.py --verbose

  Update golden files (USE WITH CAUTION):
    python scripts/run_regression_tests.py --update
        """
    )
    
    parser.add_argument(
        "--fixtures",
        type=str,
        help="Comma-separated list of fixture IDs to test (default: all)"
    )
    
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available fixtures and exit"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    parser.add_argument(
        "--update",
        action="store_true",
        help="Regenerate golden files (USE WITH CAUTION)"
    )
    
    args = parser.parse_args()
    
    # Load catalog
    try:
        catalog = load_catalog()
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading catalog: {e}")
        return 2
    
    # Handle --list
    if args.list:
        list_fixtures(catalog)
        return 0
    
    # Parse fixture filter
    fixture_ids = None
    if args.fixtures:
        fixture_ids = [f.strip() for f in args.fixtures.split(",")]
        # Validate fixtures exist
        try:
            get_fixture_ids(catalog, fixture_ids)
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 2
    
    # Print header
    print("=" * 60)
    print("PDF CASTING REGRESSION TESTS")
    print("=" * 60)
    print(f"Catalog version: {catalog['version']}")
    if fixture_ids:
        print(f"Running fixtures: {', '.join(fixture_ids)}")
    else:
        print("Running all fixtures")
    print()
    
    # Run tests
    exit_code = run_pytest(fixture_ids, args.verbose, args.update)
    
    # Report results
    report_results(exit_code, fixture_ids)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
