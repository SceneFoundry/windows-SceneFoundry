# GPU Image CPU Mapping Design

## Goal

Restore the normal `::image::image` mapped-buffer contract for GPU-backed
images without adding CPU transfers to their steady-state GPU drawing path.
The first working backend is OpenGL/NanoVG. Vulkan and Direct3D will use the
same backend-neutral interface in later work.

## Motivation

Framework code widely treats an `::image::image` as a CPU-addressable pixmap.
Some paths map the image during setup or loading, edit or inspect its pixels,
and later upload it as a texture or sample it again. Having
`gpu::image::map()` and `unmap()` throw makes a GPU-backed image incompatible
with those established consumers.

Mapping is expected to be infrequent. Most rendering operations remain on the
GPU, so correctness and compatibility are more important than optimizing a
setup-time transfer.

## Architecture

`gpu::texture` owns the backend-specific transfer mechanism. It exposes two
virtual, full-image CPU transfer operations using `::pixmap`: one reads the
texture into a pixmap and one writes a pixmap into the texture. The base
implementations throw `::not_implemented`, so unsupported backends fail
explicitly.

`gpu_opengl::texture` implements both operations. `gpu::image` remains
backend-neutral and uses the texture interface rather than casting to a
specific backend.

`gpu::image` uses its inherited `m_memoryMap` as a lazily allocated staging
buffer. The public `map()` and `unmap()` signatures remain `const`: this
constness describes unchanged logical image identity and content semantics,
while staging allocation, buffer pointers, synchronization, and mapping state
are mutable representation details.

## Mapping Flow

On the first `map()` while the image is unmapped:

1. Validate the GPU texture, its context, and the image dimensions.
2. Synchronously dispatch the operation through `gpu::context::send()`.
3. Wait for the texture producer fence.
4. Allocate or resize `m_memoryMap` and initialize the inherited pixmap over
   that memory.
5. Read the complete texture into the staging pixmap.
6. Convert OpenGL bottom-left row order to the framework's top-left row order.
7. Expose the mapped pixmap pointers and mark the image mapped.

Calling `map()` again while already mapped performs no additional readback.
The staging allocation remains available after unmapping and can be reused by
later mappings.

## Unmapping Flow

On `unmap()` while the image is mapped:

1. Synchronously dispatch the operation through the same GPU context.
2. Convert the top-left staging pixmap to the OpenGL texture's row order.
3. Upload the complete staging buffer to the texture.
4. Publish a texture fence for later GPU consumers.
5. Reset the mapped pixmap view and clear the mapped flag, retaining the
   staging allocation.

Because the existing map API has no read/write access mode, every matching
`unmap()` conservatively uploads the whole buffer. Read-only mappings therefore
perform an unnecessary upload. Explicit access modes can be added later if
profiling shows this setup-time cost matters.

Calling `unmap()` on an unmapped image is a no-op.

## Drawing Interaction

`gpu::image::get_graphics()` unmaps the image before returning its GPU-backed
drawing context, matching ordinary `::image::image` behavior. This guarantees
that CPU edits are visible before GPU drawing resumes.

The existing NanoVG direct shared-texture path remains map-free. It continues
to wait on the producer fence and wrap the OpenGL texture directly, so normal
on-screen drawing does not allocate or transfer CPU pixels.

## OpenGL Transfer Details

Readback uses the texture's framebuffer attachment and `glReadPixels`. Upload
uses the texture object and `glTexSubImage2D`. The implementation handles the
framework's native Windows channel layout with `GL_BGRA` and preserves
premultiplied-alpha values without transforming them.

The implementation preserves and restores every OpenGL state value it changes,
including framebuffer binding, read buffer, texture binding, pack/unpack
alignment, and row length. State is restored on successful and exceptional
paths.

Both transfer operations run only on the texture context's owning task through
`gpu::context::send()`. No caller thread makes the context current directly.

## Failure Behavior

The implementation throws framework exceptions for:

- missing texture or context;
- invalid or mismatched dimensions;
- incomplete framebuffer state;
- failed OpenGL transfers;
- unsupported backend transfer hooks.

An exception must not leave the image marked mapped or leave modified OpenGL
bindings and pixel-store state behind.

## Verification

Source-level contract tests will verify:

- `gpu::image` owns and reuses a staging buffer;
- map and unmap dispatch through the texture context;
- map reads before exposing CPU pixels;
- unmap uploads and fences before clearing mapping state;
- `get_graphics()` unmaps first;
- OpenGL implements readback, orientation conversion, native channel order,
  full-buffer upload, and state restoration;
- the NanoVG fast path still precedes and avoids CPU mapping.

The affected solution targets are `bred`, `gpu_opengl`, `draw2d_nanovg`, and
`shared_app_graphics3d_continuum` in Debug/x64.

Runtime verification will exercise setup-time CPU pixel access followed by GPU
drawing, font previews, direct texture rendering, memory stability, and clean
shutdown. Vulkan and Direct3D transfer implementations are explicitly outside
this phase.
