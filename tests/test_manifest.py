from pathlib import Path
import unittest

from cyberbench.manifest import load_manifest, validate_manifest


class ManifestTests(unittest.TestCase):
    def test_smoke_bundle_validates(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))

        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(manifest.bundle_id, "smoke-web")
        self.assertEqual(len(manifest.scored_services), 1)
        self.assertEqual(len(manifest.decoy_services), 1)

    def test_strict_non_smoke_requires_ten_scored_services(self) -> None:
        manifest = load_manifest(Path("bundles/smoke-web/manifest.json"))

        self.assertEqual(validate_manifest(manifest, strict=True), [])

    def test_google_web_10_has_exactly_ten_scored_services(self) -> None:
        manifest = load_manifest(Path("bundles/google-web-10/manifest.json"))

        self.assertEqual(validate_manifest(manifest, strict=True), [])
        self.assertEqual(len(manifest.scored_services), 10)
        self.assertEqual(len(manifest.decoy_services), 3)


if __name__ == "__main__":
    unittest.main()
