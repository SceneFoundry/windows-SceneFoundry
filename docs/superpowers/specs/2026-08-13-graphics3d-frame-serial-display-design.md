# Graphics3D Frame Serial Display Design

## Goal

Restore the graphics3d statistics overlay so its displayed frame number comes from the authoritative GPU window-attachment frame serial rather than a view-local counter or rotating frame-resource index.

## Root Cause

`::user::graphics3d::draw_gpu_statistics()` incremented and displayed `m_iFrameCounter`. That counter belongs to the view object and returns to zero when the view is recreated. The GPU window attachment already owns two distinct values:

- `m_iFrameSerial2`, advanced once by `window_attachment::start_frame()` and intended to identify successive frames.
- `m_iCurrentFrame3`, a rotating resource index used to select one of the frames in flight.

The overlay should use the serial. It must never display `m_iCurrentFrame3` as the serial.

Runtime verification exposed a second cause of the apparent reset. The attachment serial advanced monotonically, but the display cycled among the first values drawn into the rotating layer images. A `::draw2d::save_context` could save one `VkvgContext`, switch to a direct composed-layer context, and then restore whichever context was currently active. Because `draw2d_vkvg::graphics::save_graphics_context()` always returned zero and `restore_graphics_context()` looked up the context again, vkvg received an unmatched restore. Its context entered `VKVG_STATUS_INVALID_RESTORE`, after which later drawing into that layer stopped updating.

## Design

`draw_gpu_statistics()` obtains the current `::gpu::window_attachment` through the graphics3d interaction, reads `m_iFrameSerial2`, and formats that value in the existing first statistics line. If the window attachment is temporarily unavailable during startup, the existing `m_iFrameCounter` remains as a fallback so the overlay can still render safely.

`draw2d_vkvg::graphics` also records the exact `VkvgContext` associated with each save token. Restoring a token unwinds recorded saves in reverse order on their originating contexts and truncates the saved-context stack. Switching the active direct layer therefore cannot redirect a restore to another context.

The change does not alter `start_frame()`, `restart_frame_counter()`, `m_iCurrentFrame3`, swap-chain selection, frame-resource selection, or synchronization behavior.

## Verification

- Establish the current failing behavior by confirming the overlay source selects the view-local counter instead of the attachment serial.
- Add a focused regression contract that rejects use of `m_iCurrentFrame3` and requires selection of `m_iFrameSerial2` with the existing fallback.
- Add a focused draw2d_vkvg contract requiring save tokens to retain their originating `VkvgContext`.
- Build and run both focused contracts.
- Build the `bred` and `draw2d_vkvg` targets.
- Run continuum and verify that the displayed value advances from the GPU serial without cycling through the rotating layer images, unmatched vkvg restores, or Vulkan validation errors.

## Scope

The statistics overlay and the draw2d_vkvg save/restore identity bug are in scope. GPU frame lifecycle semantics remain unchanged.
