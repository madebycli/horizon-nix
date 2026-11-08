# horizon-client, horizon-ctl, horizon-prepare and horizon-server from a game release archive
# (`horizon-linux-x86_64.tar.gz`). Needs the player's own copy of Minecraft: Java Edition for
# `horizon-prepare`; nothing of Mojang's is shipped.
{ pkgs, channel }:

let
  inherit (pkgs) lib;
  horizon = import ./lib.nix { inherit pkgs; };
  pin = horizon.releases.${channel};
  libs = horizon.audioLibraries ++ horizon.windowingLibraries;
in
let
  real = pkgs.stdenv.mkDerivation {
  pname = if channel == "nightly" then "horizon-nightly" else "horizon";
  version = lib.removePrefix "nightly-" pin.version;
  src = horizon.fetchAsset channel "horizon-linux-x86_64.tar.gz";

  strictDeps = true;
  sourceRoot = ".";
  dontStrip = true;

  nativeBuildInputs = [
    pkgs.autoPatchelfHook
    pkgs.makeWrapper
  ];
  buildInputs = [ pkgs.stdenv.cc.cc.lib ] ++ libs;
  # Graphics and windowing libraries are loaded at run time, not linked.
  autoPatchelfIgnoreMissingDeps = true;

  installPhase = ''
    runHook preInstall

    root="$(find . -maxdepth 2 -type f -name horizon-client -printf '%h\n' | head -n1)"
    if [ -z "$root" ]; then
      echo "horizon-client not found in the release archive; layout changed?" >&2
      find . -maxdepth 3 -print >&2
      exit 1
    fi

    mkdir -p "$out/libexec/horizon" "$out/bin"
    cp -a "$root/." "$out/libexec/horizon/"

    for program in horizon-client horizon-ctl horizon-prepare horizon-server; do
      if [ -x "$out/libexec/horizon/$program" ]; then
        makeWrapper "$out/libexec/horizon/$program" "$out/bin/$program" \
          --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath libs}:/run/opengl-driver/lib"
      fi
    done
    test -x "$out/bin/horizon-client"

    runHook postInstall
  '';

  meta = {
    description = "Horizon, Minecraft: Java Edition rewritten in Rust (${channel} build, official binaries)";
    homepage = "https://github.com/horizon-rust/horizon";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "horizon-client";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
};
in
if horizon.pinned channel then real else horizon.unpinned (if channel == "nightly" then "horizon-nightly" else "horizon") channel
