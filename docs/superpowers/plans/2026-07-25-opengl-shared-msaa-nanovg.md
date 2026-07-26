# OpenGL Shared MSAA and NanoVG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render OpenGL Graphics3D and NanoVG targets with the application MSAA sample count, then resolve them before ordinary `sampler2D` composition and presentation.

**Architecture:** Every OpenGL multisample texture records its actual sample count and owns a lazily created single-sample resolve texture. NanoVG renders into the currently bound framebuffer, whose color and depth/stencil attachments use the same sample count. OpenGL shader sampler bindings resolve multisample textures at the sampling boundary, and the resolve uses isolated color-only read/draw framebuffers with independent completeness checks.

**Tech Stack:** C++20, OpenGL 3.x/WGL, NanoVG GL3 backend, Visual Studio/MSBuild, dependency-free source contract tests.

## Global Constraints

- Preserve existing user changes in the dirty `source/app` and `source/app-graphics3d` repositories.
- Stage only implementation hunks created by this plan; never stage unrelated existing edits.
- Use Windows CRLF line endings for new and modified C++ source files.
- Keep `NVG_STENCIL_STROKES` enabled.
- Keep `NVG_DEBUG` enabled in the current debug configuration.
- Do not add `sampler2DMS` to presentation, layer composition, or NanoVG shaders.
- A normal shader sampler may receive only a resolved single-sample `GL_TEXTURE_2D`.
- Use `GL_NEAREST` for multisample color resolves.
- Leave Vulkan and DirectX multisampling behavior unchanged.

## File Structure

- Modify `source/app/bred/gpu/texture.h`: store the actual texture sample count.
- Modify `source/app/bred/gpu/render_target.cpp`: propagate the application sample count and request depth/stencil for compositor targets.
- Modify `source/app/gpu_opengl/texture.h`: declare OpenGL MSAA validation, allocation tracking, resolve-texture ownership, and framebuffer invalidation state.
- Modify `source/app/gpu_opengl/texture.cpp`: allocate matching multisample color/depth-stencil storage, invalidate stale attachments, and resolve to a single-sample texture.
- Modify `source/app/gpu_opengl/context.cpp`: implement an isolated, state-preserving color resolve.
- Modify `source/app/gpu_opengl/shader.cpp`: resolve multisampled textures at all ordinary sampler binding paths.
- Create `source/app/gpu_opengl/tests/msaa_resolve_contract_test.cpp`: source-level regression coverage for allocation, framebuffer validation, resolve state, and sampling boundaries.
- Modify `source/app-graphics3d/draw2d_nanovg/draw2d.h`: expose the NanoVG geometry-antialias policy and flag builder.
- Modify `source/app-graphics3d/draw2d_nanovg/draw2d.cpp`: default NanoVG geometry AA to the inverse of application MSAA.
- Modify `source/app-graphics3d/draw2d_nanovg/graphics.cpp`: use the centralized NanoVG flags, ensure a stencil attachment exists, and clear stencil before NanoVG frames.
- Modify `source/app-graphics3d/draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp`: update the existing context-creation contract.
- Create `source/app-graphics3d/draw2d_nanovg/tests/msaa_antialias_contract_test.cpp`: source-level regression coverage for NanoVG flag policy and stencil handling.

---

### Task 1: NanoVG antialias policy

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/draw2d.h`
- Modify: `source/app-graphics3d/draw2d_nanovg/draw2d.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp`
- Create: `source/app-graphics3d/draw2d_nanovg/tests/msaa_antialias_contract_test.cpp`

**Interfaces:**
- Consumes: `application()->m_gpu.m_bMultisample`
- Produces: `bool draw2d::m_bNanoVGGeometryAntialias`
- Produces: `int draw2d::nanovg_create_flags() const`

- [ ] **Step 1: Write the failing NanoVG policy contract**

Create a dependency-free source test that reads `draw2d_nanovg/draw2d.h`,
`draw2d_nanovg/draw2d.cpp`, and `draw2d_nanovg/graphics.cpp`. Its `main`
must assert:

```cpp
assert(header.find("bool m_bNanoVGGeometryAntialias") != std::string::npos);
assert(header.find("int nanovg_create_flags() const;") != std::string::npos);
assert(source.find(
   "m_bNanoVGGeometryAntialias = !m_papplication->m_gpu.m_bMultisample;") !=
   std::string::npos);
assert(graphics.find("int draw2d::nanovg_create_flags() const") !=
   std::string::npos);
assert(graphics.find("NVG_STENCIL_STROKES | NVG_DEBUG") != std::string::npos);
assert(graphics.find(
   "if (m_bNanoVGGeometryAntialias)") != std::string::npos);
assert(graphics.find("iFlags |= NVG_ANTIALIAS;") != std::string::npos);
assert(graphics.find(
   "nvgCreateGL3(::draw2d_nanovg::get()->nanovg_create_flags())") !=
   std::string::npos);
assert(graphics.find(
   "nvgCreateGL3(NVG_ANTIALIAS | NVG_STENCIL_STROKES | NVG_DEBUG)") ==
   std::string::npos);
```

Update `memory_graphics_lifecycle_test.cpp` so `createNanoVg` searches for the
new `nvgCreateGL3(::draw2d_nanovg::get()->nanovg_create_flags())` expression.

- [ ] **Step 2: Run the contracts and verify the new one fails**

Run from `source/app-graphics3d` in a Visual Studio developer shell:

```powershell
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\msaa_antialias_contract_test.cpp /Fe:$env:TEMP\msaa_antialias_contract_test.exe
& $env:TEMP\msaa_antialias_contract_test.exe
```

Expected: compilation succeeds and execution fails on the missing
`m_bNanoVGGeometryAntialias` assertion.

- [ ] **Step 3: Implement the flag and centralized NanoVG creation flags**

Add this public state and method to `draw2d`:

```cpp
bool m_bNanoVGGeometryAntialias = true;

int nanovg_create_flags() const;
```

At the start of `draw2d::initialize`, after the base initialization has made
the application available, set:

```cpp
m_bNanoVGGeometryAntialias =
   !m_papplication->m_gpu.m_bMultisample;
```

Implement the method in `graphics.cpp`, where `_nanovg.h` has already made
the NanoVG GL3 creation flags available:

```cpp
int draw2d::nanovg_create_flags() const
{

   int iFlags = NVG_STENCIL_STROKES | NVG_DEBUG;

   if (m_bNanoVGGeometryAntialias)
   {

      iFlags |= NVG_ANTIALIAS;

   }

   return iFlags;

}
```

Replace both hard-coded `nvgCreateGL3` calls in `graphics.cpp` with:

```cpp
m_pdc = nvgCreateGL3(
   ::draw2d_nanovg::get()->nanovg_create_flags());
```

- [ ] **Step 4: Run the NanoVG contracts**

```powershell
$tests = @(
   'msaa_antialias_contract_test',
   'memory_graphics_lifecycle_test',
   'gpu_image_lifecycle_test',
   'gpu_image_fast_path_test')
foreach ($test in $tests) {
   cl /nologo /std:c++20 /EHsc "draw2d_nanovg\tests\$test.cpp" "/Fe:$env:TEMP\$test.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
   & "$env:TEMP\$test.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Expected: every executable exits `0`.

- [ ] **Step 5: Commit only this task's hunks**

Inspect `git -C source/app-graphics3d diff` before staging. Stage only the new
test and the exact antialias-policy hunks; do not stage pre-existing changes in
the same production files.

```powershell
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d diff --cached --name-only
git -C source/app-graphics3d commit -m "fix: coordinate NanoVG antialias with MSAA"
```

Expected staged paths are limited to the five files listed in this task.

---

### Task 2: Configured OpenGL sample count and matching attachments

**Files:**
- Modify: `source/app/bred/gpu/texture.h`
- Modify: `source/app/bred/gpu/render_target.cpp`
- Modify: `source/app/gpu_opengl/texture.h`
- Modify: `source/app/gpu_opengl/texture.cpp`
- Create: `source/app/gpu_opengl/tests/msaa_resolve_contract_test.cpp`

**Interfaces:**
- Consumes: `m_papplication->m_gpu.m_bMultisample`
- Consumes: `m_papplication->m_gpu.m_iSampleCount`
- Produces: `::i32 gpu::texture::m_iSampleCount`
- Produces: `::i32 gpu_opengl::texture::effective_sample_count() const`
- Produces: `void gpu_opengl::texture::invalidate_framebuffer_attachments()`
- Produces: an OpenGL `initialize_texture` override that reallocates when the
  target, dimensions, or sample count changes

- [ ] **Step 1: Write the failing allocation contract**

Create a dependency-free test that reads `bred/gpu/texture.h`,
`bred/gpu/render_target.cpp`, `gpu_opengl/texture.h`, and
`gpu_opengl/texture.cpp`. Use the same `read_file` and `section` helpers as
`gpu_image_pixel_transfer_contract_test.cpp`. Assert:

```cpp
assert(baseHeader.find("::i32 m_iSampleCount = 1;") != std::string::npos);
assert(glHeader.find("::i32 effective_sample_count() const") !=
   std::string::npos);
assert(glHeader.find("void invalidate_framebuffer_attachments()") !=
   std::string::npos);
assert(glHeader.find("GLenum m_gluAllocatedType = 0;") != std::string::npos);
assert(glHeader.find("::i32_size m_sizeAllocated{-1, -1};") !=
   std::string::npos);
assert(glHeader.find("::i32 m_iAllocatedSampleCount = 0;") !=
   std::string::npos);
assert(renderTarget.find("m_gpu.m_iSampleCount") != std::string::npos);
assert(renderTarget.find("ptexture->m_iSampleCount !=") !=
   std::string::npos);
assert(textureSource.find(
   "glTexImage2DMultisample(GL_TEXTURE_2D_MULTISAMPLE, m_iSampleCount") !=
   std::string::npos);
assert(textureSource.find(
   "glRenderbufferStorageMultisample(GL_RENDERBUFFER, m_iSampleCount") !=
   std::string::npos);
assert(textureSource.find(
   "glTexImage2DMultisample(GL_TEXTURE_2D_MULTISAMPLE, 4") ==
   std::string::npos);
assert(textureSource.find(
   "glRenderbufferStorageMultisample(GL_RENDERBUFFER, 4") ==
   std::string::npos);
assert(textureSource.find("GL_MAX_SAMPLES") != std::string::npos);
assert(textureSource.find("GL_MAX_COLOR_TEXTURE_SAMPLES") !=
   std::string::npos);
```

- [ ] **Step 2: Run the allocation contract and verify it fails**

Run from `source/app`:

```powershell
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\msaa_resolve_contract_test.cpp /Fe:$env:TEMP\msaa_resolve_contract_test.exe
& $env:TEMP\msaa_resolve_contract_test.exe
```

Expected: execution fails on the missing `m_iSampleCount` assertion.

- [ ] **Step 3: Add and propagate the actual sample count**

Add to `gpu::texture`:

```cpp
::i32 m_iSampleCount = 1;
```

In `render_target::initialize_render_target_image`, calculate:

```cpp
auto iRequestedSampleCount =
   m_pgpurenderer->m_pgpucontext->m_papplication->m_gpu.m_bMultisample
      ? m_pgpurenderer->m_pgpucontext->m_papplication->m_gpu.m_iSampleCount
      : 1;

if (m_pgpurenderer->m_pgpucontext->m_papplication->m_gpu.m_bMultisample
   && iRequestedSampleCount < 2)
{

   throw ::exception(
      error_bad_argument,
      "Application MSAA requires a sample count of at least 2.");

}

pgputexture->m_iSampleCount = iRequestedSampleCount;
pgputexture->m_bMultisample =
   m_pgpurenderer->m_pgpucontext->m_papplication->m_gpu.m_bMultisample;
```

Keep the existing texture flags. Additionally request the existing combined
depth/stencil resource for 3D and compositor targets:

```cpp
textureflags.m_bWithDepth =
   escene == ::gpu::e_scene_3d ||
   m_pgpurenderer->m_pgpucontext->m_pgpucompositor != nullptr;
```

In `render_target::texture`, calculate the same requested count before the
existing size check. Call `initialize_render_target_image` when either the
size differs or:

```cpp
ptexture->m_iSampleCount != iRequestedSampleCount
```

This ensures an application MSAA toggle or sample-count change reaches the
OpenGL texture even when the window size is unchanged.

- [ ] **Step 4: Validate and use the sample count in OpenGL allocation**

Implement `effective_sample_count() const` so single-sample textures return `1`.
For a texture explicitly marked multisample without a propagated count, use
the application's configured count. Reject counts less than `2` for an MSAA
texture.

Before allocation, query `GL_MAX_SAMPLES` and
`GL_MAX_COLOR_TEXTURE_SAMPLES`. Throw `error_not_supported` with the requested
count and both limits if the request exceeds either limit.

Replace both hard-coded `4` arguments with `m_iSampleCount`. Keep
`GL_TRUE` fixed sample locations for the color texture.

- [ ] **Step 5: Invalidate stale framebuffer attachments on reallocation**

Add these fields to `gpu_opengl::texture`:

```cpp
GLenum m_gluAllocatedType = 0;
::i32_size m_sizeAllocated{-1, -1};
::i32 m_iAllocatedSampleCount = 0;
```

Implement:

```cpp
void texture::invalidate_framebuffer_attachments()
{

   if (m_gluDepthStencilRBO)
   {

      glDeleteRenderbuffers(1, &m_gluDepthStencilRBO);
      m_gluDepthStencilRBO = 0;

   }

   for (auto & pair : m_mapContextHandleObject)
   {

      pair.element2().m_bBound = false;

   }

}
```

Override `initialize_texture` in `gpu_opengl::texture`. Before delegating to
the base implementation, calculate the desired target, dimensions, and
effective sample count and compare them with the three allocation-tracking
fields. If the base implementation did not recreate a texture whose tracked
allocation differs, call `_create_texture` explicitly and then recreate the
requested depth, render-target, and shader-resource views. This makes an MSAA
toggle or sample-count change effective even when the generic texture
attributes are unchanged.

In `_create_texture`, call `invalidate_framebuffer_attachments()` before
reallocating storage when the dimensions, texture target, or sample count
changed. If the OpenGL texture target changes between `GL_TEXTURE_2D` and
`GL_TEXTURE_2D_MULTISAMPLE`, delete and regenerate the texture name because a
texture object's target is immutable. Update the three tracking fields only
after storage allocation succeeds.

Keep attachment calls in `_defer_bind_to_render_target`; remove the premature
`glFramebufferRenderbuffer` call from `create_depth_resources`. Whenever
`create_depth_resources` creates or reallocates its renderbuffer, mark every
per-context framebuffer object's `m_bBound` false so the next
`frame_buffer_object()` call attaches the new depth/stencil storage.

- [ ] **Step 6: Run the allocation contract**

```powershell
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\msaa_resolve_contract_test.cpp /Fe:$env:TEMP\msaa_resolve_contract_test.exe
& $env:TEMP\msaa_resolve_contract_test.exe
```

Expected: exit `0`.

- [ ] **Step 7: Build the affected core libraries**

```powershell
msbuild bred\bred.vcxproj /m /p:Configuration=Debug /p:Platform=x64
msbuild gpu_opengl\gpu_opengl.vcxproj /m /p:Configuration=Debug /p:Platform=x64
```

Expected: both builds succeed without new warnings from the modified files.

- [ ] **Step 8: Commit only this task's hunks**

Stage the new test and only the sample-count/allocation hunks from dirty
production files.

```powershell
git -C source/app diff --cached --check
git -C source/app diff --cached --name-only
git -C source/app commit -m "fix: allocate matching OpenGL MSAA attachments"
```

Expected staged paths are limited to the five files listed in this task.

---

### Task 3: Isolated color-only framebuffer resolve

**Files:**
- Modify: `source/app/gpu_opengl/context.cpp`
- Modify: `source/app/gpu_opengl/tests/msaa_resolve_contract_test.cpp`

**Interfaces:**
- Consumes: `gpu_opengl::texture::m_gluTextureID`
- Consumes: `gpu_opengl::texture::m_gluType`
- Consumes: `gpu::texture::m_iSampleCount`
- Produces: state-preserving behavior in existing
  `context::copy(gpu::texture *, gpu::texture *, pointer<gpu::fence> *)`

- [ ] **Step 1: Extend the contract for isolated resolve framebuffers**

Add assertions over the `context::copy` section:

```cpp
assert(copy.find("glGenFramebuffers(1, &uReadFramebuffer)") !=
   std::string::npos);
assert(copy.find("glGenFramebuffers(1, &uDrawFramebuffer)") !=
   std::string::npos);
assert(copy.find("GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0") !=
   std::string::npos);
assert(copy.find("GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0") !=
   std::string::npos);
assert(copy.find("glCheckFramebufferStatus(GL_READ_FRAMEBUFFER)") !=
   std::string::npos);
assert(copy.find("glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER)") !=
   std::string::npos);
assert(copy.find("GL_READ_FRAMEBUFFER_BINDING") != std::string::npos);
assert(copy.find("GL_DRAW_FRAMEBUFFER_BINDING") != std::string::npos);
assert(copy.find("GL_READ_BUFFER") != std::string::npos);
assert(copy.find("GL_DRAW_BUFFER") != std::string::npos);
assert(copy.find("GL_COLOR_BUFFER_BIT, GL_NEAREST") != std::string::npos);
assert(copy.find("ptextureSrc->frame_buffer_object()") == std::string::npos);
assert(copy.find("ptextureDst->frame_buffer_object()") == std::string::npos);
```

- [ ] **Step 2: Run the contract and verify the new assertions fail**

```powershell
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\msaa_resolve_contract_test.cpp /Fe:$env:TEMP\msaa_resolve_contract_test.exe
& $env:TEMP\msaa_resolve_contract_test.exe
```

Expected: failure because `context::copy` still reuses the textures'
general-purpose framebuffer objects.

- [ ] **Step 3: Add a scoped framebuffer-blit state guard**

In the anonymous namespace of `context.cpp`, add a guard that captures:

```cpp
GL_READ_FRAMEBUFFER_BINDING
GL_DRAW_FRAMEBUFFER_BINDING
GL_READ_BUFFER
GL_DRAW_BUFFER
```

Its destructor must bind the saved read framebuffer, restore the saved read
buffer, bind the saved draw framebuffer, and restore the saved draw buffer.
The guard must also own and delete the two temporary framebuffer names.

- [ ] **Step 4: Rewrite `context::copy` as a color-only resolve**

Remove the calls to `frame_buffer_object()`. Keep the existing
`beginSingleTimeCommands` and optional `pgpufence` handling unchanged so layer
copy synchronization retains its current ownership and signaling behavior.
Generate one read and one draw framebuffer, attach only:

```cpp
glFramebufferTexture2D(
   GL_READ_FRAMEBUFFER,
   GL_COLOR_ATTACHMENT0,
   ptextureSrc->m_gluType,
   ptextureSrc->m_gluTextureID,
   0);

glFramebufferTexture2D(
   GL_DRAW_FRAMEBUFFER,
   GL_COLOR_ATTACHMENT0,
   ptextureDst->m_gluType,
   ptextureDst->m_gluTextureID,
   0);
```

Set `glReadBuffer(GL_COLOR_ATTACHMENT0)` and
`glDrawBuffer(GL_COLOR_ATTACHMENT0)`. Check read and draw completeness
separately before blitting.

If either side is incomplete, throw an OpenGL wrong-state exception whose
message includes side, framebuffer status text, texture target, sample count,
and dimensions.

When either texture is multisampled, require equal source and destination
dimensions and require the destination sample count to be `1`. Then resolve
with:

```cpp
glBlitFramebuffer(
   0, 0, sizeSrc.cx, sizeSrc.cy,
   0, 0, sizeDst.cx, sizeDst.cy,
   GL_COLOR_BUFFER_BIT,
   GL_NEAREST);
```

- [ ] **Step 5: Run the resolve and existing transfer contracts**

```powershell
$tests = @(
   'msaa_resolve_contract_test',
   'gpu_image_pixel_transfer_contract_test',
   'context_target_selection_contract_test')
foreach ($test in $tests) {
   cl /nologo /std:c++20 /EHsc "gpu_opengl\tests\$test.cpp" "/Fe:$env:TEMP\$test.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
   & "$env:TEMP\$test.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Expected: every executable exits `0`.

- [ ] **Step 6: Build `gpu_opengl`**

```powershell
msbuild gpu_opengl\gpu_opengl.vcxproj /m /p:Configuration=Debug /p:Platform=x64
```

Expected: build succeeds.

- [ ] **Step 7: Commit only the resolve hunks**

```powershell
git -C source/app diff --cached --check
git -C source/app diff --cached --name-only
git -C source/app commit -m "fix: isolate OpenGL multisample resolves"
```

Expected staged paths: `gpu_opengl/context.cpp` and
`gpu_opengl/tests/msaa_resolve_contract_test.cpp`.

---

### Task 4: Resolve before every ordinary shader sample

**Files:**
- Modify: `source/app/gpu_opengl/texture.h`
- Modify: `source/app/gpu_opengl/texture.cpp`
- Modify: `source/app/gpu_opengl/shader.cpp`
- Modify: `source/app/gpu_opengl/tests/msaa_resolve_contract_test.cpp`

**Interfaces:**
- Produces: `gpu_opengl::texture *texture::resolved_texture()`
- Produces: `::pointer<gpu_opengl::texture> texture::m_ptextureResolved`
- Consumes: the corrected `gpu_opengl::context::copy` from Task 3

- [ ] **Step 1: Extend the contract for sampler-boundary resolution**

Add:

```cpp
assert(glHeader.find(
   "::pointer < ::gpu_opengl::texture > m_ptextureResolved;") !=
   std::string::npos);
assert(glHeader.find("texture * resolved_texture();") != std::string::npos);

const auto resolveTexture = section(
   textureSource,
   "texture * texture::resolved_texture()",
   "void texture::create_depth_resources()");
assert(resolveTexture.find("if (m_iSampleCount <= 1)") != std::string::npos);
assert(resolveTexture.find("m_ptextureResolved") != std::string::npos);
assert(resolveTexture.find("m_bMultisample = false;") != std::string::npos);
assert(resolveTexture.find("m_iSampleCount = 1;") != std::string::npos);
assert(resolveTexture.find("copy(") != std::string::npos);

assert(shaderSource.find("ptexture = ptexture->resolved_texture();") !=
   std::string::npos);
assert(shaderSource.find(
   "glBindTexture(GL_TEXTURE_2D, ptexture->m_gluTextureID)") !=
   std::string::npos);
```

Also assert that the resolution call appears in all three ordinary texture
paths: `bind_source`, `bind_source2`, and the texture branch of
`bind_slot_set`.

- [ ] **Step 2: Run the contract and verify failure**

```powershell
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\msaa_resolve_contract_test.cpp /Fe:$env:TEMP\msaa_resolve_contract_test.exe
& $env:TEMP\msaa_resolve_contract_test.exe
```

Expected: failure on the missing `resolved_texture` declaration.

- [ ] **Step 3: Implement lazy single-sample resolve ownership**

Add the resolve pointer and method to `gpu_opengl::texture`. The method returns
`this` when `m_iSampleCount <= 1`. Otherwise it:

1. Constructs `m_ptextureResolved` if needed.
2. Reinitializes it when its size differs from the multisample source.
3. Sets `m_bMultisample = false` and `m_iSampleCount = 1` before
   initialization.
4. Uses texture flags with render-target, shader-resource, transfer-source,
   and transfer-target enabled, but depth disabled.
5. Calls the OpenGL context's corrected method exactly as
   `pcontext->copy(m_ptextureResolved, this, nullptr)`.
6. Returns the single-sample texture.

The method must reject recursive resolution if called on
`m_ptextureResolved`.

- [ ] **Step 4: Resolve at all ordinary OpenGL sampler bindings**

In `shader::bind_source`, `shader::bind_source2`, and the texture branch of
`shader::bind_slot_set`, cast the supplied texture and immediately call:

```cpp
ptexture = ptexture->resolved_texture();
```

Then bind:

```cpp
glBindTexture(GL_TEXTURE_2D, ptexture->m_gluTextureID);
```

Assert or throw if the returned texture target is not `GL_TEXTURE_2D`. This
keeps layer composition and swap-chain presentation unchanged while ensuring
their existing `sampler2D` uniforms never receive a multisample texture.

- [ ] **Step 5: Run all OpenGL source contracts**

```powershell
$tests = Get-ChildItem gpu_opengl\tests\*_test.cpp
foreach ($test in $tests) {
   $name = [System.IO.Path]::GetFileNameWithoutExtension($test.Name)
   cl /nologo /std:c++20 /EHsc $test.FullName "/Fe:$env:TEMP\$name.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
   & "$env:TEMP\$name.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Expected: every executable exits `0`.

- [ ] **Step 6: Build `bred` and `gpu_opengl`**

```powershell
msbuild bred\bred.vcxproj /m /p:Configuration=Debug /p:Platform=x64
msbuild gpu_opengl\gpu_opengl.vcxproj /m /p:Configuration=Debug /p:Platform=x64
```

Expected: both builds succeed.

- [ ] **Step 7: Commit only sampler-boundary resolution hunks**

```powershell
git -C source/app diff --cached --check
git -C source/app diff --cached --name-only
git -C source/app commit -m "fix: resolve MSAA textures before sampling"
```

Expected staged paths are limited to the four files listed in this task.

---

### Task 5: NanoVG stencil readiness on MSAA targets

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/msaa_antialias_contract_test.cpp`

**Interfaces:**
- Consumes: `gpu_opengl::texture::create_depth_resources()`
- Consumes: `gpu_opengl::texture::frame_buffer_object()`
- Produces: a cleared stencil attachment before each NanoVG frame begins

- [ ] **Step 1: Extend the NanoVG contract for stencil readiness**

Add source assertions that:

```cpp
assert(graphics.find("create_depth_resources();") != std::string::npos);
assert(graphics.find("glClearStencil(0);") != std::string::npos);
assert(graphics.find("glClear(GL_STENCIL_BUFFER_BIT);") !=
   std::string::npos);
```

For each active `nvgBeginFrame` path, assert that stencil clearing occurs
after the target framebuffer is bound and before `nvgBeginFrame`.

- [ ] **Step 2: Run the contract and verify failure**

```powershell
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\msaa_antialias_contract_test.cpp /Fe:$env:TEMP\msaa_antialias_contract_test.exe
& $env:TEMP\msaa_antialias_contract_test.exe
```

Expected: failure because the current code clears only color/depth.

- [ ] **Step 3: Centralize NanoVG target preparation**

Add a private helper in `graphics`:

```cpp
void prepare_nanovg_render_target(::gpu::texture * pgputexture);
```

Its OpenGL implementation must:

1. Cast to `gpu_opengl::texture`.
2. Call `create_depth_resources()` if no depth/stencil renderbuffer exists;
   that method must have marked existing per-context framebuffer bindings
   stale as specified in Task 2.
3. Bind `frame_buffer_object()`.
4. Set the viewport to the texture dimensions.
5. Call `glClearStencil(0)`.
6. Call `glClear(GL_STENCIL_BUFFER_BIT)`.
7. Check the OpenGL error.

Call the helper immediately before each active `nvgBeginFrame`, using the
current GPU target for layer rendering and the image texture for memory-image
rendering.

The helper must not clear color or depth; existing pass ownership remains
unchanged.

- [ ] **Step 4: Run all NanoVG contracts**

```powershell
$tests = Get-ChildItem draw2d_nanovg\tests\*_test.cpp
foreach ($test in $tests) {
   $name = [System.IO.Path]::GetFileNameWithoutExtension($test.Name)
   cl /nologo /std:c++20 /EHsc $test.FullName "/Fe:$env:TEMP\$name.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
   & "$env:TEMP\$name.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Expected: every executable exits `0`.

- [ ] **Step 5: Build `draw2d_nanovg`**

```powershell
msbuild draw2d_nanovg\draw2d_nanovg.vcxproj /m /p:Configuration=Debug /p:Platform=x64
```

Expected: build succeeds.

- [ ] **Step 6: Commit only NanoVG stencil hunks**

```powershell
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d diff --cached --name-only
git -C source/app-graphics3d commit -m "fix: prepare NanoVG MSAA stencil targets"
```

Expected staged paths: `draw2d_nanovg/graphics.cpp`,
`draw2d_nanovg/graphics.h`, and
`draw2d_nanovg/tests/msaa_antialias_contract_test.cpp`.

---

### Task 6: Integrated verification

**Files:**
- Verify only; modify production files only if a failing test identifies a
  specific defect and begin a new red-green cycle for that defect.

**Interfaces:**
- Consumes: all interfaces produced by Tasks 1-5
- Produces: evidence that MSAA allocation, NanoVG rendering, resolution, and
  presentation work together

- [ ] **Step 1: Run every affected source contract**

From `source/app`:

```powershell
$tests = Get-ChildItem gpu_opengl\tests\*_test.cpp
foreach ($test in $tests) {
   $name = [System.IO.Path]::GetFileNameWithoutExtension($test.Name)
   cl /nologo /std:c++20 /EHsc $test.FullName "/Fe:$env:TEMP\$name.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
   & "$env:TEMP\$name.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

From `source/app-graphics3d`:

```powershell
$tests = Get-ChildItem draw2d_nanovg\tests\*_test.cpp
foreach ($test in $tests) {
   $name = [System.IO.Path]::GetFileNameWithoutExtension($test.Name)
   cl /nologo /std:c++20 /EHsc $test.FullName "/Fe:$env:TEMP\$name.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
   & "$env:TEMP\$name.exe"
   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Expected: all tests compile and exit `0`.

- [ ] **Step 2: Build all affected Debug/x64 projects**

```powershell
msbuild source\app\bred\bred.vcxproj /m /p:Configuration=Debug /p:Platform=x64
msbuild source\app\gpu_opengl\gpu_opengl.vcxproj /m /p:Configuration=Debug /p:Platform=x64
msbuild source\app-graphics3d\draw2d_nanovg\draw2d_nanovg.vcxproj /m /p:Configuration=Debug /p:Platform=x64
msbuild source\app-graphics3d\continuum\app_graphics3d_continuum.vcxproj /m /p:Configuration=Debug /p:Platform=x64
```

Expected: all four builds succeed.

- [ ] **Step 3: Run the application with MSAA disabled**

Using a runtime configuration/debugger override when available, set:

```cpp
m_gpu.m_bMultisample = false;
```

If a temporary source edit is required, record and restore the exact original
lines before proceeding; do not include the verification toggle in a commit.

Expected:

- NanoVG contexts include `NVG_ANTIALIAS`.
- Render targets use `GL_TEXTURE_2D` with sample count `1`.
- No resolve occurs.
- Graphics3D, NanoVG, and presentation remain visible.
- `glGetError()` remains `GL_NO_ERROR`.

- [ ] **Step 4: Run with supported 2x and 4x MSAA**

For each supported value, use the same non-committed override to set:

```cpp
m_gpu.m_bMultisample = true;
m_gpu.m_iSampleCount = 2; // then 4
```

Restore the approved application defaults after the two runs.

Expected:

- NanoVG contexts omit `NVG_ANTIALIAS` by default.
- Every multisample color and depth/stencil pair reports the same count.
- Graphics3D and NanoVG both render.
- Layer composition and presentation bind only resolved
  `GL_TEXTURE_2D` textures.
- The window is not black.
- No `GL_INVALID_FRAMEBUFFER_OPERATION` occurs.

- [ ] **Step 5: Exercise resize and stencil paths**

Resize the window repeatedly while rendering NanoVG overlapping strokes,
self-intersecting fills, and text over Graphics3D content.

Expected:

- framebuffer completeness remains `GL_FRAMEBUFFER_COMPLETE`;
- no old-size depth/stencil attachment remains cached;
- no stale pixels appear after resize;
- NanoVG stencil fills and strokes render correctly.

- [ ] **Step 6: Verify explicit NanoVG override**

After draw2d_nanovg initialization but before NanoVG context creation, set:

```cpp
::draw2d_nanovg::get()->m_bNanoVGGeometryAntialias = true;
```

Run with application MSAA enabled.

Expected: `NVG_ANTIALIAS` is included deliberately and rendering remains
correct, demonstrating that the setting is an override rather than a hard
prohibition.

- [ ] **Step 7: Review repository state**

```powershell
git status --short
git -C source/app status --short
git -C source/app-graphics3d status --short
```

Expected: no generated executables are present in the repositories, no
unrelated user changes were staged, and only intended implementation commits
were added.
