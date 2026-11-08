# horizon-server, horizon-engine and horizon-prepare from a server archive
# (`horizon-server-linux-x86_64.tar.gz`), which needs neither ALSA nor udev.
{ pkgs, channel }:

let
  inherit (pkgs) lib;
  horizon = import ./lib.nix { inherit pkgs; };
  pin = horizon.releases.${channel};
in
let
  real = pkgs.stdenv.mkDerivation {
  pname = if channel == "nightly" then "horizon-server-nightly" else "horizon-server";
  version = lib.removePrefix "nightly-" pin.version;
  src = horizon.fetchAsset channel "horizon-server-linux-x86_64.tar.gz";

  strictDeps = true;
  sourceRoot = ".";
  dontStrip = true;

  nativeBuildInputs = [
    pkgs.autoPatchelfHook
    pkgs.makeWrapper
  ];
  buildInputs = [ pkgs.stdenv.cc.cc.lib ];

  installPhase = ''
    runHook preInstall

    root="$(find . -maxdepth 2 -type f -name horizon-server -printf '%h\n' | head -n1)"
    if [ -z "$root" ]; then
      echo "horizon-server not found in the release archive; layout changed?" >&2
      find . -maxdepth 3 -print >&2
      exit 1
    fi

    mkdir -p "$out/libexec/horizon-server" "$out/bin"
    cp -a "$root/." "$out/libexec/horizon-server/"

    for program in horizon-server horizon-prepare; do
      if [ -x "$out/libexec/horizon-server/$program" ]; then
        makeWrapper "$out/libexec/horizon-server/$program" "$out/bin/$program"
      fi
    done
    test -x "$out/bin/horizon-server"

    runHook postInstall
  '';

  meta = {
    description = "Horizon dedicated server (${channel} build, official binaries)";
    homepage = "https://github.com/horizon-rust/horizon";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "horizon-server";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
};
in
if horizon.pinned channel then real else horizon.unpinned (if channel == "nightly" then "horizon-server-nightly" else "horizon-server") channel
