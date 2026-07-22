# NanoVG Font Preview Target Diagnostics Design

## Problem

Normal font previews are generated lazily when their rows first become visible, and the enlarged hover preview is generated lazily on first hover. During that first generation, correctly shaped text appears temporarily at window position `(0,0)`, while the preview's intended list rectangle receives a black cached image. Later draws reuse that cache and do not regenerate the text.

This behavior indicates that the cache-generation draw is reaching two different destinations, or that NanoVG flushes against a different OpenGL context or framebuffer than the one selected for the GPU image. Existing pixel-boundary diagnostics show the rendered cache contents and final sampling rectangle, but do not identify the active WGL context and framebuffer at the deferred NanoVG flush.

## Scope

The change is diagnostic only. It must not alter target selection, synchronization, rendering order, cache invalidation, font rendering, or presentation.

Instrumentation remains inside `draw2d_nanovg` and uses the existing runtime-configurable GPU performance diagnostic setting and generation counter.

## Considered Approaches

1. **Instrument the NanoVG end-frame boundary.** Log the expected graphics/context/image/target identities and actual WGL/OpenGL state immediately before and after target binding. This is the recommended approach because the visible escape can only be diagnosed reliably at the deferred flush boundary.
2. **Instrument every context-lock transition.** This would provide a complete context history, but font enumeration and scrolling would produce excessive output and make the relevant first-preview event difficult to isolate.
3. **Force synchronous or alternate rendering during cache creation.** This might hide the symptom, but it changes behavior before the root cause is established and would not distinguish a context error from a framebuffer error.

## Design

The existing first-eight-event `gpu.performance.nanovg_image_boundary` budget will also govern the new target-state diagnostic.

For each diagnosed GPU-image render boundary, `draw2d_nanovg::graphics::on_end_layer` will capture and report:

- the diagnostic event index;
- `draw2d_nanovg::graphics`, associated image, GPU context, layer, and target texture identities;
- the expected OpenGL render-context handle when available from the Win32 OpenGL context;
- `wglGetCurrentContext()` and `wglGetCurrentDC()`;
- `GL_DRAW_FRAMEBUFFER_BINDING` before target binding;
- the target texture's framebuffer object;
- `GL_DRAW_FRAMEBUFFER_BINDING` after target binding;
- the OpenGL viewport after target binding.

The state line will be emitted immediately before `nvgEndFrame`. The existing render-pixel diagnostic remains after `nvgEndFrame`, allowing both lines to be correlated by diagnostic index and target identity.

The diagnostic will explicitly report whether the current WGL context matches the expected context and whether the post-bind framebuffer matches the target framebuffer. These booleans make the runtime result unambiguous without relying on manual handle comparison.

## Runtime Control

The existing public engine setting remains the only control:

```cpp
pengine->set_gpu_performance_diagnostics(false);
pengine->set_gpu_performance_diagnostics(true);
```

Changing the setting increments the existing diagnostics generation and rearms the first-eight-event budget. The user can therefore rearm immediately before scrolling to uncached rows or performing a first-time hover.

## Error Handling and Noise

Diagnostics are observational and will not throw on a context or framebuffer mismatch. They report the mismatch so the original rendering behavior remains reproducible.

No log is emitted when performance diagnostics are disabled. The existing event cap prevents font scrolling from flooding the log.

## Verification

A contract test will first fail until the target-state diagnostic includes the required context and framebuffer observations, is placed before `nvgEndFrame`, and remains guarded by the runtime diagnostic setting and event budget.

After implementation:

- the focused contract test and existing NanoVG image lifecycle/diagnostic contracts must pass;
- Debug x64 `draw2d_nanovg` must build;
- Debug x64 `shared_app_graphics3d_continuum` must build;
- runtime evidence from one newly visible row and one first-time hover will determine whether the wrong WGL context or wrong framebuffer is active.
