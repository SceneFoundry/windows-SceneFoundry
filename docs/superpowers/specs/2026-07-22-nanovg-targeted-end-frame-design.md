# NanoVG Targeted End-Frame Design

## Problem

NanoVG records drawing operations during a layer and performs the OpenGL draw when `nvgEndFrame` flushes the frame. The current `draw2d_nanovg::graphics` lifecycle binds a target during layer startup, but does not guarantee that the same target remains bound when the deferred NanoVG flush occurs.

Font preview diagnostics show that generated GPU image textures remain completely transparent even though their sampling rectangles are valid. The visible hover preview appearing at the window origin is consistent with NanoVG flushing the offscreen preview into a stale or window framebuffer instead of the GPU image texture.

The current lifecycle also calls `nvgEndFrame` twice: once directly in `draw2d_nanovg::graphics::end_layer` and again from `draw2d_nanovg::graphics::on_end_layer`, reached through the generic GPU renderer lifecycle.

## Scope

The correction is confined to `draw2d_nanovg`. It does not change generic `gpu_opengl` target-selection or renderer behavior.

The change must preserve both uses of NanoVG graphics:

- on-screen rendering into the window composition target;
- offscreen rendering into a `gpu::image` texture for later GPU-only sampling.

## Design

`draw2d_nanovg::graphics::on_end_layer` becomes the single owner of the NanoVG frame flush.

At the end of a layer it will:

1. Resolve the current target through `gpu_context()->current_target_texture(pgpulayer)`.
2. Require a valid target and bind it as the OpenGL render target.
3. Call `nvgEndFrame` exactly once, so all deferred NanoVG commands execute against that target.
4. Run the existing rendered GPU-image diagnostic after the NanoVG flush, while the completed target contents are available.
5. Preserve the existing GPU-image fence creation, `glFlush`, OpenGL error checking, and end-layer state update.

`draw2d_nanovg::graphics::end_layer` will no longer call `nvgEndFrame` or diagnose the rendered image directly. It will retain its generic GPU end-layer delegation, which reaches `on_end_layer` at the correct point before renderer submission and presentation.

## Error Handling

If the current target texture cannot be resolved at the flush boundary, the code will fail with an explicit wrong-state exception instead of allowing NanoVG to render into an unspecified framebuffer.

The target bind and NanoVG flush remain under the existing GPU context lock used by the end-layer lifecycle.

## Diagnostics

The runtime-configurable `gpu.performance.nanovg_image_boundary` diagnostic remains available. Its render-side pixel inspection moves to the single flush boundary and therefore observes the texture after NanoVG has completed its deferred drawing.

No new always-on logging is introduced.

## Verification

Contract tests will verify that:

- `nvgEndFrame` is owned only by `on_end_layer` for the active lifecycle;
- the current target is resolved and bound before `nvgEndFrame`;
- rendered-image diagnostics occur after `nvgEndFrame`;
- `end_layer` delegates to the generic GPU lifecycle without performing a second NanoVG flush.

The Debug x64 solution targets for `draw2d_nanovg` and `shared_app_graphics3d_continuum` will be built. Runtime validation will then confirm that normal font previews and the larger hover preview render inside their cached GPU images at their intended list positions, without duplicate content at the window origin.
