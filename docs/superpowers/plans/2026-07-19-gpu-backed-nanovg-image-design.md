# GPU-backed NanoVG image design

Date: 2026-07-19

Status: Approved

## Problem

`draw2d_nanovg::image` currently behaves like a CPU DIB-backed `::image::image`. Drawing one through NanoVG maps the CPU image, converts every pixel to RGBA, creates a temporary NanoVG image, uploads it to OpenGL, draws it, and deletes it. Cached font previews therefore repeat CPU conversion and texture upload whenever they are drawn.

NanoVG already supports wrapping an existing OpenGL texture with `nvglCreateImageFromHandleGL3`. The framework also already has a backend-neutral `gpu::texture` abstraction. A GPU-backed image can therefore remain compatible with APIs that transport `::image::image` while keeping its authoritative storage on the GPU.

Font extent enumeration is a related but distinct performance concern. Extent enumeration creates several measurement graphics contexts, but preview images are generated lazily later by `write_text::text_box::update`. This design removes the CPU transfer path for preview generation and display. It does not by itself eliminate the measurement-context creation cost.

## Goals

- Add a backend-neutral GPU image layer in `bred`.
- Specialize that layer for NanoVG/OpenGL.
- Keep the existing `::image::image` interface available for transporting images through draw2d APIs.
- Make GPU texture storage authoritative for NanoVG-created images.
- Render into the image without rendering directly to the window.
- Draw a GPU-backed NanoVG image without CPU mapping, pixel conversion, or texture upload.
- Preserve the existing CPU-image NanoVG path for ordinary `::image::image` implementations.
- Make unsupported CPU access explicit in phase one.

## Non-goals for phase one

- CPU readback from a GPU image.
- Uploading CPU edits back into a GPU image.
- Vulkan, Direct3D 11, or Direct3D 12 implementations of `gpu::image`.
- Cross-device or cross-share-group image transport.
- Redesigning font extent enumeration or pooling its measurement contexts.
- Persistently caching a NanoVG image identifier for every consuming `NVGcontext`.

## Layered architecture

The inheritance chain is:

```text
::image::image
    -> ::gpu::image
        -> ::draw2d_nanovg::image
```

### `::image::image`

This remains the framework-facing image contract. Existing code such as font preview caches, image sources, and draw2d drawing APIs can continue to store and pass `::image::image` pointers.

Most CPU bitmap operations inherited by a GPU image are not meaningful until mapping is implemented. Phase one must not silently present stale or nonexistent CPU pixels.

### `::gpu::image`

A new `gpu::image` class in `bred` derives virtually from `::image::image` and owns:

- `::pointer<::gpu::texture> m_pgputexture` as the authoritative pixel storage.
- The logical image size through the inherited image metadata.

`gpu::texture` is already a `gpu::context_object`, so it retains the GPU context required for its lifetime. A duplicate context pointer in `gpu::image` is unnecessary unless implementation evidence later shows a separate ownership requirement.

The base class exposes a small backend-neutral texture accessor and common lifecycle behavior. Its phase-one `map()` and `unmap()` overrides throw `::not_implemented()`. This is intentional: a CPU path must fail visibly rather than continue using an uninitialized pixmap.

Texture allocation uses the existing backend-neutral renderer/factory route so the returned concrete texture matches the active GPU backend. Only NanoVG/OpenGL consumes this facility in phase one.

### `::draw2d_nanovg::image`

`draw2d_nanovg::image` changes its direct base from `::image::image` to `::gpu::image`. It owns the NanoVG-specific image graphics facade through the inherited `m_pgraphics` member.

Creating or resizing the image establishes an offscreen NanoVG/OpenGL graphics context and allocates a render-target-capable OpenGL texture of the requested image size. The graphics facade returns the image texture from `current_target_texture`, causing the existing GPU compositor path to bind it as the layer render target.

The image remains offscreen: drawing rectangles, paths, ellipses, and text affects only its texture. No swap-chain presentation is performed.

## Context and sharing model

Phase one keeps the current private memory-graphics context model for an individual image. This avoids mutating the main draw2d context's compositor pointer while an image is being generated and avoids sharing a stateful `NVGcontext` across threads.

All OpenGL contexts are created in the approach's common WGL share group. The texture rendered by an image context is consequently visible to the main NanoVG window context. Framebuffer objects remain local to the producing context; only the underlying texture handle is transported.

This choice optimizes the repeated display path and preserves context isolation. Reducing the number of private contexts is a separate follow-up optimization that can introduce pooling after the GPU image path is stable.

## Creation and rendering flow

1. The image factory returns `draw2d_nanovg::image` as an `::image::image`.
2. `create(size)` rejects an empty size by leaving the image empty, and reuses existing resources when the size is unchanged and valid.
3. For a new size, old image graphics are destroyed before the old texture.
4. The NanoVG memory graphics is created for the requested size and acquires its OpenGL GPU context.
5. A render-target-capable `gpu_opengl::texture` is allocated through the generic renderer texture API and stored in `m_pgputexture`.
6. The graphics facade is associated with the image and returns `m_pgputexture` from `current_target_texture`.
7. Calls made through `image->g()` render NanoVG commands into that texture.
8. End-of-layer processing flushes the producer context and records or defers the existing texture fence so a consuming context can wait only when necessary.

The requested image size is authoritative. The historical 1920x1080 fallback remains only for an empty memory-graphics size and is not used for valid font preview sizes.

## NanoVG GPU drawing fast path

`draw2d_nanovg::graphics::_draw_raw` checks for a GPU-backed NanoVG image before calling `map()`.

For a compatible GPU image it:

1. Validates that the texture exists and is a `gpu_opengl::texture` visible to the current OpenGL share group.
2. Waits for the producer texture fence when the existing synchronization abstraction indicates it is needed.
3. Calls `nvglCreateImageFromHandleGL3` with the OpenGL texture handle, image dimensions, and `NVG_IMAGE_NODELETE`.
4. Applies premultiplied-alpha and vertical-orientation flags required by the offscreen OpenGL render target.
5. Draws the requested source region using the existing NanoVG image-pattern geometry.
6. Deletes the temporary NanoVG wrapper with `nvgDeleteImage`.

`NVG_IMAGE_NODELETE` is essential: deleting the wrapper must not delete the texture owned by `gpu::image`.

The wrapper is intentionally temporary in phase one. It avoids complicated ownership keyed by `NVGcontext` while still avoiding all pixel readback and upload. Wrapper caching can be measured and added later.

If the source is not a compatible GPU image, `_draw_raw` continues through the existing CPU map, conversion, upload, draw, and delete path. Because GPU detection happens first, `gpu::image::map()` is never called during the supported fast path.

## Orientation and alpha

OpenGL framebuffer texture coordinates and draw2d image coordinates use different vertical conventions. The fast path will explicitly apply the NanoVG vertical-flip behavior needed to make the image appear with the same orientation as the CPU-image path.

Draw2d image content is treated as premultiplied alpha. The wrapped NanoVG image uses the corresponding premultiplied flag so antialiased text and translucent shapes blend consistently with existing GUI rendering.

Both decisions require a visual test because an unnecessary flip or an alpha-convention mismatch is immediately visible but may not be caught by structural tests.

## Lifetime and failure behavior

- `draw2d_nanovg::image::destroy()` releases its graphics facade before releasing `m_pgputexture`.
- The texture retains its GPU context through `gpu::context_object` for as long as the texture exists.
- Recreating an image at a different size destroys the old graphics/texture pair before creating the replacement.
- Empty, missing, incompatible-backend, or cross-device textures fail explicitly rather than attempting CPU mapping.
- `map()` and `unmap()` throw `::not_implemented()` in phase one.
- Destruction must occur with the owning OpenGL context selected through the existing context-managed resource lifetime mechanisms.

## Expected performance effect

The expensive per-draw operations removed for GPU-backed NanoVG images are:

- CPU image mapping.
- Per-pixel BGRA/RGBA conversion.
- CPU-side temporary RGBA allocation.
- `nvgCreateImageRGBA` texture upload.
- Deletion and recreation of the actual OpenGL texture on every draw.

The remaining per-draw wrapper creation is metadata-only and does not transfer image pixels.

Font extent enumeration may remain slow because its parallel workers currently create memory graphics contexts for measurement. That path should be profiled independently after this change; likely follow-ups are a bounded context pool or a measurement-specific service.

## Verification

Structural and focused tests should verify:

- `draw2d_nanovg::image` derives from `gpu::image`.
- `gpu::image` owns and exposes a `gpu::texture`.
- Phase-one `map()` and `unmap()` throw `::not_implemented()`.
- The NanoVG fast-path dispatch occurs before the CPU mapping path.
- `NVG_IMAGE_NODELETE` is used when wrapping an OpenGL texture.
- The CPU image fallback remains present.
- Resource destruction order is graphics before texture.

Build verification should include the affected `bred`, `gpu_opengl`, and `draw2d_nanovg` projects and then the user's `SceneFoundry.sln` configuration.

Runtime verification in the continuum application should cover:

- Font previews render with correct text, colors, alpha, and orientation.
- Scrolling the font list does not invoke `gpu::image::map()` or `unmap()`.
- Preview images remain valid across many on-screen frames.
- Resizing or regenerating a preview replaces its texture safely.
- Memory use stabilizes while repeatedly scrolling the font list.
- Existing CPU-backed images still draw through the fallback path.
- Application shutdown produces no OpenGL context or texture-lifetime errors.
