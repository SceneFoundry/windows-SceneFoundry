# draw2d_nanovg Memory Graphics Design

## Goal

Implement `draw2d_nanovg::graphics::create_memory_graphics` as a true
offscreen NanoVG drawing context. It must support rectangles, paths, ellipses,
text, and the other NanoVG-backed draw2d operations without presenting
directly to a window.

The render target remains GPU-resident. It is not required to be backed by an
`image::image`; copying, sampling, or mapping between the GPU target and an
image can be added separately later.

## Public Behavior

- A non-empty requested size creates an offscreen render target of that exact
  size.
- An empty requested size preserves the historical fallback and creates a
  `1920 x 1080` target.
- Calling `create_memory_graphics` again recreates the offscreen GPU target and
  NanoVG context for the new size.
- Creation does not initialize, use, or present through a swap chain.
- The graphics object is marked ready only after both the GPU context and
  NanoVG context are valid.

## Architecture

The public `create_memory_graphics` method normalizes the size and delegates to
the existing generic graphics lifecycle. NanoVG supplies the backend work
through a new `_create_memory_graphics` override, which is the framework's
intended extension point for memory graphics creation.

The backend hook obtains the OpenGL GPU device associated with the
application's main window. The window is used only to identify and own the GPU
device; the new draw2d context uses `gpu::e_output_gpu_buffer` and therefore
renders to an offscreen GPU target.

The hook then associates the new context with the NanoVG graphics object,
registers the graphics object as its compositor, ensures the renderer and
target exist, selects the new OpenGL context, and creates an `NVGcontext` with
the existing GL3 NanoVG flags.

## Recreation and Ownership

An `NVGcontext` belongs to the OpenGL context that was current when NanoVG
created it. During recreation, the existing NanoVG context must therefore be
deleted while the old GPU context is current. Only after that deletion may the
graphics object replace its GPU context.

If a later creation step fails, `m_pdc` remains null. The new context may be
released normally through the framework's pointer ownership, and the graphics
object must not be marked ready.

The existing user edits that disable the recursive
`opengl_create_offscreen_buffer` and `opengl_delete_offscreen_buffer` members
are preserved. The new implementation does not restore or depend on those
helpers.

## Output Geometry

The offscreen context stores the normalized size and configures the same
GPU-buffer output transform used by the OpenGL draw2d backend: unit X scale,
negative Y scale, and a Y translation equal to the target height. NanoVG frame
dimensions use the offscreen context rectangle, so draw2d coordinates remain
top-left oriented while OpenGL renders into the texture target.

## Error Handling

- Absence of a usable main interaction/window is an invalid framework state
  and raises `error_wrong_state`.
- Failure to obtain or create the GPU context raises `error_wrong_state` or
  propagates the framework creation exception.
- Failure of `nvgCreateGL3` raises `error_failed` with a NanoVG-specific
  message.
- No fallback swap-chain or CPU image allocation is attempted.

## Verification

Add focused source-level regression coverage requiring:

- the `1920 x 1080` empty-size fallback;
- delegation through the generic memory-graphics lifecycle;
- a declared and implemented `_create_memory_graphics` override;
- creation of an `e_output_gpu_buffer` draw2d context;
- old-context NanoVG destruction before GPU-context replacement;
- compositor/context association and fresh `nvgCreateGL3` creation;
- no call to the disabled recursive offscreen helpers.

Build `draw2d_nanovg` for Debug x64. Runtime verification creates memory
graphics, draws representative primitives and text, confirms there is no
direct window presentation, and repeats creation with a different size.
