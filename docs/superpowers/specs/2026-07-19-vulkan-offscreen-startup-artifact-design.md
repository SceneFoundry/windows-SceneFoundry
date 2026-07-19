# Vulkan Offscreen Startup Artifact Design

## Problem

Vulkan offscreen rendering eventually produces the correct scene, but the first
published 3D image can briefly show a zoomed or distorted blue skybox image.
OpenGL offscreen rendering does not exhibit the artifact.

Existing diagnostics establish that the sampled Vulkan texture, the frame
render target, and the GPU context all use the same `1270x643` extent. The CPU
copy therefore is not scaling or interpreting an old-sized image. The same run
also shows that the device creates a new GPU layer on every frame: layer indices
increase from 0 through 282 instead of restarting for each device frame.

## Goals

- Identify which first Vulkan sample differs from the stable rendered scene.
- Correlate that sample with its Vulkan frame, layer, texture, and global UBO
  resource.
- Correct the underlying initialization or resource-selection error.
- Reset the GPU layer stack once per device frame so layer objects and their
  per-frame textures are reused as designed.
- Preserve OpenGL, DirectX 11, DirectX 12, swap-chain rendering, CPU-buffer
  rendering, and the runtime-adjustable offscreen FPS setting.

## Non-goals

- Do not hide the artifact by permanently dropping a fixed number of samples.
- Do not change skybox orientation or shader coordinate conventions.
- Do not redesign the renderer or frame scheduler.

## Diagnostic Phase

For only the first few Vulkan CPU samples, log a compact image fingerprint and
channel statistics after the readback buffer is mapped. Include the sample
serial, Vulkan frame index, layer index, selected texture, image extent, and
the global UBO resource/frame index used by rendering.

The diagnostics must not change the pixels sent to the GDI+ image target. They
are temporary and will be removed after the runtime test identifies the first
bad sample and the fix is verified.

## Layer Lifecycle Correction

At the beginning of each top-level GPU device frame, reset the device's layer
stack before any context starts a layer. This keeps all contexts in one frame
on the same ordered stack while allowing the next frame to reuse layer 0, layer
1, and so on. Post-frame processing remains unchanged, including the rule that
the main GPU context is called last.

This correction is independent of whether it removes the blue flash. It fixes
the observed unbounded layer-index and source-texture growth without altering
the ordering of layers within a frame.

## Confirmed-Fix Phase

Use the diagnostic run to distinguish among:

1. A first-frame global UBO resource mismatch.
2. A newly created or incorrectly selected layer source texture.
3. A genuinely incomplete first scene render.

Implement the smallest correction at the confirmed boundary. Do not add a
permanent warm-up delay unless evidence proves the renderer intentionally
requires warm-up and no resource initialization error exists.

## Tests

- Add a regression test that requires a device frame to reset the layer stack
  before layers are created.
- Add or extend a focused test for the confirmed first-frame resource mismatch.
- Run the existing Vulkan CPU sampling extent, synchronization, and device-loss
  regression tests.
- Build the Debug x64 Vulkan/graphics3d target from `SceneFoundry.sln`.
- Runtime-test Vulkan offscreen startup and confirm that the first visible 3D
  image is the normal scene with no blue flash, validation error, device loss,
  or increasing layer index.

## Cleanup and Completion

After runtime confirmation, remove the temporary first-frame fingerprint logs
and any remaining crash-only diagnostics that are no longer needed. Commit the
complete validated change set only at the end, as requested.
