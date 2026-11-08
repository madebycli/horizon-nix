#!/usr/bin/env python3
"""Builds every package from fake archives with the layout Horizon's workflows produce.

The real archives are not needed: each fake one is added to the Nix store under its fixed-output
hash, so fetchurl finds it without the network. This exercises the install phases, the wrappers
and the FHS environment, not Horizon's binaries. Set HORIZON_TEST_NIXPKGS=/path to override nixpkgs.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def add_to_store(path: Path) -> str:
    subprocess.run(["nix-store", "--add-fixed", "sha256", str(path)], check=True, capture_output=True)
    digest = hashlib.sha256(path.read_bytes()).digest()
    return "sha256-" + base64.b64encode(digest).decode()


def make_tar(work: Path, name: str, members: dict[str, Path | str]) -> Path:
    stage = work / ("stage-" + name)
    for member, content in members.items():
        target = stage / member
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path):
            shutil.copy(content, target)
            target.chmod(0o755)
        else:
            target.write_text(content)
    out = work / name
    with tarfile.open(out, "w:gz") as archive:
        for entry in sorted(stage.iterdir()):
            archive.add(entry, arcname=entry.name)
    return out


def main() -> int:
    elf = Path(shutil.which("true")).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        launcher = make_tar(work, "horizon-launcher-linux-x86_64.tar.gz", {"horizon-launcher": elf})
        game = make_tar(work, "horizon-linux-x86_64.tar.gz", {
            "horizon-linux-x86_64/" + name: elf
            for name in ("horizon-client", "horizon-ctl", "horizon-prepare", "horizon-server")
        } | {"horizon-linux-x86_64/exporters/manifest.json": "{}", "horizon-linux-x86_64/PLAY.txt": "play"})
        server = make_tar(work, "horizon-server-linux-x86_64.tar.gz", {
            "horizon-server-linux-x86_64/" + name: elf
            for name in ("horizon-engine", "horizon-prepare", "horizon-server")
        } | {"horizon-server-linux-x86_64/exporters/manifest.json": "{}"})
        icon = work / "horizon.png"
        icon.write_bytes(b"\x89PNG\r\n\x1a\n")

        hashes = {path.name: add_to_store(path) for path in (launcher, game, server, icon)}
        releases = json.loads((ROOT / "releases.json").read_text())
        for channel in ("launcher", "release", "nightly"):
            releases[channel]["assets"] = {name: hashes[name] for name in releases[channel]["assets"]}
        releases["icon"]["hash"] = hashes["horizon.png"]

        repo = work / "repo"
        repo.mkdir()
        for item in ("flake.nix", "flake.lock", "nix"):
            source = ROOT / item
            shutil.copytree(source, repo / item) if source.is_dir() else shutil.copy(source, repo / item)
        (repo / "releases.json").write_text(json.dumps(releases, indent=2))
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

        command = ["nix", "build", "--no-link", "--print-out-paths", "--no-write-lock-file"]
        if os.environ.get("HORIZON_TEST_NIXPKGS"):
            command += ["--override-input", "nixpkgs", "path:" + os.environ["HORIZON_TEST_NIXPKGS"]]
        attrs = ["horizon-launcher", "horizon", "horizon-nightly", "horizon-server", "horizon-server-nightly"]
        result = subprocess.run(command + [f".#{a}" for a in attrs], cwd=repo, capture_output=True, text=True)
        if result.returncode:
            print(result.stderr[-4000:], file=sys.stderr)
            return 1
        outputs = dict(zip(attrs, result.stdout.split()))

        checks = {
            "horizon-launcher": ["bin/horizon-launcher", "share/applications/horizon-launcher.desktop",
                                 "share/icons/hicolor/512x512/apps/horizon.png"],
            "horizon": ["bin/horizon-client", "bin/horizon-ctl", "bin/horizon-prepare", "bin/horizon-server",
                        "libexec/horizon/exporters/manifest.json"],
            "horizon-nightly": ["bin/horizon-client"],
            "horizon-server": ["bin/horizon-server", "bin/horizon-prepare", "libexec/horizon-server/horizon-engine"],
            "horizon-server-nightly": ["bin/horizon-server"],
        }
        failed = False
        for attr, files in checks.items():
            for relative in files:
                if not (Path(outputs[attr]) / relative).exists():
                    print(f"{attr}: missing {relative}", file=sys.stderr)
                    failed = True
        for attr in ("horizon", "horizon-server"):
            run = subprocess.run([str(Path(outputs[attr]) / "bin" / ("horizon-client" if attr == "horizon" else "horizon-server"))])
            if run.returncode:
                print(f"{attr}: wrapped program did not start", file=sys.stderr)
                failed = True
        print("OK" if not failed else "FAILED")
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
