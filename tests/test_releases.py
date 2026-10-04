"""The public stable-release endpoint and version parsing never need a token."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from updater import Updater, version_number


class ReleaseMetadataTests(unittest.TestCase):
    def response(self, value):
        return io.BytesIO(json.dumps(value).encode())

    def test_only_published_stable_version_tags_are_accepted(self):
        with patch("updater.urlopen", return_value=self.response({"tag_name": "v1.2.3"})):
            self.assertEqual(Updater().latest_release(), "v1.2.3")
        for value in ({"tag_name": "v1.2.3-rc1"}, {"tag_name": "../main"},
                      {"tag_name": "v1.2"}, {"tag_name": "v01.2.3"}, {}, [],
                      {"tag_name": "v1.2.3", "draft": True}, {"tag_name": "v1.2.3", "prerelease": True}):
            with self.subTest(value=value), patch("updater.urlopen", return_value=self.response(value)):
                with self.assertRaisesRegex(RuntimeError, "invalid release"):
                    Updater().latest_release()

    def test_no_releases_and_offline_are_distinct(self):
        with patch("updater.urlopen", side_effect=HTTPError("", 404, "Not found", {}, None)):
            self.assertIsNone(Updater().latest_release())
        with patch("updater.urlopen", side_effect=URLError("Offline")):
            with self.assertRaisesRegex(RuntimeError, "connection"):
                Updater().latest_release()

    def test_versions_compare_numerically(self):
        self.assertGreater(version_number("0.10.0"), version_number("0.9.9"))
        for version in (None, "1.2", "v1.2.3", "1.2.3-alpha", "01.2.3"):
            with self.assertRaises(ValueError):
                version_number(version)


if __name__ == "__main__":
    unittest.main()
