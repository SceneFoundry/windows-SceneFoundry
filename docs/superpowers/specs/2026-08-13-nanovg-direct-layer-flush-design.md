# NanoVG Direct Layer Flush Design

## Goal

Ensure `draw2d_nanovg` with `gpu_opengl` flushes queued NanoVG drawing into the active compositor layer texture so `merge_layers` samples the rendered 2D content.

## Root Cause

`graphics::on_end_layer()` resolves the active layer target as `pgputexturesiteTarget`, but then ignores it and obtains the flush texture from `m_pgputexturesiteTarget`. That member is the wrapper cache used by standalone `m_pimage` memory graphics. Because NanoVG submits queued drawing during `nvgEndFrame()`, binding the cached memory-image target at that boundary leaves the active layer texture empty.

## Design

When a GPU layer is active, both the beginning and ending of a NanoVG frame use that layer's current texture. `on_end_layer()` binds `pgputexturesiteTarget->gpu_texture()` immediately before `nvgEndFrame()`. The `m_pgputexturesiteTarget` member remains reserved for standalone memory-image graphics selected by `graphics::current_target_texture()` when `m_pimage` owns a GPU texture.

The compositor architecture remains direct-to-layer:

- Do not restore `layer_end_copy()`.
- Do not add an intermediate texture or framebuffer copy.
- Do not change `merge_layers()`.
- Preserve the existing flush and OpenGL error checks after `nvgEndFrame()`.

## Error Handling

Retain the existing wrong-state exception when the active layer has no current texture. Validate that the resolved texture site also contains a GPU texture before dereferencing it, so a malformed layer target fails at the NanoVG flush boundary rather than silently drawing elsewhere.

## Testing

Add a focused source contract that inspects `graphics::on_end_layer()` and requires the flush texture to come from the locally resolved active layer texture site. The test must fail against the current cached-member lookup and pass after the one-line target correction.

Verification includes:

- Running the focused regression contract.
- Building `draw2d_nanovg` and `gpu_opengl` for Debug x64.
- Running the affected application configuration and confirming the 2D layer textures contain rendered pixels at `merge_layers` and appear composited with the 3D scene.
