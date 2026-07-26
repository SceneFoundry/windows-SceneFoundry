# Continuum Monitor Composition Correction Design

## Goal

Correct the Continuum monitor composition so the full main-monitor image is
rendered into the offscreen MSAA target, the HelloMultiverse capture is not
clipped, and the WIC-loaded ocean background is upright without changing the
already-correct capture orientation.

## Established Rendering Contracts

- `imaging_wic` produces the framework's normal CPU pixmap representation.
- `gpu_opengl::texture::write_pixels` remains responsible for CPU-to-OpenGL
  row-orientation conversion.
- MSAA resolve and other GPU-to-GPU copies preserve their source orientation.
- The HelloMultiverse memory-map upload and its top-left monitor-coordinate
  placement remain unchanged.

## Correction

Immediately after beginning the monitor composition render pass, set the
command buffer viewport and scissor to the complete rectangle of
`m_pgputextureMonitorMultisample`. This prevents the pass from inheriting the
smaller Continuum window viewport or scissor, which previously updated only a
fraction of the monitor texture and left clipped or stale regions.

In the monitor composition fragment shader, derive a background-only texture
coordinate whose V component is `1.0 - viewportUv.y`. Use it only for
`backgroundTexture`. Do not change `viewportTopLeftUv`, `overlayTopLeftUv`, or
`overlayUv`, because the HelloMultiverse content is already upright.

Keep the existing resolve into `m_pgputextureMonitor2` and publication through
`prenderableMonitor->m_ptextureTexture` unchanged.

## Files

- `source/app-graphics3d/continuum/main_scene.cpp`
  - Set the monitor-target viewport and scissor.
- `source/app-graphics3d/continuum/opengl/overlay1.frag`
  - Flip only the background sampling V coordinate.
- `source/app-graphics3d/continuum/opengl/overlay1.frag.h`
  - Keep the embedded runtime shader synchronized with the editable shader.
- `source/app-graphics3d/continuum/tests/live_monitor_texture_contract_test.cpp`
  - Guard the focused render-state and shader-orientation contracts.

## Verification

The focused contract must fail before the implementation and pass afterward.
The `app_graphics3d_continuum` Debug/x64 target must build from
`solution-windows/SceneFoundry.sln`. Runtime visual verification should show:

- ocean.jpg upright and stretched across the full monitor quad;
- no quarter-sized fill or middle seam;
- the HelloMultiverse capture upright, fully visible, and proportionally placed.

