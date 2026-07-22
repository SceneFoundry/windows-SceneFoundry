# NanoVG GPU Image Wrapper Cache Design

## Problem

`draw2d_nanovg::graphics::_draw_gpu_image` imports an existing OpenGL texture into NanoVG with `nvglCreateImageFromHandleGL3`, records a deferred NanoVG draw, and immediately calls `nvgDeleteImage` for the imported image identifier.

NanoVG does not execute the recorded draw until `nvgEndFrame`. Deleting the identifier before that flush removes its internal texture record even when `NVG_IMAGE_NODELETE` protects the underlying OpenGL texture. During the later flush, NanoVG can no longer resolve the recorded image identifier and binds its dummy texture. This produces the black font-preview rectangles while the original text render target itself contains correct RGBA pixels.

Creating and deleting an imported NanoVG wrapper for every image draw also causes substantial wrapper churn during font enumeration and scrolling.

## Goals

- Keep every imported NanoVG image identifier valid through the `nvgEndFrame` that consumes it.
- Reuse imported wrappers across frames when the same GPU texture is drawn repeatedly.
- Retain the underlying GPU texture while its NanoVG wrapper is cached.
- Bound wrapper and texture retention so transient images do not accumulate indefinitely.
- Preserve the GPU-only draw path; do not map or sample the image through a CPU buffer.
- Keep all NanoVG and OpenGL cache operations on the owning graphics GPU-context thread.

## Non-Goals

- Changing font enumeration, font rasterization, or preview invalidation policy.
- Adding a global cache shared by multiple `NVGcontext` instances.
- Changing the public `draw2d::graphics` image-drawing interface.
- Implementing CPU map/unmap behavior for GPU images.

## Considered Approaches

### 1. Retain wrappers only until the current `nvgEndFrame`

This is the smallest correctness fix: queue wrappers for deletion and release them immediately after the frame flush. It fixes the black rectangles, but still creates and deletes wrappers for every draw and does not address the measured wrapper churn.

### 2. Use an unbounded persistent wrapper cache

This maximizes reuse and is simple to look up, but a graphics context that sees many transient images would retain all corresponding textures for its lifetime. Font previews and other image-heavy views make that retention unacceptable.

### 3. Use a bounded persistent cache owned by each `draw2d_nanovg::graphics`

This is the selected approach. NanoVG image identifiers belong to one `NVGcontext`, so cache ownership follows the `draw2d_nanovg::graphics` object that owns that context. Entries are reused across frames, retain their GPU textures, and are evicted only after a completed NanoVG flush.

## Architecture

Each `draw2d_nanovg::graphics` instance will own a private cache of imported GPU-image wrappers. The cache is meaningful only while its current `m_pdc` (`NVGcontext`) exists.

Each cache entry contains:

- the unique `gpu::texture` serial;
- the OpenGL texture object identifier;
- the texture width and height;
- the NanoVG image identifier returned by `nvglCreateImageFromHandleGL3`;
- a strong pointer to the GPU texture;
- the last graphics-frame serial in which the entry was used.

The owning graphics object increments a private frame serial when a NanoVG layer begins. Because the cache itself belongs to one `NVGcontext`, the context identity does not need to be repeated in each key.

The lookup key is the tuple `(texture serial, OpenGL texture identifier, width, height)`. The texture serial prevents accidental matches if OpenGL later reuses a numeric object identifier. Including the identifier and dimensions causes a changed or recreated texture backing to receive a new wrapper even if the higher-level texture object remains the same.

## Draw Flow

When `_draw_gpu_image` receives an eligible OpenGL-backed GPU texture:

1. It looks for a matching entry in the owning graphics cache.
2. On a hit, it updates `last-used frame` and queues the draw with the cached NanoVG image identifier.
3. On a miss, it calls `nvglCreateImageFromHandleGL3` with `NVG_IMAGE_NODELETE`, creates a cache entry holding a strong texture pointer, and queues the draw with the new identifier.
4. It does not call `nvgDeleteImage` from `_draw_gpu_image`.

The existing NanoVG mutex and GPU-context-thread discipline continue to protect calls into NanoVG. The path never accesses `image::image` CPU pixels and never invokes map, unmap, upload, or CPU sampling.

## Post-Frame Eviction

Eviction runs only after `nvgEndFrame` has completed. This ordering is a correctness requirement: no wrapper referenced by the just-flushed deferred command stream may be deleted earlier.

The initial bounds are:

- stale-age threshold: 120 completed graphics frames;
- preferred maximum: 512 cached wrappers per graphics instance.

Post-frame maintenance first deletes entries not used during the most recent 120 frames. If more than 512 entries remain, it then deletes least-recently-used entries until the preferred maximum is reached.

An entry used in the frame that was just flushed is never evicted during that frame's maintenance. If a single frame uses more than 512 distinct textures, temporary overflow is allowed instead of invalidating a wrapper still referenced by that frame. Later post-frame maintenance reduces the cache once entries are no longer current-frame users.

Evicting an entry calls `nvgDeleteImage` while the owning `NVGcontext` and OpenGL context are current, then releases the strong GPU texture pointer.

## Context Lifetime

Every path that destroys or replaces `m_pdc` invalidates all cached NanoVG image identifiers.

Before or as part of `nvgDeleteGL3`, the graphics object will discard its cache and release its strong texture references. Individual `nvgDeleteImage` calls are unnecessary when the entire `NVGcontext` is being deleted because NanoVG destroys its own image records. `NVG_IMAGE_NODELETE` ensures this destruction does not delete the externally owned OpenGL textures.

Both the normal `DeleteDC` path and any initialization path that deletes and recreates an existing `m_pdc` must perform this cache reset. A newly created `NVGcontext` always starts with an empty cache and a reset frame serial.

## Failure Handling

If `nvglCreateImageFromHandleGL3` fails, no cache entry is inserted. `_draw_gpu_image` retains its existing failure behavior so callers can follow the established fallback or error path.

Cache eviction and context cleanup operate only with a valid owning context. Context destruction clears cache metadata even if there are no cached entries.

## Diagnostics

The existing runtime-configurable NanoVG GPU performance diagnostics will distinguish:

- imported-wrapper cache hits;
- imported-wrapper cache misses/creations;
- post-frame evictions;
- current cached-wrapper count.

Existing wrapper creation/deletion counters remain meaningful. Successful steady-state scrolling should show hits increasing while wrapper creation and deletion rates fall sharply compared with the current per-draw behavior.

## Testing

Implementation will be test-driven.

Focused contract tests will verify that:

- `_draw_gpu_image` no longer deletes a wrapper before `nvgEndFrame`;
- repeated draws of the same texture reuse one cached wrapper;
- the cache key includes texture serial, OpenGL identifier, and dimensions;
- post-frame eviction is placed after `nvgEndFrame`;
- current-frame entries are protected from eviction;
- both `NVGcontext` destruction/recreation paths clear the cache;
- the GPU-only image path does not introduce CPU mapping or sampling.

Existing NanoVG image lifecycle, diagnostics, and GPU-image boundary contracts must continue to pass. Debug x64 builds of `draw2d_nanovg` and `shared_app_graphics3d_continuum` must succeed.

Runtime validation will confirm:

- normal and hovered font previews contain visible text instead of black rectangles;
- no first-use text escapes to window position `(0,0)`;
- enumeration and scrolling remain responsive;
- diagnostics show cache reuse and bounded entry count.
