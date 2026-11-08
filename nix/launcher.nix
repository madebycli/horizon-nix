# The Horizon launcher (official `horizon-launcher-linux-x86_64.tar.gz`) inside a FHS environment.
# The launcher downloads and starts the game itself; those standard Linux binaries only run where
# /lib64 and the usual libraries exist, which is what the FHS environment provides. The launcher
# never replaces itself here: updating is done by this flake (HORIZON_LAUNCHER_NO_SELF_UPDATE).
{ pkgs }:

let
  inherit (pkgs) lib;
  horizon = import ./lib.nix { inherit pkgs; };
  pin = horizon.releases.launcher;

  unwrapped = pkgs.stdenv.mkDerivation {
    pname = "horizon-launcher-unwrapped";
    inherit (pin) version;
    src = horizon.fetchAsset "launcher" "horizon-launcher-linux-x86_64.tar.gz";

    strictDeps = true;
    sourceRoot = ".";
    dontStrip = true;
    dontPatchELF = true; # runs inside the FHS environment with the standard loader

    installPhase = ''
      runHook preInstall
      binary="$(find . -maxdepth 2 -type f -name horizon-launcher | head -n1)"
      if [ -z "$binary" ]; then
        echo "horizon-launcher not found in the release archive; layout changed?" >&2
        find . -maxdepth 3 -print >&2
        exit 1
      fi
      install -Dm755 "$binary" "$out/libexec/horizon-launcher/horizon-launcher"
      runHook postInstall
    '';
  };

  desktopItem = pkgs.makeDesktopItem {
    name = "horizon-launcher";
    desktopName = "Horizon";
    genericName = "Game launcher";
    comment = "Install, prepare and play Horizon, Minecraft: Java Edition rewritten in Rust";
    exec = "horizon-launcher";
    icon = "horizon";
    categories = [ "Game" ];
    startupWMClass = "horizon-launcher";
  };
in
let
  real = pkgs.buildFHSEnv {
  pname = "horizon-launcher";
  inherit (pin) version;

  targetPkgs =
    _:
    horizon.audioLibraries
    ++ horizon.windowingLibraries
    ++ (with pkgs; [
      stdenv.cc.cc.lib
      zlib
      openssl
      cacert
      xdg-utils
      curl
    ]);

  runScript = "${unwrapped}/libexec/horizon-launcher/horizon-launcher";

  profile = ''
    export HORIZON_LAUNCHER_NO_SELF_UPDATE=1
    export SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt
  '';

  extraInstallCommands = ''
    mkdir -p "$out/share/applications"
    cp ${desktopItem}/share/applications/*.desktop "$out/share/applications/"
    ${lib.optionalString (horizon.icon != null) ''
      install -Dm644 ${horizon.icon} "$out/share/icons/hicolor/512x512/apps/horizon.png"
    ''}
  '';

  passthru = { inherit unwrapped; };

  meta = {
    description = "Horizon launcher: installs, prepares and starts Horizon (official binary in a FHS environment)";
    homepage = "https://github.com/horizon-rust/horizon";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "horizon-launcher";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
};
in
if horizon.pinned "launcher" then real else horizon.unpinned "horizon-launcher" "launcher"
