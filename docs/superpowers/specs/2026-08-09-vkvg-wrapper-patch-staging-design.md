# VKVG Wrapper Patch Staging Design

## Objective

Maintain SceneFoundry-specific VKVG correctness fixes without requiring write access to the upstream repository, maintaining a personal fork, publishing an unavailable submodule commit, or modifying the checked-out VKVG submodule during a build.

Both the Visual Studio wrapper project and the wrapper CMake project must compile the same generated patched sources. The checked-out `port/graphics3d/vkvg/vkvg` submodule must remain byte-for-byte unchanged by materialization, configuration, compilation, and testing.

## Architecture

The parent `port/graphics3d/vkvg` wrapper owns a patch series and one CMake-script materializer. The materializer receives the pristine VKVG source directory and a build-intermediate output directory. It copies only the affected source files into an output tree that preserves their `src/...` relative paths, validates each unified patch with `git apply --check`, and applies the patches inside that output tree.

The Visual Studio project invokes the materializer before C compilation and replaces only affected `ClCompile` entries with generated files under its intermediate directory. The wrapper CMake project invokes the same materializer through an incremental custom command and replaces the affected entries in `VKVG_SRC` before creating its shared and static targets. Both targets therefore compile identical patched content.

The wrapper permits an explicit CMake executable override for Visual Studio builds and otherwise resolves `cmake` from `PATH`. Git is a required materialization dependency because the patch format and validation use `git apply`.

The wrapper's `.gitmodules` entry does not name a tracking branch. The parent repository's mode-`160000` gitlink is the sole source of truth for the VKVG revision and remains pinned to `65d1eecacbfeb0f7a288896cccb8e1e871ecf6cf`. Consequently, ordinary submodule initialization checks out the reviewed revision. An explicit `git submodule update --remote` can still move the working tree to the remote's default branch tip; it is excluded from the normal build/update procedure, and adopting such a revision requires review followed by an intentional gitlink update.

## Owned Components

The wrapper will own:

- `patches/materialize_vkvg_sources.cmake`: deterministic copy, validation, and patch application.
- A numbered unified patch series under `patches/`, ordered lexically.
- Wrapper-owned contract tests that validate materialization and build-system integration.
- Wrapper-owned rendering regression coverage derived from the useful checks currently present in the modified vendored `tests/offscreen.c`.

Generated files live only in build-intermediate directories and are not source-controlled.

## Production Patch Scope

The initial series preserves these intentional production changes:

1. Clear and push `FULLSCREEN_BIT` state before ordinary indexed draws so pixel-coordinate geometry cannot be interpreted as clip-space geometry.
2. Correct non-zero fill triangulation for both clockwise and counterclockwise paths.
3. Honor a requested supported Vulkan sample count and fall back to `VK_SAMPLE_COUNT_1_BIT` only when the requested count is unsupported.
4. Use conservative external render-pass dependencies and preserve the multisample color attachment through the render pass.

Temporary diagnostics do not enter the production patch series. The modified vendored `tests/offscreen.c` is restored with the rest of the submodule after its reusable clockwise/counterclockwise gradient assertions are represented as wrapper-owned regression coverage.

## Materialization Data Flow

1. The build system supplies absolute input, output, and patch-directory paths.
2. The materializer verifies that every required pristine source and numbered patch exists.
3. It recreates only its dedicated output subtree, never the submodule or a broad workspace path.
4. It copies the affected pristine files while preserving their relative paths.
5. For every patch in lexical order, it runs `git apply --check` in the staged tree.
6. If validation succeeds, it applies that patch to the staged tree.
7. It writes a stamp only after every patch succeeds.
8. The build compiles staged versions of affected files and pristine versions of unaffected files.

The custom-command dependencies include the materializer, every patch, and every affected pristine input. Any of them changing rematerializes the generated sources.

## Failure Behavior

Materialization fails immediately and identifies the patch and staged source tree when:

- CMake or Git cannot be resolved;
- a required input or patch is missing;
- a patch no longer applies cleanly;
- an output file expected by a build target was not produced.

An upstream update that already contains an equivalent fix is intentionally treated as a patch mismatch. Contract-test output will direct maintainers to inspect and remove or refresh the obsolete patch rather than silently accepting an ambiguous partial application.

## Testing Strategy

Testing follows failing-first development:

1. A materialization contract initially fails because no wrapper materializer or patch series exists.
2. The minimal materializer and fullscreen-state patch make the first contract pass.
3. Additional contracts are introduced before adding the remaining production patches.
4. Integration contracts initially fail until `vkvg.vcxproj` and `CMakeLists.txt` consume staged sources.

The completed verification set covers:

- expected failure against an incompatible pristine fixture;
- successful materialization against the pinned VKVG sources;
- unchanged hashes and clean Git status for the VKVG submodule before and after materialization;
- presence of every intended production change in generated files;
- absence of those local modifications from the restored submodule;
- absence of a branch-tracking hint in `.gitmodules` and an exact mode-`160000` gitlink at commit `65d1eecacbfeb0f7a288896cccb8e1e871ecf6cf`;
- Visual Studio references to generated affected sources;
- CMake shared and static targets receiving the same generated affected sources;
- wrapper-owned clockwise and counterclockwise gradient regression coverage;
- Debug x64 MSBuild of VKVG and its consuming draw2d wrapper;
- CMake configure and build when installed Vulkan, FreeType, and related external dependencies permit it;
- existing VKVG, queue-handoff, gradient-lifetime, and path-continuity contracts.

If a full CMake build is blocked by an unavailable external dependency, the standalone CMake materializer and configure-level integration tests remain mandatory, and the exact dependency blocker is reported.

## Update Procedure

When advancing the VKVG submodule:

1. Update the pinned submodule commit without applying local edits.
2. Run the materialization contracts.
3. For each rejected patch, inspect whether upstream incorporated it or changed its surrounding implementation.
4. Remove an incorporated patch or refresh a still-required patch.
5. Run both build-system integrations and rendering regressions.

This procedure keeps SceneFoundry's maintenance surface to a small, reviewable patch series while preserving a clean and replaceable upstream checkout.
