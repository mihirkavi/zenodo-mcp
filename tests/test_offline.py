"""Offline tests: no network, no token. Run: uv run --with mcp==2.3.0 python -m unittest discover -s tests"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import zenodo_client as zc  # noqa: E402


class MetadataTests(unittest.TestCase):
    def test_creators_from_strings_and_dicts(self):
        md = zc.build_metadata(creators=["Doe, Jane", {"name": "Roe, Rick", "orcid": "0000-0002-1825-0097",
                                                       "ignored": "x"}])
        self.assertEqual(md["creators"], [{"name": "Doe, Jane"},
                                          {"name": "Roe, Rick", "orcid": "0000-0002-1825-0097"}])

    def test_creator_needs_name(self):
        with self.assertRaises(zc.ZenodoError):
            zc.build_metadata(creators=[{"affiliation": "MIT"}])

    def test_only_given_fields(self):
        md = zc.build_metadata(title="T", communities=["zenodo"], keywords=[" a ", ""])
        self.assertEqual(md, {"title": "T", "communities": [{"identifier": "zenodo"}], "keywords": ["a"]})

    def test_summarize_deposition_reserved_doi(self):
        s = zc.summarize_deposition({"id": 1, "state": "unsubmitted", "submitted": False,
                                     "metadata": {"title": "T", "prereserve_doi": {"doi": "10.5281/zenodo.2"}},
                                     "files": [{"id": "f", "filename": "p.pdf", "filesize": 3}]})
        self.assertEqual((s["doi"], s["doi_status"]), ("10.5281/zenodo.2", "reserved"))
        self.assertEqual(s["files"][0]["filename"], "p.pdf")


class ConfigTests(unittest.TestCase):
    def test_sandbox_switch(self):
        with mock.patch.dict(os.environ, {"ZENODO_SANDBOX": "1", "ZENODO_BASE_URL": ""}):
            self.assertEqual(zc.base_url(), zc.SANDBOX_URL)
            self.assertEqual(zc.keychain_account(), "sandbox")
        with mock.patch.dict(os.environ, {"ZENODO_SANDBOX": "", "ZENODO_BASE_URL": ""}):
            self.assertEqual(zc.base_url(), zc.PRODUCTION_URL)

    def test_env_token_wins_and_placeholder_ignored(self):
        with mock.patch.dict(os.environ, {"ZENODO_TOKEN": "abc1234"}):
            self.assertEqual(zc.read_token(), "abc1234")
            self.assertEqual(zc.token_status()["fingerprint"], "…1234")
        with mock.patch.dict(os.environ, {"ZENODO_TOKEN": "${ZENODO_TOKEN}"}), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=44, stdout="")):
            self.assertIsNone(zc.read_token(required=False))

    def test_bad_token_rejected_before_keychain(self):
        with self.assertRaises(zc.ZenodoError):
            zc.store_token("has space")


class ServerTests(unittest.TestCase):
    def test_publish_requires_confirm(self):
        import zenodo_mcp as srv
        fake = mock.Mock()
        fake.get_deposition.return_value = {"id": 5, "metadata": {"title": "T"}, "files": []}
        with mock.patch.object(srv, "client", return_value=fake):
            out = srv.zenodo_publish(5)
        self.assertIn("preview", out)
        self.assertIn("no files uploaded", out["problems"])
        fake.action.assert_not_called()


if __name__ == "__main__":
    unittest.main()
