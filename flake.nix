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

        # Shell
        shellPkgs = with pkgs; [
          zsh
        ];

        # Node.js development
        nodePkgs = with pkgs; [
          nodejs_22 # as per engines in package.json
          corepack # pnpm version managed via corepack
          turbo
          biome
          lefthook
        ];

        # Infrastructure (deploy/)
        # Note: devtunnel not in nixpkgs, install via: brew install --cask devtunnel
        infraPkgs = with pkgs; [
          terraform
          kubectl
          kubernetes-helm
          azure-cli
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
            # Enable corepack for pnpm version management
            corepack enable

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
