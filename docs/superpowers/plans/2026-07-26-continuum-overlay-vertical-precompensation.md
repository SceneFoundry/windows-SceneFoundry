# Continuum Overlay Vertical Precompensation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display HelloMultiverse upright and at its matching vertical desktop position on the Continuum monitor quad without changing the correct background or horizontal behavior.

**Architecture:** Keep the monitor quad, MSAA resolve, IPC coordinates, and pixel-upload orientation unchanged. Precompensate only overlay placement inside the composition shader by using `viewportUv` directly as the desktop-coordinate comparison domain, while retaining vertical inversion for background and overlay texture sampling.

**Tech Stack:** C++20 contract test, OpenGL 3.3 GLSL, embedded shader header, Visual Studio/MSBuild.

## Global Constraints

- Work directly on `main`, as explicitly authorized by the user.
- Preserve unrelated edits in `source/app/gpu_opengl/texture.cpp` and `source/app/gpu_opengl/texture.h`.
- Preserve existing line endings when practical.
- Use Windows CRLF line endings for modified C++ and GLSL source files.
- Do not change `continuum/main_scene.cpp`, IPC data, WIC decoding, OpenGL pixel upload, MSAA composition or resolve, `quad2.obj`, the shared texture render system, horizontal overlay coordinates, or background sampling.

---

### Task 1: Precompensate Overlay Placement and Sampling

**Files:**
- Modify: `source/app-graphics3d/continuum/tests/live_monitor_texture_contract_test.cpp:124`
- Modify: `source/app-graphics3d/continuum/opengl/overlay1.frag:47`
- Modify: `source/app-graphics3d/continuum/opengl/overlay1.frag.h:52`

**Interfaces:**
- Consumes: `viewportUv`, `overlayTopLeft`, `overlayBottomRight`, and the uploaded `overlayTexture`.
- Produces: `overlayPlacementUv`, a quad-precompensated placement coordinate, and `overlayLocalUv`, the corresponding local sampling coordinate.

- [ ] **Step 1: Extend the focused contract before shader changes**

In the loop that validates both shader representations, retain the exact
`backgroundBlock` assertion and replace the existing overlay-only assertion
with exact declarations and blocks:

```cpp
const std::string overlayPlacementDeclaration =
   "vec2 overlayPlacementUv = viewportUv;";
const std::string insideOverlayBlock =
   "bool insideOverlay =\r\n"
   "        overlayPlacementUv.x >= overlayTopLeft.x &&\r\n"
   "        overlayPlacementUv.y >= overlayTopLeft.y &&\r\n"
   "        overlayPlacementUv.x <= overlayBottomRight.x &&\r\n"
   "        overlayPlacementUv.y <= overlayBottomRight.y;";
const std::string overlayLocalBlock =
   "vec2 overlayLocalUv =\r\n"
   "        (overlayPlacementUv - overlayTopLeft) /\r\n"
   "        rectangleSize;";
const std::string overlaySampleBlock =
   "vec2 overlayUv = vec2(\r\n"
   "        overlayLocalUv.x,\r\n"
   "        1.0 - overlayLocalUv.y);\r\n"
   "\r\n"
   "    vec4 overlayColor =\r\n"
   "        texture(overlayTexture, overlayUv);";
```

Assert every block is present in both `overlay1.frag` and `overlay1.frag.h`.
Also assert `viewportTopLeftUv` and `overlayTopLeftUv` are absent. These
assertions protect direct Y placement, unchanged X placement, local-coordinate
consistency, and the required uploaded-texture V conversion.

- [ ] **Step 2: Run the focused contract and verify RED**

Run from `source/app-graphics3d`:

```powershell
g++ -std=c++20 continuum/tests/live_monitor_texture_contract_test.cpp `
  -o "$env:TEMP\live_monitor_texture_contract_test.exe"
& "$env:TEMP\live_monitor_texture_contract_test.exe"
```

Expected: compilation succeeds and execution fails because
`overlayPlacementUv` and `overlayLocalUv` are absent.

- [ ] **Step 3: Implement the editable shader correction**

In `continuum/opengl/overlay1.frag`, keep `backgroundUv` unchanged and replace
the current viewport conversion with:

```glsl
/*
    The monitor quad vertically reverses this composition texture.
    Use viewportUv directly for desktop placement so a desktop-top
    overlay is written at the offscreen bottom and appears at the
    quad's visual top.
*/
vec2 overlayPlacementUv = viewportUv;
```

Use `overlayPlacementUv.x` and `.y` in all four `insideOverlay` comparisons.
Replace the local-coordinate block with:

```glsl
vec2 overlayLocalUv =
    (overlayPlacementUv - overlayTopLeft) /
    rectangleSize;
```

Keep texture sampling vertically precompensated:

```glsl
vec2 overlayUv = vec2(
    overlayLocalUv.x,
    1.0 - overlayLocalUv.y);
```

- [ ] **Step 4: Synchronize the embedded runtime shader**

Regenerate or edit `continuum/opengl/overlay1.frag.h` so the GLSL body matches
`overlay1.frag` exactly inside the existing raw-string wrapper. Do not change
the wrapper name or delimiter.

- [ ] **Step 5: Normalize modified source line endings**

Ensure the contract test, editable GLSL, and embedded shader header contain
only Windows CRLF line endings and retain UTF-8 without a BOM.

- [ ] **Step 6: Run the focused contract and verify GREEN**

Run the commands from Step 2 again.

Expected: exit code 0.

- [ ] **Step 7: Perform mutation checks**

Temporarily change `overlayPlacementUv = viewportUv` back to a
`1.0 - viewportUv.y` construction in both shader representations and run the
focused contract.

Expected: nonzero exit because the exact direct-placement declaration is
missing.

Restore the direct placement, then temporarily remove
`1.0 - overlayLocalUv.y` from both shader representations and run the
contract.

Expected: nonzero exit because the overlay sampling block is missing.

Restore the approved shader and rerun the contract.

Expected: exit code 0.

- [ ] **Step 8: Build the Continuum application**

Run:

```powershell
& "C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe" `
  solution-windows\SceneFoundry.sln `
  /t:app_graphics3d_continuum `
  /p:Configuration=Debug `
  /p:Platform=x64 `
  /m `
  /nr:false `
  /clp:ErrorsOnly
```

Expected: build succeeds with zero errors.

- [ ] **Step 9: Review and commit the focused change**

Confirm only the contract test and the two shader representations changed in
`source/app-graphics3d`. Confirm the unrelated `source/app/gpu_opengl` edits
remain untouched. Commit the nested implementation and then update the
`source` and root repository pointers without staging unrelated files.
