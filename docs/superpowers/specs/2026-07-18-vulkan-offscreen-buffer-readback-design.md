# Vulkan Offscreen Buffer Readback Design

## Problem

Vulkan offscreen rendering finishes successfully, but CPU sampling loses the device when commands write to the host-visible linear destination image. Staged submissions established the following boundaries:

- The empty queue submission succeeds.
- The render-source image transition to `VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL` succeeds.
- The linear destination image transition to `VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL` succeeds.
- `vkCmdClearColorImage` targeting the linear image causes `VK_ERROR_DEVICE_LOST`.
- After removing the redundant clear, `vkCmdCopyImage` targeting the same linear image also causes `VK_ERROR_DEVICE_LOST`.

The queue wrapper, fence completion, and image-transition machinery are therefore not the failing boundary. The shared failing dependency is GPU writes to the host-visible linear image.

## Goal

Replace Vulkan CPU sampling's linear-image readback with a host-visible buffer readback while preserving the existing renderer, queue-wrapper, post-frame, and public CPU-buffer interfaces.

## Architecture

`gpu_vulkan::renderer::cpu_buffer_sampler` will own one host-visible readback buffer per frame index instead of one linear readback texture per frame index. Each buffer will be created with `VK_BUFFER_USAGE_TRANSFER_DST_BIT` and `VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT`, with a capacity of `width * height * 4` bytes.

Sampling will use the existing graphics queue wrapper and managed fence path:

1. Transition the rendered source image to `VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL`.
2. Copy the full color subresource with `vkCmdCopyImageToBuffer` and a tightly packed `VkBufferImageCopy` region.
3. Establish transfer-write to host-read visibility for the destination buffer.
4. Wait for command completion through the existing managed command-buffer fence path.
5. Map the readback buffer and pass its bytes to the existing CPU buffer with a scan of `width * 4`.

The source texture format remains unchanged. The readback buffer contains the same four-byte-per-pixel texel representation that the current image mapping path sends to `set_pixels`.

## Component Boundaries

### CPU Buffer Sampler

- Replace `m_texturea` with a per-frame array of Vulkan buffers.
- Track the allocated size so resize recreates only the affected frame's buffer.
- Keep `sample`, `send_sample`, `clear`, and `destroy` as the sampler's internal lifecycle interface.

### Vulkan Queue and Command Buffers

- Retain `gpu_vulkan::queue` without bypassing it.
- Retain managed fences and synchronous single-time-command completion.
- Keep diagnostic stage annotations during runtime verification: source transition, buffer copy, and host visibility.

### Framework Interface

- Do not change `gpu::renderer::on_end_frame`, `gpu::context::on_end_frame`, device post-frame ordering, or the public CPU-buffer callback path.
- GDI+ continues to consume the same framework CPU buffer.

## Error Handling

- Buffer allocation failures continue through the existing Vulkan/context exception path.
- Check the result of `vkMapMemory` before reading.
- Log failing queue submissions with the existing command annotation.
- Do not retain or fall back to the known device-losing linear-image path.

## Testing

- Extend the focused sampler source test to require `vkCmdCopyImageToBuffer` and reject an active `vkCmdCopyImage` readback call.
- Require transfer-destination, host-visible, and host-coherent buffer creation flags.
- Require the tightly packed `width * 4` CPU scan.
- Run all existing queue, fence-ownership, and CPU-sampling synchronization tests.
- Compile the `gpu_vulkan` Visual Studio target.
- Runtime verification must show successful source transition, buffer copy, host visibility, mapping, and GDI+ display without `VK_ERROR_DEVICE_LOST`.

## Scope Exclusions

- No changes to swap-chain rendering.
- No shader or cubemap changes.
- No asynchronous or multi-frame readback optimization until correctness is verified.
- No removal of the `gpu_vulkan::queue` wrapper.
