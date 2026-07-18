# Vulkan Cubemap Native Upload Design

## Goal

Correctly upload six-image, non-HDR cubemaps in the Vulkan backend while making the Vulkan face convention explicit and independently testable. The upload must not mutate or clone the source images.

## Root cause

The original Vulkan face order and rotations were correct, but `_assign_cube_map` applied them through high-level `image::rotate(180_degrees)` calls. In the Vulkan execution path, those calls could empty the four rotated source images, leaving only the top and bottom faces visible.

Temporarily removing the rotations made all six faces visible, confirming that the high-level rotation mechanism was the visibility failure. Uploading with the OpenGL row-flip convention then provided the remaining orientation evidence:

- The top and bottom faces appeared vertically flipped.
- The other four faces appeared horizontally flipped.
- The front and back faces were swapped.

This evidence confirms that Vulkan requires the original native face order and transforms, applied directly during the staging copy.

## Design

Add a distinctly named CPU-only helper, `gpu_vulkan::pack_cube_map_for_vulkan`, and keep the complete Vulkan convention inside that helper as an explicit face-rule table.

| Vulkan destination layer | Source face index | Pixel operation |
| --- | ---: | --- |
| Positive X | 0 | Rotate 180 degrees |
| Negative X | 1 | Rotate 180 degrees |
| Positive Y | 3 | Copy unchanged |
| Negative Y | 2 | Copy unchanged |
| Positive Z | 5 | Rotate 180 degrees |
| Negative Z | 4 | Rotate 180 degrees |

The 180-degree rotation will be performed during the copy by reading source rows from bottom to top and pixels within each row from right to left. Unchanged faces will be copied row-for-row. No source pointer or source image will be modified.

`gpu_vulkan::buffer::_assign_cube_map` will only gather the six source pointers and strides and call `pack_cube_map_for_vulkan`. Vulkan buffer mapping, image creation, the six `VkBufferImageCopy` regions, image view creation, and layout transitions remain unchanged.

## Alternatives considered

Changing the skybox sampling direction in shaders could compensate for the visible orientation, but it risks changing HDR and image-based-lighting cubemaps that share sampling conventions.

Six explicit copy blocks in `_assign_cube_map` would make the operations visible but would duplicate staging-copy logic and make the convention harder to test in isolation.

The named helper with a face-rule table keeps the backend-specific convention prominent without spreading it through Vulkan resource-management code.

## Error handling

Existing cubemap validation continues to require exactly six square images with identical dimensions. The helper receives already-validated pointers, dimensions, and strides and does not introduce a second validation policy.

## Testing

A focused regression test will use six synthetic 2x2 faces with unique pixel values and verify:

- Destination layers select source indices `{0, 1, 3, 2, 5, 4}`.
- Positive X, negative X, positive Z, and negative Z are rotated 180 degrees.
- Positive Y and negative Y are copied unchanged.
- Source pixels remain unchanged.

The regression test must be observed failing against the current OpenGL-compatible helper before the production helper is changed, then passing afterward. The `Debug|x64` `shared_app_graphics3d_continuum` target will be rebuilt. Final orientation confirmation remains a visual comparison of the Vulkan and OpenGL scenes.

## Scope

This change affects only six-image, non-HDR cubemap staging in Vulkan. KTX and HDR cubemap paths, shaders, face sampling, and other graphics backends are unchanged.
