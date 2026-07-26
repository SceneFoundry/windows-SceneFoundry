# Continuum Overlay Vertical Precompensation Design

## Goal

Make the HelloMultiverse capture appear upright and at the same vertical
monitor position as its real desktop window, while preserving its already
correct horizontal orientation and positioning and the upright ocean
background.

## Observed Coordinate Contract

- `overlayTopLeft` and `overlayBottomRight` come from Windows monitor
  coordinates, with Y increasing from the desktop top toward the bottom.
- `viewportUv` in the offscreen composition shader has OpenGL orientation,
  with Y increasing from the render target bottom toward the top.
- `gpu_opengl::texture::write_pixels()` converts CPU pixmaps at the upload
  boundary, so an uploaded image's visual top is sampled at texture V = 1.
- Runtime verification shows that the monitor quad maps the resolved
  composition texture's V = 0 edge to the quad's visual top. The quad
  therefore vertically reverses the offscreen composition.
- The ocean background is already upright because its shader sampling uses
  `1.0 - viewportUv.y`, precompensating for that final quad reversal.
- HelloMultiverse currently uses `1.0 - viewportUv.y` for placement before
  the final reversal. Consequently its vertical position and its pixels are
  both reversed on the quad.

Horizontal sampling and placement are correct and must remain unchanged.

## Focused Correction

Keep the background precompensation unchanged.

For overlay rectangle placement, use the composition coordinate directly:

```glsl
vec2 overlayPlacementUv = viewportUv;
```

Compare `overlayPlacementUv` with the top-origin desktop rectangle uniforms.
This intentionally places a desktop-top overlay at the offscreen target's
bottom so the monitor quad's final vertical reversal moves it back to the
visual top.

Calculate the local overlay coordinate from that same placement coordinate:

```glsl
vec2 overlayLocalUv =
    (overlayPlacementUv - overlayTopLeft) /
    rectangleSize;
```

Retain the uploaded-texture sampling conversion:

```glsl
vec2 overlayUv = vec2(
    overlayLocalUv.x,
    1.0 - overlayLocalUv.y);
```

At the offscreen bottom edge of a desktop-top overlay, this samples the
capture's visual top. The final quad reversal then presents both the capture
and its placement upright.

## Files and Scope

- Modify `source/app-graphics3d/continuum/opengl/overlay1.frag`.
- Modify the synchronized embedded shader
  `source/app-graphics3d/continuum/opengl/overlay1.frag.h`.
- Strengthen
  `source/app-graphics3d/continuum/tests/live_monitor_texture_contract_test.cpp`.

Do not change:

- `continuum/main_scene.cpp` or its monitor-coordinate normalization;
- the HelloMultiverse IPC header or pixel payload;
- WIC decoding or OpenGL pixel upload orientation;
- MSAA composition or resolve;
- `quad2.obj` or the shared texture render system;
- horizontal overlay coordinates;
- background sampling.

## Regression Contract

The focused contract must check both editable and embedded shader forms and
must fail if:

- overlay placement reintroduces `1.0 - viewportUv.y`;
- overlay local coordinates are calculated from a different coordinate;
- overlay texture sampling stops using `1.0 - overlayLocalUv.y`;
- background sampling stops using `1.0 - viewportUv.y`;
- horizontal components are changed.

The contract must be observed failing before the shader correction and
passing afterward.

## Verification

- Compile and run the focused monitor-texture contract.
- Build `app_graphics3d_continuum` Debug/x64 from
  `solution-windows/SceneFoundry.sln`.
- Runtime verification:
  - ocean remains upright and continuous;
  - HelloMultiverse appears upright;
  - moving HelloMultiverse upward moves it upward on the quad;
  - moving it downward moves it downward on the quad;
  - horizontal orientation and positioning remain unchanged.
