# Yazelix Helix Steel Plugin Defaults

This directory is the packaged source for curated Helix Steel plugin defaults

The initial bundled files come from `mattwparas/helix-config` and are loaded
by downstream Steel config when their corresponding plugin ids are enabled

The plugin repository is declared in `manifest.toml`

The package exposes this directory through the Nix passthru contract field
`yazelixHelixPackageContract.steelPluginRoot`

Downstream projects own their own user-facing settings, startup policy, and
generated `helix.scm` or `init.scm` entrypoints
