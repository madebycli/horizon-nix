#!/usr/bin/env python3
"""Release selection, checksum parsing and Ed25519 signature checks of scripts/update.py."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update", ROOT / "scripts/update.py")
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


def release(tag, assets=update.GAME_ASSETS, **extra):
    return {"tag_name": tag, "assets": [{"name": name} for name in assets], **extra}


class Selection(unittest.TestCase):
    def test_launcher_release_and_game_release_use_semver_and_ignore_date_tags(self):
        releases = [release("launcher@0.2.9", update.LAUNCHER_ASSETS), release("launcher@0.2.55", update.LAUNCHER_ASSETS),
                    release("launcher@0.2.60", update.LAUNCHER_ASSETS, draft=True),
                    release("launcher@0.2.58", update.LAUNCHER_ASSETS, prerelease=True),
                    release("v2026.10.22.16"), release("v0.2.9"), release("v0.2.97"), release("v0.2.100", draft=True)]
        self.assertEqual(update.pick_launcher(releases)["tag_name"], "launcher@0.2.55")
        self.assertEqual(update.pick_release(releases)["tag_name"], "v0.2.97")

    def test_nightly_is_the_newest_dated_release_with_both_archives(self):
        releases = [release("nightly"), release("nightly-2026-11-05"), release("nightly-2026-11-07"),
                    release("nightly-2026-11-08", update.LAUNCHER_ASSETS), release("nightly-source/2026-11-08-abc1234")]
        self.assertEqual(update.pick_nightly(releases)["tag_name"], "nightly-2026-11-07")

    def test_missing_releases_fail_clearly(self):
        for picker in (update.pick_launcher, update.pick_release, update.pick_nightly):
            with self.assertRaises(update.UpdateError):
                picker([release("something-else")])

    def test_versions(self):
        self.assertEqual([update.version_of(t) for t in ("launcher@0.2.55", "v0.2.97", "nightly-2026-11-07")],
                         ["0.2.55", "0.2.97", "nightly-2026-11-07"])


class Checksums(unittest.TestCase):
    def test_parse_and_sri(self):
        digest = hashlib.sha256(b"x").hexdigest()
        sums = update.parse_sums(f"{digest}  a.tar.gz\n{digest} *b.zip\nnot a line\n")
        self.assertEqual(sums, {"a.tar.gz": digest, "b.zip": digest})
        self.assertEqual(update.sri(digest), "sha256-" + base64.b64encode(hashlib.sha256(b"x").digest()).decode())

    def test_signed_names_for_nightlies_include_channel_and_version(self):
        names = update.signed_names(release("nightly-2026-11-07", name="Nightly 2026-11-07 · 1234abc"))
        self.assertIn("nightly", names)
        self.assertIn("nightly-2026-11-07", names)
        self.assertIn("nightly-2026-11-07-1234abc", names)
        self.assertEqual(update.signed_names(release("v0.2.97")), ["v0.2.97"])


@unittest.skipUnless(shutil.which("openssl"), "openssl is required")
class Signatures(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name)
        key = directory / "key.der"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-outform", "DER", "-out", str(key)], check=True)
        public = subprocess.run(["openssl", "pkey", "-inform", "DER", "-in", str(key), "-pubout", "-outform", "DER"],
                                check=True, capture_output=True).stdout[-32:]
        self.key = base64.b64encode(public).decode()
        self.directory, self.private = directory, key

    def sign(self, message: bytes) -> str:
        (self.directory / "m").write_bytes(message)
        subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(self.private), "-keyform", "DER",
                        "-in", str(self.directory / "m"), "-out", str(self.directory / "s")], check=True)
        return base64.b64encode((self.directory / "s").read_bytes()).decode()

    def test_valid_signature_for_the_tag_or_channel_passes_and_others_fail(self):
        sums = b"abc  file\n"
        signature = self.sign(b"horizon release v0.2.97\n" + sums)
        self.assertTrue(update.verify_signature(sums, [signature], ["v0.2.97"], [self.key]))
        self.assertFalse(update.verify_signature(sums, [signature], ["v0.2.98"], [self.key]))
        self.assertFalse(update.verify_signature(sums + b"x", [signature], ["v0.2.97"], [self.key]))
        other = base64.b64encode(b"\x01" * 32).decode()
        self.assertFalse(update.verify_signature(sums, [signature], ["v0.2.97"], [other]))
        self.assertFalse(update.verify_signature(sums, ["not base64!!", ""], ["v0.2.97"], [self.key]))

    def test_second_signature_line_and_nightly_channel_name(self):
        sums = b"abc  file\n"
        channel = self.sign(b"horizon release nightly\n" + sums)
        self.assertTrue(update.verify_signature(sums, ["AAAA", channel], update.signed_names(release("nightly-2026-11-07")), [self.key]))


class Metadata(unittest.TestCase):
    def test_releases_file_shape(self):
        data = json.loads((ROOT / "releases.json").read_text())
        self.assertEqual(set(data) - {"_comment"}, {"launcher", "release", "nightly", "icon"})
        self.assertEqual(set(data["launcher"]["assets"]), set(update.LAUNCHER_ASSETS))
        for channel in ("release", "nightly"):
            self.assertEqual(set(data[channel]["assets"]), set(update.GAME_ASSETS))
        for channel in ("launcher", "release", "nightly"):
            for hash_ in data[channel]["assets"].values():
                self.assertRegex(hash_, r"^(sha256-[A-Za-z0-9+/]{43}=)?$")
        self.assertRegex(data["icon"]["commit"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
