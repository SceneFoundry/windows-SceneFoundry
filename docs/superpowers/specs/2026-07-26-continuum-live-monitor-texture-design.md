# Continuum Live Monitor Texture Design

## Context

Continuum renders a virtual desktop monitor in two stages:

1. `main_scene::on_before_render` composites the full-screen ocean wallpaper with the current HelloMultiverse application frame into `m_pgputextureMonitorMultisample`.
2. The multisampled composite is resolved into the single-sample texture `m_pgputextureMonitor2`.

The screen quad is rendered later by `graphics3d::texture_render_system`. That render system samples the texture stored in the quad renderable's `m_ptextureTexture` member.

The resolved monitor texture is currently never assigned to that member. Consequently, the quad does not intentionally sample the completed virtual-monitor image. On OpenGL it can instead display a texture left bound by an earlier pass, which explains why only the ocean wallpaper is visible.

## Goal

Make the quad display the live virtual-monitor composition:

- `ocean.jpg` remains the full-screen monitor wallpaper.
- The current HelloMultiverse frame is projected at its real desktop position and proportional size.
- The quad samples a single-sample texture suitable for a regular `sampler2D`, even when the composition pass uses MSAA.
- The image updates as new HelloMultiverse frames are copied into the existing GPU textures.

## Design

The Continuum scene remains responsible for producing and publishing its monitor texture. The generic texture render system remains responsible only for binding and drawing the texture supplied by a renderable.

After the composition draw completes and the multisampled texture is successfully copied/resolved into `m_pgputextureMonitor2`, `main_scene::on_before_render` will assign that resolved texture to the screen quad's underlying renderable:

```cpp
m_prenderable->renderable()->m_ptextureTexture = m_pgputextureMonitor2;
```

The assignment will be guarded so that both the scene renderable and its underlying renderable must exist. It will occur only after a successful resolve, preventing the quad from being switched to an incomplete monitor frame.

`m_pgputextureMonitor2` is the final single-sample composite. It must be published directly; the multisampled `m_pgputextureMonitorMultisample` must never be assigned to a binding consumed as `sampler2D`.

The same `m_pgputextureMonitor2` object is reused across frames. Each frame updates its pixel contents through the existing resolve operation, so the renderable does not need a newly allocated texture or a separate copy. Reassigning the pointer after each successful resolve is inexpensive and also handles future recreation of the destination texture.

## Frame Flow

For every available HelloMultiverse bitmap frame:

1. Read the application's desktop rectangle and pixels from the bitmap source buffer.
2. Upload or resize `m_pgputextureHelloMultiverse` as needed.
3. Render the ocean wallpaper and HelloMultiverse overlay into `m_pgputextureMonitorMultisample`.
4. Resolve/copy the complete monitor image into `m_pgputextureMonitor2`.
5. Publish `m_pgputextureMonitor2` through the screen quad's `m_ptextureTexture`.
6. Later in the scene render, `texture_render_system` binds that texture and draws the quad.

The existing shader coordinate calculation remains unchanged: the source frame's `x`, `y`, width, and height are normalized against the main monitor dimensions.

## Ownership and Boundaries

- `main_scene` owns the wallpaper/HelloMultiverse composition and knows which scene renderable represents the monitor screen.
- `texture_render_system` stays generic and does not gain Continuum-specific knowledge or MSAA resolve behavior.
- `gpu::context::copy` remains the backend abstraction responsible for the multisample resolve.
- No extra monitor texture or full-screen GPU copy is introduced.

## Error Handling

The renderable texture is published only after `gpu::context::copy` returns successfully. If frame capture, upload, composition, or resolve fails, the previous successfully published texture remains associated with the quad.

Existing exception behavior in `on_before_render` is not expanded by this change.

## Verification

Add a regression contract that verifies:

- the assignment occurs after the resolve/copy;
- the assigned texture is `m_pgputextureMonitor2`;
- `m_pgputextureMonitorMultisample` is not assigned to the quad;
- the assignment is guarded against missing scene/renderable pointers.

Build the affected Continuum target from:

`C:\Users\camilo\SceneFoundry\main\solution-windows\SceneFoundry.sln`

Runtime verification should confirm that the quad shows the ocean wallpaper across its full surface while the HelloMultiverse window updates live at the captured desktop position and proportional dimensions, with MSAA enabled.

## Non-Goals

- Moving the composition logic into `texture_render_system`.
- Adding a second resolved copy of `m_pgputextureMonitor2`.
- Changing the wallpaper/overlay shader, coordinate mapping, or opacity behavior.
- Changing the application-wide MSAA or NanoVG antialiasing policy.
