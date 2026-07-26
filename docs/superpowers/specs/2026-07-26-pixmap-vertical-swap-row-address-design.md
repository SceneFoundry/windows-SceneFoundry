# Pixmap Vertical-Swap Row Address Correction Design

## Goal

Correct the shared in-place pixmap vertical flip so non-square images and
images with padded row strides are reversed by complete rows without reading
or writing outside their buffers.

## Root Cause

`pixmap_t::vertical_swap()` currently derives the second row pointer with:

```cpp
pdata + (w - 1) * h
```

Here `w` is the stride measured in pixels and `h` is the image height. This
does not address the first pixel of the final row. For a tightly packed
1920-by-1080 image, it starts 840 pixels into the final row and a subsequent
1920-pixel copy overruns the allocation by 840 pixels.

Both `gpu_opengl::texture::write_pixels()` and OpenGL pixel readback use this
shared helper. The invalid row address accounts for shifted image sections,
midpoint or quadrant seams, clipped live content, and possible adjacent-memory
corruption.

## Correction

Keep the shared in-place flip and correct its row addressing at the source.
Treat the scan as a byte stride:

```cpp
auto pline1 = (::u8 *)pdata;
auto pline2 = pline1 + iStride * (h - 1);
```

Swap exactly `width() * sizeof(::image32_t)` bytes per row while advancing the
top pointer by `iStride` and retreating the bottom pointer by `iStride`.

Return without allocating or performing pointer arithmetic when the pixmap
has no data, has a non-positive row width, has fewer than two rows, or has a
stride smaller than the active row width. Padding bytes must remain untouched.

## Scope

- Modify `source/app/acme/graphics/image/pixmap.cpp`.
- Add an executable behavioral regression covering a non-square pixmap with
  padded stride and guard bytes.
- Do not change WIC decoding, OpenGL texture upload orientation, shaders,
  MSAA composition or resolve, or the HelloMultiverse IPC layout.
- Preserve unrelated edits in `source/app/gpu_opengl/texture.cpp` and
  `source/app/gpu_opengl/texture.h`.

## Verification

The behavioral regression must fail against the current implementation
because rows are not reversed correctly and/or guard bytes are changed. It
must pass after the shared helper is corrected.

Build the `app_graphics3d_continuum` Debug/x64 target from
`solution-windows/SceneFoundry.sln`. Runtime verification should then show:

- `ocean.jpg` upright and continuous, without quadrant seams;
- HelloMultiverse fully sampled and proportionally placed;
- no OpenGL framebuffer or multisample errors.

If the capture remains incorrectly placed after removing the proven memory
corruption, investigate the separately observed IPC header distinction
between outer-window dimensions and render-pixmap dimensions.
