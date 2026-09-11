from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bdo_music_composer.app.release_evidence import (
    InstalledPackage,
    build_spdx_document,
    installed_packages,
    sha256_file,
    write_release_evidence,
)


class ReleaseEvidenceTests(unittest.TestCase):
    def test_installed_packages_excludes_the_application_distribution(self) -> None:
        class Distribution:
            def __init__(self, name: str, version: str) -> None:
                self.metadata = {"Name": name, "License-Expression": "MIT"}
                self.version = version

        distributions = (
            Distribution("bdo_music_composer", "1.2.0.2"),
            Distribution("Example-Dependency", "3.0"),
        )
        with patch(
            "bdo_music_composer.app.release_evidence.importlib.metadata.distributions",
            return_value=distributions,
        ):
            self.assertEqual(
                installed_packages(),
                (InstalledPackage("Example-Dependency", "3.0", "MIT"),),
            )

    def test_spdx_is_deterministic_and_contains_artifact_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "app.exe"
            artifact.write_bytes(b"release-candidate")
            packages = (
                InstalledPackage("Zeta", "2", "MIT"),
                InstalledPackage("Alpha", "1", "Apache-2.0"),
            )
            first = build_spdx_document(artifact, packages)
            second = build_spdx_document(artifact, packages)
            self.assertEqual(first, second)
            self.assertEqual(
                first["files"][0]["checksums"][0]["checksumValue"],
                sha256_file(artifact),
            )

    def test_release_evidence_is_atomically_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "app.exe"
            artifact.write_bytes(b"candidate")
            checksum, sbom = write_release_evidence(artifact, root / "evidence")
            self.assertIn(sha256_file(artifact), checksum.read_text(encoding="ascii"))
            self.assertEqual(json.loads(sbom.read_text())["spdxVersion"], "SPDX-2.3")


if __name__ == "__main__":
    unittest.main()
