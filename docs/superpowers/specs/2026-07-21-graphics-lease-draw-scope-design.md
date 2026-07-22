# Graphics Lease and Draw Scope Separation

## Problem

`draw2d_nanovg::graphics::on_acquire_memory_graphics()` currently starts a device frame and GPU layer, and `on_release_memory_graphics()` ends them. This makes returning a pooled resource also end a rendering transaction.

During on-screen OpenGL validation, releasing the first pooled font graphics called `end_layer(true)`. The generic GPU renderer interpreted `true` as the closing window layer, entered the swap-chain presentation path, and called `glDrawBuffer(GL_BACK)` while the offscreen NanoVG WGL context was current. OpenGL correctly reported `GL_INVALID_OPERATION` (1282).

The ownership error is broader than that boolean: a resource lease must not silently own the device frame or decide when presentation occurs.

## Decision

Separate resource ownership from rendering lifecycle.

### Resource lease

`draw2d::graphics_lease` continues to provide exclusive, move-only access to one pooled memory graphics object. Acquiring and releasing it may:

- bind or unbind an image target;
- resize and reset borrower-specific graphics state;
- flush pending backend work;
- fence the bound image texture;
- mark a damaged resource so it is destroyed instead of pooled; and
- return the graphics object to the central pool.

Acquisition and release must not call `start_frame()`, `end_frame()`, `start_layer()`, or `end_layer()`.

### Scoped draw transaction

Add a separate move-only `draw2d::graphics_layer_scope`, created explicitly from a live `graphics_lease`. Its lifetime must be nested inside the lease lifetime.

The scope will:

1. remember the previously current GPU layer;
2. call `graphics::start_layer(false)` when opened;
3. call `graphics::end_layer(false)` when explicitly closed;
4. restore the previously current GPU layer after closing;
5. provide a non-throwing destructor that attempts cleanup and marks the parent lease damaged on failure; and
6. reject a second simultaneous layer scope on the same lease.

It will not start or end the device frame. The containing on-screen window draw remains the frame owner and the only code allowed to close/present that frame.

`graphics_lease::close()` will reject an active layer scope instead of implicitly ending it. This makes incorrect lifetime ordering visible and prevents presentation or rendering work from being hidden in pool return.

## Font-List Data Flow

### Measurement

Font enumeration acquires one measurement `graphics_lease`, selects fonts, and queries extents. It does not open a layer scope because measurement does not produce pixels. The lease is returned after both extent phases.

### Preview rendering

`text_box::update()` performs the following lexical sequence:

1. acquire the image's exclusive `graphics_lease`;
2. open a `graphics_layer_scope` inside that lease;
3. clear the image and draw the font preview;
4. explicitly close the layer scope;
5. explicitly close the graphics lease; and
6. mark the preview cache valid only after both closes succeed.

If drawing throws, scope destruction attempts to end the non-closing layer, restores the previous current layer, and marks the graphics lease damaged. Lease destruction then removes that graphics/context from reuse.

## Alternatives Considered

### Change `end_layer(true)` to `end_layer(false)` during lease release

This avoids the immediate swap-chain branch but preserves the incorrect ownership coupling. Measurement leases would still start GPU frames/layers, and returning a resource would still perform rendering work. Rejected.

### Require callers to issue raw `start_layer()` and `end_layer()` calls

This separates responsibilities but is not exception-safe. A thrown draw operation can leave the current layer and pooled graphics state open. Rejected in favor of an RAII scope with explicit close.

### Use a separate GPU device for every offscreen image

This isolates frame/layer state but recreates the context/thread explosion the pool was introduced to remove. Rejected.

## Scope and Constraints

- This correction covers the current OpenGL/NanoVG font measurement and preview vertical slice.
- The scope always uses `bClosingLayer=false`; it cannot present a swap chain.
- It preserves the existing GPU-only source-image fast path and introduces no CPU mapping.
- It does not redesign the generic GPU compositor or device frame API.
- A future standalone offscreen workflow that has no containing frame will require a separate explicit frame-owner scope; that is not inferred by `graphics_lease`.

## Verification

Source contracts will require:

- NanoVG acquire/release hooks contain no frame/layer lifecycle calls;
- the font measurement path acquires a graphics lease without opening a layer scope;
- the preview path opens and closes a `graphics_layer_scope` before closing its graphics lease;
- the layer scope is move-only, has explicit `close()`, restores the previous GPU layer, and marks the lease damaged on cleanup failure; and
- `graphics_lease::close()` detects an active layer scope.

Build verification will cover `aura`, `bred`, `gpu_opengl`, `draw2d_nanovg`, and `shared_app_graphics3d_continuum` in Debug/x64.

Runtime validation will repeat the on-screen OpenGL/NanoVG font-list scenario and require:

- no OpenGL 1282 at `swap_chain::present()`;
- no swap-chain presentation initiated by preview lease return;
- one measurement graphics/context for enumeration;
- correct preview transparency and colors;
- no CPU mapping or CPU fallback during steady scrolling; and
- responsive font-list scrolling with bounded graphics/context creation.
