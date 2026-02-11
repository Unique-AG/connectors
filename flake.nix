{
  description = "Connectors monorepo development environment";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        lib = pkgs.lib;

        # Microsoft Dev Tunnels CLI (not in nixpkgs)
        devtunnel =
          let
            version = "1.0.1516+7e996fe917";
            platform = {
              aarch64-darwin = { name = "osx-arm64";   hash = "sha256-nxfXdt4WnutbOFTmu2Zo6eJ2xD/j4ZhskGSDsoz2pSQ="; };
              x86_64-darwin  = { name = "osx-x64";     hash = "sha256-BLWX1qoxlCs3HN71JPKEf7lUVy9zH11oas3MKYWxdwI="; };
              x86_64-linux   = { name = "linux-x64";   hash = "sha256-mRJ0btEY+ja34i1si4ykJvGt1T0xQlYw/ngIw9AV6Mo="; };
              aarch64-linux  = { name = "linux-arm64"; hash = "sha256-FSVyCu0pIEro0ToCDK8AG5YF4GRABsxQCfiam8HjNRA="; };
            }.${system} or (throw "Unsupported system: ${system}");
          in
          pkgs.stdenv.mkDerivation {
            pname = "devtunnel";
            inherit version;

            src = pkgs.fetchurl {
              url = "https://tunnelsassetsprod.blob.core.windows.net/cli/${version}/${platform.name}-devtunnel";
              hash = platform.hash;
            };

            nativeBuildInputs = lib.optionals pkgs.stdenv.isDarwin [
              pkgs.darwin.sigtool
            ];

            dontUnpack = true;

            installPhase = ''
              mkdir -p $out/bin
              cp $src $out/bin/devtunnel
              chmod 755 $out/bin/devtunnel
            '' + lib.optionalString pkgs.stdenv.isDarwin ''
              codesign --force --sign - $out/bin/devtunnel
            '';

            meta = with lib; {
              description = "Microsoft Dev Tunnels CLI";
              homepage = "https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/";
              license = licenses.unfree;
              platforms = [ "aarch64-darwin" "x86_64-darwin" "x86_64-linux" "aarch64-linux" ];
            };
          };

        # Shell
        shellPkgs = with pkgs; [
          zsh
        ];

        # Node.js development
        # turbo and biome are installed via pnpm (in package.json)
        nodePkgs = with pkgs; [
          nodejs_24 # matches Dockerfiles
          corepack # pnpm version managed via corepack
        ];

        # Infrastructure (deploy/)
        infraPkgs = [
          devtunnel
          pkgs.terraform
          pkgs.kubectl
          pkgs.kubernetes-helm
          pkgs.azure-cli
        ];

        # Utilities
        utilPkgs = with pkgs; [
          jq
          yq-go
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = shellPkgs ++ nodePkgs ++ infraPkgs ++ utilPkgs;

          shellHook = ''
            echo "Connectors dev environment loaded"
            echo "Node.js: $(node --version)"
            echo "pnpm: $(pnpm --version)"

            # Switch to zsh for interactive sessions
            if [[ $- == *i* ]]; then
              export SHELL=${pkgs.zsh}/bin/zsh
              exec $SHELL
            fi
          '';
        };
      }
    );
}
