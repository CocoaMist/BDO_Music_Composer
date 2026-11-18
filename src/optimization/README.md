# Optimization: preview first, write second

This is the optimizer extension contract. The same input must produce the same
preview, and nothing touches the score until the user applies it.

`builtin.py` owns the BDO-safe production optimizer. `plugin_api.py` defines
optimizer API v1, `plugin_loader.py` discovers `.bdoopt` packages without
executing them, and `plugin_host.py` presents built-in and external algorithms
through one preview/apply workflow. `registry.py` remains the compatibility
registry for older in-process integrations.

## `.bdoopt` package

A package is a ZIP archive with this layout:

```text
manifest.json
payload/
  entry.py
resources/       # optional
models/          # optional
README.md        # optional
```

The manifest sets `schema_version` and `api_version` to `1`. It declares
`plugin_id`, `version`, `display_name`, `description`, `entrypoint`,
`intensities`, `scopes`, `capabilities`, and `requires_safe_prepass`.
The `intensities` array contains `conservative`, `balanced`, and `deep`.
The entrypoint uses
`module:function` syntax and returns an object implementing:

```python
class Plugin:
    def analyse(self, request, environment):
        return OptimizationPreview(...)
```

The request contains immutable track/note snapshots, the valid BDO instrument
set, and host limits. Oversized songs are rejected before plugin code runs.
Plugins return structured operations; they never receive the mutable editor
model and never commit edits. The host validates source fingerprints, target
scope, note wire values, supported BDO pitches, canonical drum routing,
derived-track budgets, and the single global-effect-write rule.

Capability names are negotiated against the host-owned allowlist before code
is imported. Unknown or duplicate capabilities disable the bundle. The
negotiated set is exposed through `PluginEnvironment`; it is a compatibility
contract, not a sandbox or permission bypass.

Imported projects can already contain an out-of-map pitch, unsupported manual
articulation, or pre-normalization drum encoding. API v1 treats those values as
bounded source debt: an optimizer may preserve their pitch/type multiset while
cleaning timing or velocity, but may not add another incompatible value. A
track-instrument change and every derived track are validated strictly.
Remaining compatibility issues appear in the timeline validation marks and
the checks that run before export.

Packages are copied to `%LOCALAPPDATA%\BDO Music Composer\optimizer_plugins`.
`BDO_OPTIMIZER_DIR` and `BDO_OPTIMIZER_CACHE` are available for development and
tests. Discovery reads manifests only. Code is imported lazily into the same
process from a SHA-256-keyed cache when analysis begins. Install bundles from
sources you trust. The host provides no dependency installation or sandbox.
`bdo_common.extension_protocol` currently defines the bounded `ndjson-stdio`
framing. An isolated launcher for optimizer bundles is future work.

### Optional Marnian Muse package

Build the package in the independent Marnian Muse project with
`marnian-build-bdoopt path\to\marnian-muse.bdoopt`. Copy the result to the
folder opened by **Algorithm package directory** in the optimizer, refresh
the list, and start analysis explicitly. Its manifest requests the built-in
game-safe prepass and project-wide scope. The host validates the preview,
then applies it only after confirmation. Remove the package and refresh the
list to uninstall it. Keep the corpus, local paths and research outputs in
the independent project.

## Compatibility registry

Existing callers may continue using `register_algorithm()` and
`optimize_tracks(..., algorithm=...)`. New distributable algorithms should use
optimizer API v1 and `.bdoopt` instead.

## Blank-project authoring

`apply_preview` optionally accepts host-owned `note_factory` and `track_factory`
callables. They materialize the first notes/parts of a blank score and allow
fresh tracks without copying a reference's Clips, monitoring state or metadata.
They are not supplied by a plugin and do not bypass preview validation. Existing
callers retain the previous prototype-based behavior.
