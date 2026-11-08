{
  description = "Native Nix packages for Horizon (Minecraft: Java Edition rewritten in Rust): official releases and Nightlies";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      inherit (pkgs) lib;
      horizon = import ./nix/lib.nix { inherit pkgs; };

      packageSet = {
        # The launcher installs and starts the game; it has a single (release) channel.
        horizon-launcher = import ./nix/launcher.nix { inherit pkgs; };
        # Game archive of the latest numbered release (GitHub release) and of the latest Nightly.
        horizon = import ./nix/game.nix { inherit pkgs; channel = "release"; };
        horizon-nightly = import ./nix/game.nix { inherit pkgs; channel = "nightly"; };
        horizon-server = import ./nix/server.nix { inherit pkgs; channel = "release"; };
        horizon-server-nightly = import ./nix/server.nix { inherit pkgs; channel = "nightly"; };
      };
    in
    {
      packages.${system} = packageSet // {
        default = packageSet.horizon-launcher;
      };

      apps.${system} =
        lib.mapAttrs (name: package: {
          type = "app";
          program = lib.getExe package;
        }) packageSet
        // {
          default = self.apps.${system}.horizon-launcher;
        };

      checks.${system} = {
        # Evaluates without network or pins: tags and channel layout stay well formed.
        release-metadata = pkgs.runCommand "horizon-release-metadata" { } ''
          set -euo pipefail
          printf '%s\n' ${lib.escapeShellArg (builtins.toJSON horizon.releases)} \
            | ${lib.getExe pkgs.jq} -e '
                (.launcher.tag | test("^launcher@[0-9]+\\.[0-9]+\\.[0-9]+$"))
                and (.release.tag | test("^v[0-9]+\\.[0-9]+\\.[0-9]+$"))
                and (.nightly.tag | test("^nightly-[0-9]{4}-[0-9]{2}-[0-9]{2}$"))
                and (.release.assets | has("horizon-linux-x86_64.tar.gz") and has("horizon-server-linux-x86_64.tar.gz"))
                and (.nightly.assets | has("horizon-linux-x86_64.tar.gz") and has("horizon-server-linux-x86_64.tar.gz"))
              ' > /dev/null
          touch "$out"
        '';
      }
      # Package builds need the hashes written by scripts/update.py.
      // lib.optionalAttrs horizon.allPinned packageSet;

      overlays.default =
        final: _prev:
        lib.optionalAttrs (final.stdenv.hostPlatform.system == system) (
          lib.mapAttrs (_: _: null) packageSet
          // {
            horizon-launcher = import ./nix/launcher.nix { pkgs = final; };
            horizon = import ./nix/game.nix { pkgs = final; channel = "release"; };
            horizon-nightly = import ./nix/game.nix { pkgs = final; channel = "nightly"; };
            horizon-server = import ./nix/server.nix { pkgs = final; channel = "release"; };
            horizon-server-nightly = import ./nix/server.nix { pkgs = final; channel = "nightly"; };
          }
        );

      nixosModules.default =
        {
          config,
          lib,
          pkgs,
          ...
        }:
        let
          cfg = config.programs.horizon;
          hostSystem = pkgs.stdenv.hostPlatform.system;
          suffix = if cfg.channel == "nightly" then "-nightly" else "";
          packages = self.packages.${system};
        in
        {
          options.programs.horizon = {
            enable = lib.mkEnableOption "Horizon, Minecraft: Java Edition rewritten in Rust";

            channel = lib.mkOption {
              type = lib.types.enum [
                "release"
                "nightly"
              ];
              default = "release";
              description = ''
                Which build the game and server packages come from: the latest numbered GitHub
                release, or the latest Nightly. The launcher has no Nightly channel; it installs
                the game builds it needs by itself.
              '';
            };

            launcher.enable = lib.mkOption {
              type = lib.types.bool;
              default = true;
              description = "Install the Horizon launcher (it downloads and prepares the game itself).";
            };

            game.enable = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Also install the game, horizon-ctl and horizon-prepare from the selected channel, outside the launcher.";
            };

            server.enable = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Install the dedicated server (horizon-server) from the selected channel.";
            };
          };

          config = lib.mkIf cfg.enable {
            assertions = [
              {
                assertion = hostSystem == system;
                message = "Horizon is packaged only for x86_64-linux.";
              }
            ];

            environment.systemPackages = lib.optionals (hostSystem == system) (
              lib.optional cfg.launcher.enable packages.horizon-launcher
              ++ lib.optional cfg.game.enable packages."horizon${suffix}"
              ++ lib.optional cfg.server.enable packages."horizon-server${suffix}"
            );

            # The graphics driver is the host's; the packages only load it.
            hardware.graphics.enable = lib.mkDefault true;
          };
        };

      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [
          git
          jq
          nixfmt
          openssl
          python3
        ];
      };
    };
}
