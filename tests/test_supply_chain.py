"""Tests for deterministic release supply-chain artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.generate_sbom import SBOM_SCHEMA_VERSION, build_sbom


ROOT = Path(__file__).resolve().parents[1]


class SupplyChainTests(unittest.TestCase):
    def test_declared_dependency_sbom_is_deterministic_and_excludes_dev_by_default(self):
        first = build_sbom(ROOT)
        second = build_sbom(ROOT)

        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(first["bomFormat"], "CycloneDX")
        self.assertEqual(first["specVersion"], "1.5")
        self.assertEqual(first["metadata"]["component"]["name"], "citationguard")
        self.assertEqual(first["metadata"]["properties"][0]["value"], str(SBOM_SCHEMA_VERSION))
        names = {component["name"] for component in first["components"]}
        self.assertIn("mcp", names)
        self.assertIn("pypdf", names)
        self.assertIn("cryptography", names)
        self.assertIn("sentence-transformers", names)
        self.assertNotIn("build", names)
        self.assertNotIn("pytest", names)
        mcp = next(component for component in first["components"] if component["name"] == "mcp")
        self.assertIn(
            {
                "name": "citeguard:declared_requirement",
                "value": "mcp>=1.28,<2; python_version >= '3.10'",
            },
            mcp["properties"],
        )
        cryptography = next(component for component in first["components"] if component["name"] == "cryptography")
        self.assertIn(
            {
                "name": "citeguard:declared_requirement",
                "value": "cryptography>=50; python_version >= '3.10'",
            },
            cryptography["properties"],
        )

    def test_dev_dependencies_are_opt_in_for_the_declared_dependency_sbom(self):
        sbom = build_sbom(ROOT, include_dev=True)

        names = {component["name"] for component in sbom["components"]}
        self.assertIn("build", names)
        build_component = next(component for component in sbom["components"] if component["name"] == "build")
        self.assertIn(
            {"name": "citeguard:dependency_group", "value": "optional:dev"},
            build_component["properties"],
        )


if __name__ == "__main__":
    unittest.main()
