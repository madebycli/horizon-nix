#!/usr/bin/env python3
"""Pin Horizon's latest launcher release, numbered game release and Nightly in releases.json.

Every pin comes from the release's own SHA256SUMS, after its Ed25519 signature checked out against
Horizon's public release key (docs/release-flow.md "Signed checksums" in horizon-rust/horizon).
The large archives are not downloaded. Needs python3 and openssl 3.

  python3 scripts/update.py                  # write the newest verified pins
  python3 scripts/update.py --check          # exit 1 when anything is stale or unpinned
  python3 scripts/update.py --verify         # re-verify the pins already in releases.json
  python3 scripts/update.py --verify --allow-unpinned
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = "horizon-rust/horizon"
API = f"https://api.github.com/repos/{REPO}/releases"
DOWNLOAD = f"https://github.com/{REPO}/releases/download"
ROOT = Path(__file__).resolve().parents[1]
RELEASES_FILE = ROOT / "releases.json"

# crates/horizon-release-sign/release-keys.txt in horizon-rust/horizon (base64, raw Ed25519 public keys).
# A rotation adds a key there first: add it here after reading that change, then drop the old one.
RELEASE_KEYS = ["MU4oiIQcCxkZvbwSjjXs7SySCuM6ywRQ3nGaJYZG0gw="]
SPKI_ED25519_PREFIX = bytes.fromhex("302a300506032b6570032100")

LAUNCHER_ASSETS = ["horizon-launcher-linux-x86_64.tar.gz"]
GAME_ASSETS = ["horizon-linux-x86_64.tar.gz", "horizon-server-linux-x86_64.tar.gz"]


class UpdateError(RuntimeError):
    """A safe, user-facing update failure."""


# ---------------------------------------------------------------- selecting releases

def semver(tag: str, prefix: str) -> tuple[int, int, int] | None:
    """(major, minor, patch) of `prefix`X.Y.Z, or None. Date tags such as v2026.10.22 never match."""
    match = re.fullmatch(re.escape(prefix) + r"(\d{1,3})\.(\d+)\.(\d+)", tag)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def nightly_date(tag: str) -> str | None:
    match = re.fullmatch(r"nightly-(\d{4}-\d{2}-\d{2})", tag)
    return match[1] if match else None


def has_assets(release: dict[str, Any], names: list[str]) -> bool:
    available = {a.get("name") for a in release.get("assets", []) if isinstance(a, dict)}
    return all(name in available for name in names)


def published(release: dict[str, Any]) -> bool:
    return release.get("draft") is not True


def pick_launcher(releases: list[dict[str, Any]]) -> dict[str, Any]:
    found = [(semver(r["tag_name"], "launcher@"), r) for r in releases
             if published(r) and r.get("prerelease") is not True and has_assets(r, LAUNCHER_ASSETS)]
    found = [(key, r) for key, r in found if key]
    if not found:
        raise UpdateError("No published launcher@X.Y.Z release with the Linux archive was found")
    return max(found, key=lambda item: item[0])[1]


def pick_release(releases: list[dict[str, Any]]) -> dict[str, Any]:
    """The newest numbered game release (since 2026-10-28 Horizon makes only Nightlies)."""
    found = [(semver(r["tag_name"], "v"), r) for r in releases
             if published(r) and has_assets(r, GAME_ASSETS)]
    found = [(key, r) for key, r in found if key]
    if not found:
        raise UpdateError("No published vX.Y.Z game release with the Linux archives was found")
    return max(found, key=lambda item: item[0])[1]


def pick_nightly(releases: list[dict[str, Any]]) -> dict[str, Any]:
    """The newest dated Nightly (`nightly-YYYY-MM-DD`). The rolling `nightly` release changes in place."""
    found = [(nightly_date(r["tag_name"]), r) for r in releases
             if published(r) and has_assets(r, GAME_ASSETS)]
    found = [(date, r) for date, r in found if date]
    if not found:
        raise UpdateError("No published dated Nightly with the Linux archives was found")
    return max(found, key=lambda item: item[0])[1]


# ---------------------------------------------------------------- checksums and signatures

def parse_sums(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line.strip())
        if match:
            sums[match[2]] = match[1]
    return sums


def sri(hexdigest: str) -> str:
    return "sha256-" + base64.b64encode(bytes.fromhex(hexdigest)).decode()


def signed_names(release: dict[str, Any]) -> list[str]:
    """Version names a release's checksums may be signed for: its tag, the channel, a Nightly's own version."""
    tag = release["tag_name"]
    names = [tag]
    if nightly_date(tag):
        names.append("nightly")
        text = " ".join(str(release.get(key) or "") for key in ("name", "body"))
        commits = set(re.findall(r"\b[0-9a-f]{7,40}\b", text))
        commitish = str(release.get("target_commitish") or "")
        if re.fullmatch(r"[0-9a-f]{7,40}", commitish):
            commits.add(commitish)
        for commit in commits:
            for length in {7, len(commit)}:
                names.append(f"nightly-{tag.removeprefix('nightly-')}-{commit[:length]}")
    return list(dict.fromkeys(names))


def openssl_verify(key: str, message: bytes, signature: bytes) -> bool:
    raw = base64.b64decode(key)
    if len(raw) != 32:
        raise UpdateError("A pinned release key is not a 32-byte Ed25519 public key")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        (directory / "key.der").write_bytes(SPKI_ED25519_PREFIX + raw)
        (directory / "message").write_bytes(message)
        (directory / "signature").write_bytes(signature)
        try:
            result = subprocess.run(
                ["openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-keyform", "DER",
                 "-inkey", str(directory / "key.der"), "-in", str(directory / "message"),
                 "-sigfile", str(directory / "signature")],
                capture_output=True, text=True, check=False)
        except FileNotFoundError as error:
            raise UpdateError("openssl 3 is required to verify Horizon's release signatures") from error
    return result.returncode == 0


def verify_signature(sums: bytes, signatures: list[str], names: list[str], keys: list[str]) -> bool:
    """True when any key signed `horizon release <name>\\n` + SHA256SUMS for any name, in any signature line."""
    for line in signatures:
        line = line.strip()
        if not line:
            continue
        try:
            signature = base64.b64decode(line, validate=True)
        except ValueError:
            continue
        for name in names:
            message = f"horizon release {name}\n".encode() + sums
            if any(openssl_verify(key, message, signature) for key in keys):
                return True
    return False


# ---------------------------------------------------------------- network

def request(url: str, *, api: bool = False) -> urllib.request.Request:
    headers = {"User-Agent": "madebycli/horizon-nix updater"}
    if api:
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return urllib.request.Request(url, headers=headers)


def get(url: str, *, api: bool = False, optional: bool = False) -> bytes | None:
    try:
        with urllib.request.urlopen(request(url, api=api), timeout=90) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if optional and error.code == 404:
            return None
        raise UpdateError(f"Could not read {url}: HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise UpdateError(f"Could not read {url}: {error}") from error


def fetch_releases() -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for page in range(1, 6):
        payload = json.loads(get(f"{API}?per_page=100&page={page}", api=True) or b"[]")
        if not isinstance(payload, list):
            raise UpdateError("The release API returned an unexpected payload")
        releases += [r for r in payload if isinstance(r, dict) and "tag_name" in r]
        if len(payload) < 100:
            break
    return releases


def url_tag(tag: str) -> str:
    return tag.replace("@", "%40")


def pin_from(release: dict[str, Any], assets: list[str], *, verify: bool) -> dict[str, Any]:
    tag = release["tag_name"]
    sums = get(f"{DOWNLOAD}/{url_tag(tag)}/SHA256SUMS")
    if sums is None:
        raise UpdateError(f"{tag} has no SHA256SUMS")
    if verify:
        signatures: list[str] = []
        for name in ("SHA256SUMS.sig", "SHA256SUMS.v2.sig"):
            blob = get(f"{DOWNLOAD}/{url_tag(tag)}/{name}", optional=True)
            if blob:
                signatures += blob.decode().splitlines()
        if not signatures:
            raise UpdateError(f"{tag} carries no SHA256SUMS signature; refusing to pin it")
        if not verify_signature(sums, signatures, signed_names(release), RELEASE_KEYS):
            raise UpdateError(
                f"{tag}: the SHA256SUMS signature does not match Horizon's pinned release key. "
                "If Horizon rotated its key, review crates/horizon-release-sign/release-keys.txt and update RELEASE_KEYS.")
    listed = parse_sums(sums.decode())
    pinned: dict[str, str] = {}
    for name in assets:
        if name not in listed:
            raise UpdateError(f"{tag}: SHA256SUMS does not list {name}")
        pinned[name] = sri(listed[name])
    return {"tag": tag, "version": version_of(tag), "assets": pinned}


def version_of(tag: str) -> str:
    if tag.startswith("launcher@"):
        return tag.split("@", 1)[1]
    return tag[1:] if semver(tag, "v") else tag


def pin_icon(commit: str) -> str:
    data = get(f"https://raw.githubusercontent.com/{REPO}/{commit}/packaging/icons/hicolor/512x512/apps/horizon.png")
    assert data is not None
    return sri(hashlib.sha256(data).hexdigest())


# ---------------------------------------------------------------- main

def load() -> dict[str, Any]:
    return json.loads(RELEASES_FILE.read_text(encoding="utf-8"))


def save(data: dict[str, Any]) -> None:
    RELEASES_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def unpinned(data: dict[str, Any]) -> list[str]:
    missing = [f"{channel}:{name}" for channel in ("launcher", "release", "nightly")
               for name, hash_ in data[channel]["assets"].items() if not hash_]
    return missing + (["icon"] if not data["icon"]["hash"] else [])


def verify_current(data: dict[str, Any], *, allow_unpinned: bool) -> int:
    missing = unpinned(data)
    if missing:
        print(("::warning::" if allow_unpinned else "") + "Not pinned yet: " + ", ".join(missing))
        if not allow_unpinned:
            return 1
    verified = 0
    for channel, assets in (("launcher", LAUNCHER_ASSETS), ("release", GAME_ASSETS), ("nightly", GAME_ASSETS)):
        if any(f"{channel}:{name}" in missing for name in assets):
            continue
        try:
            fresh = pin_from({"tag_name": data[channel]["tag"]}, assets, verify=True)
        except UpdateError as error:
            print(f"{channel}: {error}", file=sys.stderr)
            return 1
        if fresh["assets"] != data[channel]["assets"]:
            print(f"{channel}: the signed SHA256SUMS differ from releases.json", file=sys.stderr)
            return 1
        verified += 1
    print(f"{verified} channel(s) match Horizon's signed checksums." if verified else "Nothing pinned, nothing to verify.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 when anything is stale or unpinned; write nothing")
    parser.add_argument("--verify", action="store_true", help="re-verify the pins already in releases.json")
    parser.add_argument("--allow-unpinned", action="store_true", help="with --verify: unpinned channels are a warning")
    parser.add_argument("--no-verify", action="store_true", help="skip the signature check (unsafe; never in CI)")
    args = parser.parse_args()

    try:
        data = load()
        if args.verify:
            return verify_current(data, allow_unpinned=args.allow_unpinned)
        releases = fetch_releases()
        verify = not args.no_verify
        new = json.loads(json.dumps(data))
        new["launcher"] = pin_from(pick_launcher(releases), LAUNCHER_ASSETS, verify=verify)
        new["release"] = pin_from(pick_release(releases), GAME_ASSETS, verify=verify)
        new["nightly"] = pin_from(pick_nightly(releases), GAME_ASSETS, verify=verify)
        new["icon"]["hash"] = data["icon"]["hash"] or pin_icon(data["icon"]["commit"])
    except (UpdateError, KeyError, json.JSONDecodeError, OSError) as error:
        print(f"update.py: {error}", file=sys.stderr)
        return 2

    for channel in ("launcher", "release", "nightly"):
        print(f"{channel:9} {data[channel]['tag']} -> {new[channel]['tag']}")
    if new == data:
        print("releases.json is current.")
        return 0
    if args.check:
        print("releases.json is stale or unpinned.")
        return 1
    save(new)
    print("releases.json updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
