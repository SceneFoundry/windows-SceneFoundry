# Vulkan Shader Rebuild Target Design

## Problem

`gpu_vulkan::shader::need_rebuild()` dereferences `m_ptextureTarget`, but the
shader no longer caches a destination texture after the `texture_site`
migration. On-screen Vulkan rendering reaches this method through
`::nok(shader)` after the shader has already been constructed, so the stale
member is null.

## Root cause

Vulkan shaders formerly tracked one render pass through
`m_ptextureTarget` and `m_vkrenderpassCurrent`. Since per-render-pass pipeline
caching was introduced, `shader::_defer_set_current_pipeline()` obtains the
destination texture from the explicit target `texture_site` and selects or
creates the compatible pipeline in `m_mapRenderPassPipeline`.

`need_rebuild()` was not updated when that ownership changed.
`m_vkrenderpassCurrent` is no longer assigned, so restoring the cached target
would also cause `need_rebuild()` to report a rebuild on every later check.

## Approved change

Make `gpu_vulkan::shader::need_rebuild()` return `false`, matching the base
shader behavior. Pipeline compatibility remains the responsibility of the
existing render-pass-keyed pipeline map during `bind()`.

This is intentionally the smallest behavioral correction. Removal of the
obsolete members and override can be considered separately.

## Verification

- Add a focused contract regression test proving that Vulkan
  `need_rebuild()` neither reads `m_ptextureTarget` nor requests reconstruction.
- Run the regression test before and after the production change to establish
  red/green behavior.
- Build `gpu_vulkan` and `shared_app_graphics3d_continuum` from
  `SceneFoundry.sln`.
- Run the on-screen `draw2d_vulkan` plus `gpu_vulkan` configuration and verify
  that presentation proceeds without the null-target failure.
