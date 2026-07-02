# Yazelix Helix Fork Boundary

This repository currently tracks Helix Steel as a thin fork with
Yazelix-compatible runtime hooks. It must remain usable as a standalone
Steel-enabled Helix project without Yazelix.

Thinness is the current implementation shape, not a long-term constraint. This
fork may grow when reusable editor behavior or defaults are useful outside
Yazelix-managed sessions.

Current fork delta:

- `hx --config-dir <path>` for self-contained managed Helix config lookup
- optional local Helix action bridge, enabled only when
  `YAZELIX_HELIX_BRIDGE=1`
- packaged reusable Steel plugin defaults below
  `share/yazelix_helix/steel_plugins`

The packaged Steel plugin defaults are editor assets. They can be consumed by
Yazelix managed sessions, standalone wrappers, or other downstream packages
without inheriting Yazelix settings semantics.

The bridge is not a general remote-control surface for arbitrary Helix
instances. It is a Yazelix-managed local IPC endpoint used to replace terminal
keystroke injection for editor-owned actions.

Bridge startup requires:

- `YAZELIX_STATE_DIR`
- `YAZELIX_HELIX_BRIDGE_SESSION_ID`
- `YAZELIX_HELIX_BRIDGE_AUTH_TOKEN`

Optional context:

- `YAZELIX_HELIX_BRIDGE_ROOT`
- `YAZELIX_HELIX_BRIDGE_INSTANCE_ID`
- `YAZELIX_HELIX_MANAGED_CONFIG_PATH`
- `ZELLIJ_SESSION_NAME`
- `ZELLIJ_TAB_POSITION`
- `ZELLIJ_PANE_ID`

When enabled, Helix writes bridge registry and token files below
`YAZELIX_HELIX_BRIDGE_ROOT` when it is set, otherwise below
`YAZELIX_STATE_DIR/helix_bridge`:

```text
<bridge_root>/<session_id>/
```

The registry advertises the native local IPC transport for the current
platform: Unix sockets on Unix-like systems and best-effort named pipes on
native Windows.

Supported first-slice actions:

- `helix.get_context`
- `helix.set_cwd`
- `helix.open_directory`
- `helix.open_files`

Zellij remains responsible for panes, tabs, focus, layout, and workspace
routing. The bridge owns only editor-local actions after the target Helix
instance has been selected.

## Packaged Steel Defaults

The package exposes a Nix passthru contract named
`yazelixHelixPackageContract`:

```nix
{
  schemaVersion = 1;
  packageName = "yazelix-helix";
  steelPluginRoot = "share/yazelix_helix/steel_plugins";
  pluginIds = [ "recentf" "splash" "spacemacs_theme" "keymaps" "labelled_buffers" ];
}
```

The contract describes the reusable plugin repository shipped by this fork. It
does not define which plugins Yazelix enables, when startup commands run, or how
user plugin manifests are configured; those remain downstream policy.
