# Shared helpers: release pins, asset fetching and the runtime library sets.
{ pkgs }:

let
  inherit (pkgs) lib;
  releases = builtins.fromJSON (builtins.readFile ../releases.json);
  repo = "https://github.com/horizon-rust/horizon";
  urlTag = tag: builtins.replaceStrings [ "@" ] [ "%40" ] tag;
in
rec {
  inherit releases;

  # True when every hash of a channel is filled in by scripts/update.py.
  pinned = channel: lib.all (hash: hash != "") (lib.attrValues releases.${channel}.assets);
  allPinned = lib.all pinned [ "launcher" "release" "nightly" ] && releases.icon.hash != "";

  fetchAsset =
    channel: name:
    let
      pin = releases.${channel};
      hash = pin.assets.${name} or (throw "horizon-nix: ${name} is not listed for the ${channel} channel");
    in
    if hash == "" then
      throw "horizon-nix: ${channel} (${pin.tag}) is not pinned yet. Run `python3 scripts/update.py` (needs openssl) and commit releases.json."
    else
      pkgs.fetchurl {
        url = "${repo}/releases/download/${urlTag pin.tag}/${name}";
        inherit hash;
      };

  # Stands in for a package whose channel is not pinned yet: evaluates, and fails when built or run.
  unpinned =
    name: channel:
    pkgs.runCommand "${name}-unpinned" { meta.mainProgram = name; } ''
      echo "horizon-nix: ${channel} (${releases.${channel}.tag}) is not pinned yet." >&2
      echo "Run \`python3 scripts/update.py\` (needs openssl 3), commit releases.json, or run the 'Update upstream release' workflow." >&2
      exit 1
    '';

  icon =
    if releases.icon.hash == "" then
      null
    else
      pkgs.fetchurl {
        url = "https://raw.githubusercontent.com/horizon-rust/horizon/${releases.icon.commit}/packaging/icons/hicolor/512x512/apps/horizon.png";
        inherit (releases.icon) hash;
      };

  # Libraries the programs link (alsa, udev) or load at run time (graphics, windowing).
  # The graphics driver itself comes from the host (hardware.graphics.enable).
  windowingLibraries = with pkgs; [
    libxkbcommon
    wayland
    libx11
    libxcb
    libxcursor
    libxi
    libxrandr
    libxext
    libxfixes
    libxinerama
    vulkan-loader
    libglvnd
    libdrm
    libgbm
    fontconfig
    freetype
    dbus
  ];
  # What the launcher's "native build" of the game needs on Linux (rust_toolchain.rs `linux_needs`): a C
  # compiler with the C library's headers, pkg-config and the development files of ALSA and libudev.
  # buildFHSEnv puts them at /usr/bin, /usr/include and /usr/lib/pkgconfig (PKG_CONFIG_PATH is set).
  buildTools = with pkgs; [
    gcc
    binutils
    gnumake
    pkg-config
    glibc.dev
    alsa-lib.dev
    systemd.dev
  ];
  audioLibraries = with pkgs; [
    alsa-lib
    systemd
  ];
}
