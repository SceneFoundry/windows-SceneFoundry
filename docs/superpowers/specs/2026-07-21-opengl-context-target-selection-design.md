# OpenGL Context Target Selection Design

## Problem

The OpenGL renderer begins a layer by binding `render_target()->current_texture(pgpulayer)`. For ordinary contexts this is the layer source texture. A graphics compositor can instead override `gpu::context::current_target_texture()`; NanoVG memory graphics uses that override to select the GPU texture owned by the destination `gpu::image`.

Because OpenGL bypasses the context selection when it binds the render target, font-preview commands are written into the temporary layer texture. Layer completion then reads from the compositor-selected image texture, which has not received those commands. Cached drawing therefore samples an untouched image and displays a black rectangle.

## Design

In `gpu_opengl::renderer::_on_begin_render()`, select the color target through `m_pgpucontext->current_target_texture(pgpulayer)` and bind that texture.

The existing fallback in `gpu::context::current_target_texture()` returns `m_pgpurenderer->current_render_target_texture(pgpulayer)`, so ordinary window, 2D, and 3D rendering keeps the current layer-target behavior. When a compositor supplies a target, OpenGL renders directly into that supplied texture. No CPU mapping and no extra GPU copy are introduced.

The rest of the layer lifecycle remains unchanged. Layer completion can fence and expose the destination image through the existing interfaces.

## Error Handling

Target creation and target binding retain their current exception behavior. This change does not add fallback rendering: a missing or invalid compositor texture should continue to fail through the existing texture cast or bind path.

## Verification

Add a source contract that fails while `_on_begin_render()` directly calls `render_target()->current_texture(pgpulayer)` and passes only when it selects `m_pgpucontext->current_target_texture(pgpulayer)`.

Then run the OpenGL target-selection contract, existing graphics-lease and NanoVG image lifecycle contracts, and Debug x64 builds for `gpu_opengl`, `draw2d_nanovg`, and `shared_app_graphics3d_continuum`. Runtime success requires transparent font-preview backgrounds with visible text, no OpenGL 1282 error, GPU-only cached draws, and responsive scrolling.
