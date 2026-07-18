# Vulkan Cubemap OpenGL-Compatible Upload Design

## Goal

Make six-image cubemaps uploaded by the Vulkan backend use the same face order and pixel orientation as the working OpenGL backend. The upload must not mutate or clone the source images.

## Current failure

The Vulkan staging path calls `image::rotate(180_degrees)` for the right, left, front, and back images. Under the Vulkan draw2d backend, that high-level rotation path can empty those four images. Disabling the rotations makes all six faces visible, confirming this boundary as the failure source, but leaves the faces incorrectly oriented.

## Design

`gpu_vulkan::buffer::_assign_cube_map` will pack the mapped staging buffer using the same transformation as `gpu_opengl::texture`:

- Destination face order uses source indices `{0, 1, 3, 2, 4, 5}`.
- Every source face is vertically flipped while copied into its destination layer.
- The source pointer array and source images remain unchanged.
- Existing Vulkan image creation, six `VkBufferImageCopy` regions, image view, and layout transitions remain unchanged.

The implementation will use a small CPU-only packing helper so face selection and vertical row order can be tested without creating Vulkan objects or draw2d images.

## Error handling

The existing cubemap validation continues to require exactly six square images with identical dimensions. The packing helper will receive already-validated pointers, dimensions, and strides, so it does not add a second validation policy.

## Testing

A focused regression test will use six synthetic 2x2 faces with unique pixel values. It will verify:

- Destination faces select source indices `{0, 1, 3, 2, 4, 5}`.
- Rows within every face are vertically reversed.
- Source pixels remain unchanged.

The test will be observed failing before the helper is implemented, then passing afterward. The affected Visual Studio project will be built after implementation. Final visual confirmation remains running `shared_app_graphics3d_continuum` with the Vulkan backend.

## Scope

This change affects only six-image, non-HDR cubemap staging in Vulkan. KTX and HDR cubemap paths, shaders, face sampling, and other graphics backends are unchanged.
