# OpenGL Shared MSAA and NanoVG Design

## Problem

Enabling `m_gpu.m_bMultisample` currently changes generic OpenGL render-target
textures to `GL_TEXTURE_2D_MULTISAMPLE`, but the rest of the rendering pipeline
still treats some of those textures as ordinary `GL_TEXTURE_2D` shader
resources. The new multisample allocations also hard-code four samples instead
of consistently using `m_gpu.m_iSampleCount`.

The failing path renders into a multisampled texture and calls
`gpu_opengl::context::copy` to resolve it. `glBlitFramebuffer` reports
`GL_INVALID_FRAMEBUFFER_OPERATION`, and the currently checked framebuffer
reports `GL_FRAMEBUFFER_INCOMPLETE_MULTISAMPLE`. The copy operation reuses
general render-target framebuffer objects, so unrelated cached depth/stencil
attachments can participate in what should be a color-only resolve.

NanoVG already uses `NVG_ANTIALIAS`, but that flag enables NanoVG's
geometry-fringe antialiasing. It does not allocate a multisampled framebuffer
or choose an MSAA sample count. NanoVG renders into the framebuffer that is
bound when its queued commands are flushed by `nvgEndFrame`.

## Goals

- Use MSAA for Graphics3D offscreen rendering when
  `m_gpu.m_bMultisample` is enabled.
- Render NanoVG into the same multisampled offscreen framebuffer.
- Use `m_gpu.m_iSampleCount` consistently for every attachment in that
  framebuffer.
- Resolve the completed 3D and 2D composition exactly once.
- Expose only a single-sample `GL_TEXTURE_2D` to normal `sampler2D` shaders and
  swap-chain presentation.
- Diagnose framebuffer failures at the point where each framebuffer is
  assembled.

## Non-goals

- Adding `sampler2DMS` support to presentation or NanoVG shaders.
- Maintaining separate multisampled framebuffers for Graphics3D and NanoVG.
- Changing Vulkan or DirectX multisampling behavior.
- Replacing NanoVG's renderer backend.

## Rendering Pipeline

When MSAA is enabled, each composited render target owns two color resources:

1. An MSAA render texture using `GL_TEXTURE_2D_MULTISAMPLE`.
2. A single-sample resolve texture using `GL_TEXTURE_2D`.

The MSAA framebuffer contains:

- the multisampled color texture;
- a `GL_DEPTH24_STENCIL8` renderbuffer with the same dimensions and sample
  count.

The stencil component is required by NanoVG's OpenGL renderer. Graphics3D
renders first. NanoVG then renders while the same MSAA framebuffer remains the
draw framebuffer. `nvgEndFrame` flushes NanoVG commands into that framebuffer.
The color buffer is then resolved into the single-sample texture through
`glBlitFramebuffer` with `GL_NEAREST`.

Only the resolved texture can be bound to ordinary image, composition, and
presentation shaders.

When MSAA is disabled, the existing single-sample render path remains in use
and no resolve is performed.

## Sample-count Source

OpenGL texture and renderbuffer allocation must use one normalized sample
count derived from the application configuration:

- `1` when `m_gpu.m_bMultisample` is false;
- `m_gpu.m_iSampleCount` when multisampling is enabled.

The requested count must be positive and supported for both the color and
depth/stencil formats. Unsupported values should fail during resource creation
with a message containing the requested count and the relevant OpenGL limit,
rather than producing an incomplete framebuffer later.

The normalized sample count belongs in the GPU texture/render-target
description. A Boolean `m_bMultisample` is not sufficient because every
attachment and resolve operation needs the actual count.

## NanoVG Coordination

NanoVG does not receive or own the sample count. Coordination happens through
the framebuffer bound by the application:

1. Bind the shared MSAA framebuffer.
2. Set the viewport to the target size.
3. Clear the stencil buffer at the start of the NanoVG pass.
4. Call `nvgBeginFrame`.
5. Submit NanoVG drawing.
6. Call `nvgEndFrame` before resolving.

`NVG_STENCIL_STROKES` remains enabled. `NVG_DEBUG` remains enabled in the
current debug configuration.

`NVG_ANTIALIAS` may be disabled when MSAA is active because it is redundant
geometry-fringe antialiasing, but this optimization is deferred until the
shared-MSAA path is visually verified. Keeping it enabled initially reduces
the behavioral scope of the fix.

## Resolve Operation

The resolve helper must use framebuffer bindings whose attachments are
unambiguous:

- read framebuffer: MSAA color attachment only;
- draw framebuffer: single-sample color attachment only.

It must not depend on the textures' general render-target framebuffer objects
or their depth/stencil attachments.

Before `glBlitFramebuffer`, the helper checks `GL_READ_FRAMEBUFFER` and
`GL_DRAW_FRAMEBUFFER` separately. A failure reports:

- which side is incomplete;
- framebuffer status;
- color texture target;
- color texture sample count;
- source and destination dimensions.

The resolve uses equal-sized source and destination rectangles and
`GL_NEAREST`, as required for multisample color resolution.

## State and Lifetime

The render target owns both color resources and recreates them together when
its size or normalized sample count changes. Cached framebuffer state must be
invalidated when attachments are reallocated.

The resolve operation preserves and restores the previous read framebuffer,
draw framebuffer, read buffer, and draw buffer bindings. NanoVG rendering and
the resolve execute on the same current OpenGL context.

## Testing

Static contract tests will first demonstrate the current failures:

- multisample allocation is hard-coded instead of using the configured count;
- generic multisample render targets can reach a `sampler2D` presentation path;
- the resolve reuses general render-target framebuffer objects;
- read and draw framebuffer completeness are not checked independently.

After implementation, those contracts must pass.

Runtime verification will cover:

- MSAA disabled;
- 2x and 4x MSAA when supported;
- Graphics3D without NanoVG;
- NanoVG without Graphics3D;
- combined Graphics3D and NanoVG;
- window resize and render-target recreation;
- a frame containing NanoVG stencil-based fills and strokes;
- presentation of the resolved texture without OpenGL errors.

The debug build must report both framebuffer statuses and attachment sample
counts if resolve validation fails.
