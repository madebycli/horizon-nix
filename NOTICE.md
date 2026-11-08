# Third-party notices

This repository provides independent Nix packaging for the official Linux binary releases of
[Horizon](https://github.com/horizon-rust/horizon) (Minecraft: Java Edition rewritten in Rust).

- Horizon is developed by the `horizon-rust` project and is released under the MIT licence. It is unofficial and
  contains no Minecraft code or assets: players use their own copy of Minecraft: Java Edition.
- The release archives (`horizon-launcher-linux-x86_64.tar.gz`, `horizon-linux-x86_64.tar.gz`,
  `horizon-server-linux-x86_64.tar.gz`) are downloaded from `https://github.com/horizon-rust/horizon/releases`.
- `scripts/update.py` pins an archive only after the release's `SHA256SUMS` carries a valid Ed25519 signature for
  Horizon's published release key (`crates/horizon-release-sign/release-keys.txt` upstream). The key pinned here is
  `MU4oiIQcCxkZvbwSjjXs7SySCuM6ywRQ3nGaJYZG0gw=`.
- Horizon's own Nightly builds are what its launcher installs by default. The numbered `vX.Y.Z` game releases stopped
  on 2026-10-28; `release` here means the newest of them.
- This repository does not redistribute any archive. Nix downloads the official fixed-output sources from upstream
  and verifies the pinned SHA-256 hashes.

The packaging code in this repository is licensed under GPL-3.0-only (see `LICENSE`). That does not replace or
modify the licences of the upstream binaries.

Packaging in this repository is not maintained or endorsed by the Horizon project.
