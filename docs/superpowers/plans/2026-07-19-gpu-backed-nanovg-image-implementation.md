# GPU-backed NanoVG Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-neutral `gpu::image`, specialize it for NanoVG/OpenGL offscreen rendering, and draw those images directly from shared OpenGL textures without CPU mapping or upload.

**Architecture:** `gpu::image` derives from `::image::image` and owns the authoritative `gpu::texture`. `draw2d_nanovg::image` derives from `gpu::image`, renders into that texture through its private shared OpenGL context, and `draw2d_nanovg::graphics` wraps the shared GL handle with `nvglCreateImageFromHandleGL3` when drawing it in another NanoVG context.

**Tech Stack:** C++20, SceneFoundry `aura`/`bred` GPU abstractions, OpenGL/WGL shared contexts, NanoVG GL3, Visual Studio/MSBuild, dependency-free C++ source regression probes.

## Global Constraints

- Preserve existing line endings when practical; use Windows CRLF for modified C++ sources and new C++ tests.
- Preserve all unrelated work already present in the dirty `source/app` and `source/app-graphics3d` repositories.
- Phase-one `gpu::image::map()` and `gpu::image::unmap()` must throw `::not_implemented()`.
- The supported NanoVG GPU path must never call `map()` or `unmap()`.
- Ordinary CPU-backed `::image::image` objects must retain the current conversion/upload fallback.
- Only OpenGL/NanoVG consumes GPU images in this phase; no Vulkan or Direct3D implementation is added.
- The image graphics/context must be released before its GPU texture.
- Do not commit the overlapping `draw2d_nanovg/graphics.cpp` and `graphics.h` changes until the user confirms the runtime test; those files already contain earlier uncommitted work.

---

## File Structure

- Create `source/app/bred/gpu/image.h`: backend-neutral GPU image contract and texture ownership.
- Create `source/app/bred/gpu/image.cpp`: lifecycle, graphics access, texture initialization, and explicit CPU mapping failures.
- Create `source/app/bred/gpu/tests/gpu_image_contract_test.cpp`: dependency-free source-level contract regression test.
- Modify `source/app/bred/gpu/_.h`: forward-declare `gpu::image`.
- Modify `source/app/bred/gpu/renderer.cpp`: make `create_image_texture` create a render-target and shader-resource texture.
- Modify `source/app/bred/CMakeLists.txt`: compile the new GPU image files.
- Modify `source/app/bred/bred.vcxproj`: compile and expose the new GPU image files in Visual Studio.
- Modify `source/app/bred/bred.vcxproj.filters`: place the new files in the GPU source/header filters.
- Create `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp`: verify inheritance, creation, target selection, and destruction order.
- Create `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_fast_path_test.cpp`: verify the direct GL texture path precedes CPU mapping and preserves fallback behavior.
- Modify `source/app-graphics3d/draw2d_nanovg/image.h`: derive from `gpu::image` and remove the obsolete NanoVG map/unmap overrides.
- Modify `source/app-graphics3d/draw2d_nanovg/image.cpp`: allocate offscreen graphics plus a GPU texture without allocating a CPU bitmap.
- Modify `source/app-graphics3d/draw2d_nanovg/graphics.h`: declare focused GPU-image and NanoVG-image drawing helpers.
- Modify `source/app-graphics3d/draw2d_nanovg/graphics.cpp`: select image textures as compositor targets, fence completed image rendering, and implement the direct shared-texture drawing path.

### Task 1: Backend-neutral `gpu::image`

**Files:**
- Create: `source/app/bred/gpu/image.h`
- Create: `source/app/bred/gpu/image.cpp`
- Create: `source/app/bred/gpu/tests/gpu_image_contract_test.cpp`
- Modify: `source/app/bred/gpu/_.h`
- Modify: `source/app/bred/gpu/renderer.cpp:248-265`
- Modify: `source/app/bred/CMakeLists.txt`
- Modify: `source/app/bred/bred.vcxproj`
- Modify: `source/app/bred/bred.vcxproj.filters`

**Interfaces:**
- Consumes: `gpu::renderer::create_image_texture(const ::i32_size &, bool)` and `gpu::texture` context ownership.
- Produces: `gpu::image::initialize_gpu_image(gpu::context *, const ::i32_size &)`, `gpu::image::gpu_texture() const`, and a `get_graphics()` override that does not invoke CPU unmapping.

- [ ] **Step 1: Write the failing GPU image contract test**

Create `source/app/bred/gpu/tests/gpu_image_contract_test.cpp` with a source-level probe that can run without linking the framework:

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>


namespace
{


   std::string read_file(const char * pszPath)
   {

      std::ifstream stream(pszPath, std::ios::binary);

      return {
         std::istreambuf_iterator<char>(stream),
         std::istreambuf_iterator<char>()};

   }


} // namespace


int main()
{

   const auto header = read_file("bred/gpu/image.h");
   const auto source = read_file("bred/gpu/image.cpp");
   const auto renderer = read_file("bred/gpu/renderer.cpp");
   const auto cmake = read_file("bred/CMakeLists.txt");
   const auto project = read_file("bred/bred.vcxproj");

   assert(header.find("virtual public ::image::image") != std::string::npos);
   assert(header.find("::pointer < ::gpu::texture > m_pgputexture;") !=
      std::string::npos);
   assert(header.find("::gpu::texture * gpu_texture() const;") !=
      std::string::npos);
   assert(header.find("void initialize_gpu_image(") != std::string::npos);
   assert(header.find("::draw2d::graphics * get_graphics() const override;") !=
      std::string::npos);

   assert(source.find("return _get_graphics();") != std::string::npos);
   assert(source.find("throw ::not_implemented();") != std::string::npos);
   assert(source.find("m_pgputexture =") != std::string::npos);

   const auto destroy = source.find("void image::destroy()");
   const auto destroyGraphics = source.find(
      "::image::image::destroy();", destroy);
   const auto destroyTexture = source.find(
      "m_pgputexture.release();", destroy);
   assert(destroy != std::string::npos);
   assert(destroyGraphics != std::string::npos);
   assert(destroyTexture != std::string::npos);
   assert(destroyGraphics < destroyTexture);

   const auto createImageTexture = renderer.find(
      "renderer::create_image_texture");
   assert(createImageTexture != std::string::npos);
   const auto renderTarget = renderer.find(
      "textureflags.m_bRenderTarget = true;", createImageTexture);
   const auto shaderResource = renderer.find(
      "textureflags.m_bShaderResource = true;", createImageTexture);
   assert(renderTarget != std::string::npos);
   assert(shaderResource != std::string::npos);

   assert(cmake.find("gpu/image.cpp") != std::string::npos);
   assert(cmake.find("gpu/image.h") != std::string::npos);
   assert(project.find("gpu\\image.cpp") != std::string::npos);
   assert(project.find("gpu\\image.h") != std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Run the contract test and verify RED**

From a Visual Studio x64 Developer PowerShell:

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app
cl /nologo /std:c++20 /EHsc bred\gpu\tests\gpu_image_contract_test.cpp /Fe:gpu_image_contract_test.exe
.\gpu_image_contract_test.exe
```

Expected: compilation succeeds and the executable aborts because `bred/gpu/image.h` does not exist or lacks the required contract.

- [ ] **Step 3: Add the `gpu::image` declaration**

Create `source/app/bred/gpu/image.h`:

```cpp
#pragma once


#include "aura/graphics/image/image.h"


namespace gpu
{


   class context;
   class texture;


   class CLASS_DECL_BRED image :
      virtual public ::image::image
   {
   public:


      ::pointer < ::gpu::texture > m_pgputexture;


      image();
      ~image() override;


      ::draw2d::graphics * get_graphics() const override;

      virtual ::gpu::texture * gpu_texture() const;
      virtual void initialize_gpu_image(
         ::gpu::context * pgpucontext,
         const ::i32_size & size);

      void destroy() override;

      void map(bool bApplyAlphaTransform = true) const override;
      void unmap() const override;


   };


} // namespace gpu
```

Add this declaration next to `class texture;` in `source/app/bred/gpu/_.h`:

```cpp
   class image;
   class texture;
```

- [ ] **Step 4: Implement the GPU image lifecycle and explicit mapping failure**

Create `source/app/bred/gpu/image.cpp`:

```cpp
#include "framework.h"
#include "image.h"
#include "context.h"
#include "context_lock.h"
#include "renderer.h"
#include "texture.h"


namespace gpu
{


   image::image()
   {

   }


   image::~image()
   {

      destroy();

   }


   ::draw2d::graphics * image::get_graphics() const
   {

      return _get_graphics();

   }


   ::gpu::texture * image::gpu_texture() const
   {

      return m_pgputexture;

   }


   void image::initialize_gpu_image(
      ::gpu::context * pgpucontext,
      const ::i32_size & size)
   {

      if (!pgpucontext || size.is_empty())
      {

         throw ::exception(error_bad_argument);

      }

      ::gpu::context_lock contextlock(pgpucontext);

      auto pgpurenderer = pgpucontext->get_gpu_renderer();
      auto pgputexture = pgpurenderer->create_image_texture(size, false);

      if (!pgputexture)
      {

         throw ::exception(error_failed, "Failed to create GPU image texture.");

      }

      m_pgputexture = pgputexture;
      m_size = size;
      m_sizeRaw = size;
      m_point.clear();
      m_iScan = 0;
      m_pimage32 = nullptr;
      m_pimage32Raw = nullptr;
      set_ok_flag();

   }


   void image::destroy()
   {

      ::image::image::destroy();
      m_pgputexture.release();

   }


   void image::map(bool) const
   {

      throw ::not_implemented();

   }


   void image::unmap() const
   {

      throw ::not_implemented();

   }


} // namespace gpu
```

The `get_graphics()` override is required because `::image::image::get_graphics()` calls `unmap()` before `_get_graphics()`; phase-one GPU images intentionally cannot unmap.

- [ ] **Step 5: Make image textures renderable and sampleable**

In `gpu::renderer::create_image_texture`, set the flags before `initialize_texture`:

```cpp
      ::gpu::texture_flags textureflags;

      textureflags.m_bWithDepth = bWithDepth;
      textureflags.m_bRenderTarget = true;
      textureflags.m_bShaderResource = true;

      ptexture->initialize_texture(m_pgpucontext, textureattributes, textureflags);
```

There are currently no other call sites for `create_image_texture`, so this gives the helper the semantics its name requires without changing existing consumers.

- [ ] **Step 6: Add the new files to all build descriptions**

Add these entries to the `library_source` list in `source/app/bred/CMakeLists.txt`:

```cmake
   gpu/image.cpp
   gpu/image.h
```

Add these entries to the existing `ItemGroup` blocks in `source/app/bred/bred.vcxproj`:

```xml
    <ClInclude Include="gpu\image.h" />
    <ClCompile Include="gpu\image.cpp" />
```

Add these entries to `source/app/bred/bred.vcxproj.filters`:

```xml
    <ClInclude Include="gpu\image.h">
      <Filter>Header Files\gpu</Filter>
    </ClInclude>
    <ClCompile Include="gpu\image.cpp">
      <Filter>Source Files\gpu</Filter>
    </ClCompile>
```

- [ ] **Step 7: Run the contract test and verify GREEN**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app
cl /nologo /std:c++20 /EHsc bred\gpu\tests\gpu_image_contract_test.cpp /Fe:gpu_image_contract_test.exe
.\gpu_image_contract_test.exe
```

Expected: compilation succeeds and the executable exits with code `0`.

- [ ] **Step 8: Build `bred`**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main
msbuild solution-windows\SceneFoundry.sln /m /t:bred /p:Configuration=Debug /p:Platform=x64
```

Expected: `bred` and its required dependencies build successfully with zero compiler or linker errors.

- [ ] **Step 9: Commit the isolated `source/app` change**

Stage only the new GPU image contract and renderer/build wiring; do not stage the unrelated dirty `gpu_opengl` files:

```powershell
git -C source/app add -- bred/gpu/image.h bred/gpu/image.cpp bred/gpu/tests/gpu_image_contract_test.cpp bred/gpu/_.h bred/gpu/renderer.cpp bred/CMakeLists.txt bred/bred.vcxproj bred/bred.vcxproj.filters
git -C source/app diff --cached --check
git -C source/app commit -m "Add backend-neutral GPU images"
```

Expected: one commit containing only the listed `bred` paths.

### Task 2: NanoVG GPU image lifecycle and render target

**Files:**
- Create: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/image.h:7-20, 29-53, 150-151`
- Modify: `source/app-graphics3d/draw2d_nanovg/image.cpp:10-123, 218-229, 2405-2456, 2752-2888`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:6235-6239, 8740-8748`

**Interfaces:**
- Consumes: `gpu::image::initialize_gpu_image`, `gpu::image::gpu_texture`, and `gpu::image::destroy` from Task 1.
- Produces: a factory-compatible `draw2d_nanovg::image` whose `g()` renders to `m_pgputexture`, plus `graphics::current_target_texture` selection for that image.

- [ ] **Step 1: Write the failing NanoVG lifecycle test**

Create `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp`:

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>


namespace
{


   std::string read_file(const char * pszPath)
   {

      std::ifstream stream(pszPath, std::ios::binary);

      return {
         std::istreambuf_iterator<char>(stream),
         std::istreambuf_iterator<char>()};

   }


   std::string section(
      const std::string & source,
      const std::string & beginMarker,
      const std::string & endMarker)
   {

      const auto begin = source.find(beginMarker);
      const auto end = source.find(endMarker, begin);

      assert(begin != std::string::npos);
      assert(end != std::string::npos);
      assert(begin < end);

      return source.substr(begin, end - begin);

   }


} // namespace


int main()
{

   const auto header = read_file("draw2d_nanovg/image.h");
   const auto imageSource = read_file("draw2d_nanovg/image.cpp");
   const auto graphicsSource = read_file("draw2d_nanovg/graphics.cpp");

   assert(header.find("virtual public ::gpu::image") != std::string::npos);
   assert(header.find("void map(") == std::string::npos);
   assert(header.find("void unmap(") == std::string::npos);

   const auto create = section(
      imageSource,
      "void image::create(const ::i32_size& size",
      "bool image::host(");
   const auto createGraphics = create.find("create_memory_graphics(size);");
   const auto initializeGpuImage = create.find("initialize_gpu_image(");
   assert(createGraphics != std::string::npos);
   assert(initializeGpuImage != std::string::npos);
   assert(createGraphics < initializeGpuImage);
   assert(create.find("create_bitmap") == std::string::npos);
   assert(create.find("::pixmap::initialize") == std::string::npos);

   const auto getGraphics = section(
      imageSource,
      "::draw2d::graphics * image::_get_graphics() const",
      "double image::pi()");
   assert(getGraphics.find("return m_pgraphics;") != std::string::npos);
   assert(getGraphics.find("m_pbitmap") == std::string::npos);

   const auto destroy = section(
      imageSource,
      "void image::destroy()",
      "bool image::from(");
   assert(destroy.find("::gpu::image::destroy();") != std::string::npos);

   const auto target = section(
      graphicsSource,
      "::gpu::texture* graphics::current_target_texture(",
      "bool graphics::is_gpu_oriented()");
   const auto imageCast = target.find("dynamic_cast < ::gpu::image * >");
   const auto imageTexture = target.find("gpu_texture()", imageCast);
   const auto fallback = target.find(
      "::gpu::graphics::current_target_texture(pgpulayer)", imageTexture);
   assert(imageCast != std::string::npos);
   assert(imageTexture != std::string::npos);
   assert(fallback != std::string::npos);
   assert(imageCast < imageTexture);
   assert(imageTexture < fallback);

   const auto endLayer = section(
      graphicsSource,
      "void graphics::on_end_layer(",
      "void graphics::start_layer(");
   assert(endLayer.find("gpu_texture()") != std::string::npos);
   assert(endLayer.find("defer_fence();") != std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Run the lifecycle test and verify RED**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app-graphics3d
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\gpu_image_lifecycle_test.cpp /Fe:gpu_image_lifecycle_test.exe
.\gpu_image_lifecycle_test.exe
```

Expected: compilation succeeds and the executable aborts because `draw2d_nanovg::image` still derives directly from `::image::image`.

- [ ] **Step 3: Change the NanoVG image base and phase-one interface**

In `draw2d_nanovg/image.h`, replace the Aura image include and base declaration with:

```cpp
#include "bred/gpu/image.h"


namespace draw2d_nanovg
{


   class CLASS_DECL_DRAW2D_NANOVG image :
      virtual public ::gpu::image
```

Keep the existing `create`, `_get_graphics`, bitmap-access, host, and destroy declarations. Remove the `map()` and `unmap()` declarations so the explicit `gpu::image` implementations are inherited.

- [ ] **Step 4: Replace CPU bitmap creation with GPU image creation**

Replace `draw2d_nanovg::image::create` with:

```cpp
   void image::create(
      const ::i32_size & size,
      ::enum_flag eobjectCreate,
      int,
      bool)
   {

      if (m_pgputexture && m_pgraphics && m_pgputexture->size() == size)
      {

         return;

      }

      destroy();

      if (size.is_empty())
      {

         return;

      }

      constructø(m_pgraphics);
      m_pgraphics->m_pimage = this;
      m_pgraphics->create_memory_graphics(size);

      ::cast < ::draw2d_nanovg::graphics > pgraphics = m_pgraphics;

      if (!pgraphics || !pgraphics->gpu_context())
      {

         destroy();
         throw ::exception(
            error_wrong_state,
            "NanoVG GPU image has no OpenGL graphics context.");

      }

      initialize_gpu_image(pgraphics->gpu_context(), size);

      m_eflagElement = eobjectCreate;
      m_estatus = ::success;
      set_ok_flag();

   }
```

Add `#include "bred/gpu/texture.h"` near the top of `image.cpp` so the texture size check uses a complete type.

- [ ] **Step 5: Simplify graphics access and destruction**

Replace `_get_graphics()` with:

```cpp
   ::draw2d::graphics * image::_get_graphics() const
   {

      return m_pgraphics;

   }
```

Replace `destroy()` with:

```cpp
   void image::destroy()
   {

      m_phost = nullptr;
      ::gpu::image::destroy();

   }
```

Delete the obsolete `image::map` and `image::unmap` definitions. Leave `get_bitmap()` and `detach_bitmap()` returning the inherited null bitmap; phase one has no CPU bitmap.

- [ ] **Step 6: Route the NanoVG compositor to the image texture**

Replace `draw2d_nanovg::graphics::current_target_texture` with:

```cpp
   ::gpu::texture * graphics::current_target_texture(::gpu::layer * pgpulayer)
   {

      auto pgpuimage = dynamic_cast < ::gpu::image * >(m_pimage);

      if (pgpuimage)
      {

         auto pgputexture = pgpuimage->gpu_texture();

         if (pgputexture)
         {

            return pgputexture;

         }

      }

      return ::gpu::graphics::current_target_texture(pgpulayer);

   }
```

This override is active only for an image-associated graphics facade; window graphics continues to use the renderer/swap-chain target.

- [ ] **Step 7: Fence completed image rendering**

Immediately after `nvgEndFrame(m_pdc);` in `graphics::on_end_layer`, add:

```cpp
      auto pgpuimage = dynamic_cast < ::gpu::image * >(m_pimage);

      if (pgpuimage && pgpuimage->gpu_texture())
      {

         pgpuimage->gpu_texture()->defer_fence();

      }
```

Keep the existing `glFlush()` and error check. The texture fence publishes producer completion to a consuming shared OpenGL context.

- [ ] **Step 8: Run both NanoVG lifecycle tests**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app-graphics3d
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\memory_graphics_lifecycle_test.cpp /Fe:memory_graphics_lifecycle_test.exe
.\memory_graphics_lifecycle_test.exe
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\gpu_image_lifecycle_test.cpp /Fe:gpu_image_lifecycle_test.exe
.\gpu_image_lifecycle_test.exe
```

Expected: both executables exit with code `0`; the existing memory-graphics lifecycle test remains unchanged because it covers graphics-context creation rather than image bitmap storage.

- [ ] **Step 9: Build `draw2d_nanovg` without committing overlapping files**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main
msbuild solution-windows\SceneFoundry.sln /m /t:draw2d_nanovg /p:Configuration=Debug /p:Platform=x64
git -C source/app-graphics3d diff --check -- draw2d_nanovg/image.h draw2d_nanovg/image.cpp draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp
```

Expected: the project builds with zero errors and `git diff --check` reports no whitespace errors. Keep this task as a review checkpoint because `graphics.cpp` already contains earlier uncommitted work.

### Task 3: Direct NanoVG shared-texture drawing path

**Files:**
- Create: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_fast_path_test.cpp`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.h:118`
- Modify: `source/app-graphics3d/draw2d_nanovg/graphics.cpp:8167-8248`

**Interfaces:**
- Consumes: `gpu::image::gpu_texture`, `gpu_opengl::texture::m_gluTextureID`, and the producer fence from Task 2.
- Produces: `graphics::_draw_gpu_image`, `graphics::_draw_nanovg_image`, and an `_draw_raw` dispatch that never maps compatible GPU images.

- [ ] **Step 1: Write the failing direct-path regression test**

Create `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_fast_path_test.cpp`:

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>


namespace
{


   std::string read_file(const char * pszPath)
   {

      std::ifstream stream(pszPath, std::ios::binary);

      return {
         std::istreambuf_iterator<char>(stream),
         std::istreambuf_iterator<char>()};

   }


   std::string section(
      const std::string & source,
      const std::string & beginMarker,
      const std::string & endMarker)
   {

      const auto begin = source.find(beginMarker);
      const auto end = source.find(endMarker, begin);

      assert(begin != std::string::npos);
      assert(end != std::string::npos);
      assert(begin < end);

      return source.substr(begin, end - begin);

   }


} // namespace


int main()
{

   const auto header = read_file("draw2d_nanovg/graphics.h");
   const auto source = read_file("draw2d_nanovg/graphics.cpp");

   assert(header.find("bool _draw_gpu_image(") != std::string::npos);
   assert(header.find("void _draw_nanovg_image(") != std::string::npos);

   const auto drawRaw = section(
      source,
      "void graphics::_draw_raw(",
      "void graphics::set_text_rendering_hint(");
   const auto update = drawRaw.find("pimage->defer_update_image();");
   const auto gpuDispatch = drawRaw.find("_draw_gpu_image(", update);
   const auto cpuMap = drawRaw.find("pimage->map();", gpuDispatch);
   const auto cpuUpload = drawRaw.find("nvgCreateImageRGBA(", cpuMap);
   assert(update != std::string::npos);
   assert(gpuDispatch != std::string::npos);
   assert(cpuMap != std::string::npos);
   assert(cpuUpload != std::string::npos);
   assert(update < gpuDispatch);
   assert(gpuDispatch < cpuMap);
   assert(cpuMap < cpuUpload);

   const auto gpuPath = section(
      source,
      "bool graphics::_draw_gpu_image(",
      "void graphics::_draw_raw(");
   assert(gpuPath.find("dynamic_cast < ::gpu::image * >") !=
      std::string::npos);
   assert(gpuPath.find("dynamic_cast < ::gpu_opengl::texture * >") !=
      std::string::npos);
   assert(gpuPath.find("wait_fence();") != std::string::npos);
   assert(gpuPath.find("nvglCreateImageFromHandleGL3(") !=
      std::string::npos);
   assert(gpuPath.find("NVG_IMAGE_NODELETE") != std::string::npos);
   assert(gpuPath.find("NVG_IMAGE_PREMULTIPLIED") != std::string::npos);
   assert(gpuPath.find("NVG_IMAGE_FLIPY") != std::string::npos);
   assert(gpuPath.find("nvgDeleteImage(m_pdc, iImage);") !=
      std::string::npos);
   assert(gpuPath.find("->map(") == std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Run the fast-path test and verify RED**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app-graphics3d
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\gpu_image_fast_path_test.cpp /Fe:gpu_image_fast_path_test.exe
.\gpu_image_fast_path_test.exe
```

Expected: compilation succeeds and the executable aborts because the helper declarations and direct GL texture path do not exist.

- [ ] **Step 3: Declare focused drawing helpers**

Immediately after `_draw_raw` in `draw2d_nanovg/graphics.h`, add:

```cpp
      virtual bool _draw_gpu_image(
         const ::f64_rectangle & rectangleTarget,
         ::image::image * pimage,
         const ::image::image_drawing_options & imagedrawingoptions,
         const ::f64_point & pointSrc);

      virtual void _draw_nanovg_image(
         int iImage,
         const ::i32_size & sizeImage,
         const ::f64_rectangle & rectangleTarget,
         const ::image::image_drawing_options & imagedrawingoptions,
         const ::f64_point & pointSrc);
```

- [ ] **Step 4: Extract the common NanoVG image geometry**

Add this implementation before `_draw_gpu_image`:

```cpp
   void graphics::_draw_nanovg_image(
      int iImage,
      const ::i32_size & sizeImage,
      const ::f64_rectangle & rectangleTarget,
      const ::image::image_drawing_options & imagedrawingoptions,
      const ::f64_point & pointSrc)
   {

      nanovg_keep keep(m_pdc);

      auto paint = nvgImagePattern(
         m_pdc,
         (float)(rectangleTarget.left - pointSrc.x),
         (float)(rectangleTarget.top - pointSrc.y),
         (float)sizeImage.cx,
         (float)sizeImage.cy,
         0.f,
         iImage,
         imagedrawingoptions.opacity().f32_opacity());

      nvgBeginPath(m_pdc);
      nvgRect(
         m_pdc,
         (float)rectangleTarget.left,
         (float)rectangleTarget.top,
         (float)rectangleTarget.width(),
         (float)rectangleTarget.height());
      nvgFillPaint(m_pdc, paint);
      nvgFill(m_pdc);

   }
```

Both GPU and CPU image paths call this helper so source-region placement and opacity remain identical.

- [ ] **Step 5: Implement the shared OpenGL texture path**

Add before `_draw_raw`:

```cpp
   bool graphics::_draw_gpu_image(
      const ::f64_rectangle & rectangleTarget,
      ::image::image * pimage,
      const ::image::image_drawing_options & imagedrawingoptions,
      const ::f64_point & pointSrc)
   {

      auto pgpuimage = dynamic_cast < ::gpu::image * >(pimage);

      if (!pgpuimage)
      {

         return false;

      }

      auto pgputexture = dynamic_cast < ::gpu_opengl::texture * >(
         pgpuimage->gpu_texture());

      if (!pgputexture || !pgputexture->m_gluTextureID)
      {

         throw ::exception(
            error_wrong_state,
            "NanoVG GPU image has no compatible OpenGL texture.");

      }

      auto pgpucontextTexture = pgputexture->context();
      auto pgpucontextCurrent = gpu_context();

      if (!pgpucontextTexture || !pgpucontextCurrent ||
          pgpucontextTexture->m_pgpudevice != pgpucontextCurrent->m_pgpudevice)
      {

         throw ::exception(
            error_wrong_state,
            "NanoVG GPU image belongs to a different GPU device.");

      }

      pgputexture->wait_fence();

      _synchronous_lock synchronouslock(::draw2d_nanovg::mutex());

      auto sizeImage = pgpuimage->size();
      auto iImage = nvglCreateImageFromHandleGL3(
         m_pdc,
         pgputexture->m_gluTextureID,
         sizeImage.cx,
         sizeImage.cy,
         NVG_IMAGE_NODELETE |
            NVG_IMAGE_PREMULTIPLIED |
            NVG_IMAGE_FLIPY);

      if (iImage == 0)
      {

         throw ::exception(
            error_failed,
            "NanoVG failed to wrap the OpenGL GPU image texture.");

      }

      _draw_nanovg_image(
         iImage,
         sizeImage,
         rectangleTarget,
         imagedrawingoptions,
         pointSrc);

      nvgDeleteImage(m_pdc, iImage);

      return true;

   }
```

`NVG_IMAGE_NODELETE` ensures `nvgDeleteImage` releases only NanoVG wrapper metadata. The `gpu::image` remains the texture owner.

- [ ] **Step 6: Dispatch before CPU mapping and retain the fallback**

Refactor `_draw_raw` to keep the existing validation and CPU conversion, but dispatch to the GPU path before `map()`:

```cpp
   void graphics::_draw_raw(
      const ::f64_rectangle & rectangleTarget,
      ::image::image * pimage,
      const ::image::image_drawing_options & imagedrawingoptions,
      const ::f64_point & pointSrc)
   {

      if (!m_pdc || !pimage || rectangleTarget.is_empty() || pimage->is_empty())
      {

         return;

      }

      pimage->defer_update_image();

      if (_draw_gpu_image(
         rectangleTarget,
         pimage,
         imagedrawingoptions,
         pointSrc))
      {

         return;

      }

      pimage->map();

      auto sizeImage = pimage->size();
      ::memory memoryRgba;
      memoryRgba.set_size(sizeImage.area() * 4);

      auto ptarget = memoryRgba.data();
      auto colorindexes = pimage->color_indexes();

      for (int y = 0; y < sizeImage.cy; y++)
      {

         auto psource = pimage->line_data(y);

         for (int x = 0; x < sizeImage.cx; x++)
         {

            *ptarget++ = psource->u8_red(colorindexes);
            *ptarget++ = psource->u8_green(colorindexes);
            *ptarget++ = psource->u8_blue(colorindexes);
            *ptarget++ = psource->u8_opacity(colorindexes);
            psource++;

         }

      }

      _synchronous_lock synchronouslock(::draw2d_nanovg::mutex());

      auto iImage = nvgCreateImageRGBA(
         m_pdc,
         sizeImage.cx,
         sizeImage.cy,
         NVG_IMAGE_PREMULTIPLIED,
         memoryRgba.data());

      if (iImage == 0)
      {

         return;

      }

      _draw_nanovg_image(
         iImage,
         sizeImage,
         rectangleTarget,
         imagedrawingoptions,
         pointSrc);

      nvgDeleteImage(m_pdc, iImage);

   }
```

- [ ] **Step 7: Run all focused regression tests**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app-graphics3d
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\memory_graphics_lifecycle_test.cpp /Fe:memory_graphics_lifecycle_test.exe
.\memory_graphics_lifecycle_test.exe
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\gpu_image_lifecycle_test.cpp /Fe:gpu_image_lifecycle_test.exe
.\gpu_image_lifecycle_test.exe
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\gpu_image_fast_path_test.cpp /Fe:gpu_image_fast_path_test.exe
.\gpu_image_fast_path_test.exe
```

Expected: all three executables exit with code `0`.

- [ ] **Step 8: Build the affected projects and application**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main
msbuild solution-windows\SceneFoundry.sln /m /t:bred /p:Configuration=Debug /p:Platform=x64
msbuild solution-windows\SceneFoundry.sln /m /t:gpu_opengl /p:Configuration=Debug /p:Platform=x64
msbuild solution-windows\SceneFoundry.sln /m /t:draw2d_nanovg /p:Configuration=Debug /p:Platform=x64
msbuild solution-windows\SceneFoundry.sln /m /t:shared_app_graphics3d_continuum /p:Configuration=Debug /p:Platform=x64
```

Expected: all four targets build with zero compiler/linker errors.

- [ ] **Step 9: Review the complete nested-repository diff**

```powershell
git -C source/app status --short
git -C source/app diff --check
git -C source/app-graphics3d status --short
git -C source/app-graphics3d diff --check
git -C source/app-graphics3d diff -- draw2d_nanovg/image.h draw2d_nanovg/image.cpp draw2d_nanovg/graphics.h draw2d_nanovg/graphics.cpp draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp draw2d_nanovg/tests/gpu_image_fast_path_test.cpp
```

Expected: no whitespace errors; unrelated prior changes remain present and unstaged; the reviewed NanoVG diff contains the previously approved memory-graphics work plus this GPU-image feature.

### Task 4: Visual Studio runtime verification and final commit

**Files:**
- Runtime target: `solution-windows/SceneFoundry.sln`
- Runtime project: `shared_app_graphics3d_continuum`
- Commit scope: the reviewed `draw2d_nanovg` files from Tasks 2 and 3 after user confirmation.

**Interfaces:**
- Consumes: the built GPU image lifecycle and direct texture path.
- Produces: runtime evidence for orientation, alpha, mapping avoidance, resource stability, and shutdown safety.

- [ ] **Step 1: Verify font preview generation without CPU mapping**

In Visual Studio, set `shared_app_graphics3d_continuum` as the startup project, select Debug/x64, use the OpenGL backend with on-screen rendering and `draw2d_nanovg`, and place breakpoints on:

```text
gpu::image::map
gpu::image::unmap
draw2d_nanovg::graphics::_draw_gpu_image
```

Open the font list and scroll until several preview images are created. Expected: `_draw_gpu_image` is hit; `gpu::image::map` and `gpu::image::unmap` are never hit.

- [ ] **Step 2: Verify visual correctness**

Inspect multiple font previews against their labels. Expected:

- Text is upright rather than vertically inverted.
- Glyph colors are correct rather than red/blue swapped.
- Antialiased edges blend cleanly with the list background.
- Transparent pixels do not show dark or bright fringes.
- Source rectangles and opacity behave like ordinary CPU-backed images.

If every preview is vertically inverted, remove only `NVG_IMAGE_FLIPY`, rebuild `draw2d_nanovg`, and repeat this step. Keep whichever flag configuration matches the existing CPU-image orientation.

- [ ] **Step 3: Verify caching, memory stability, and shutdown**

Scroll repeatedly through the font list for at least two minutes and revisit previously viewed fonts. Expected: previews remain stable, previously generated previews do not upload through `nvgCreateImageRGBA`, process memory reaches a steady range, and Visual Studio reports no OpenGL errors or access violations when the application closes.

- [ ] **Step 4: Verify the CPU image fallback**

Display a known CPU-backed image that is not a `gpu::image` and place a breakpoint on `nvgCreateImageRGBA`. Expected: the breakpoint is hit for the CPU image and the image renders as before. This confirms the fallback was preserved.

- [ ] **Step 5: Commit only after runtime confirmation**

After the user confirms Steps 1-4, stage the reviewed NanoVG scope, including the earlier compatible memory-graphics changes already present in the same files:

```powershell
git -C source/app-graphics3d add -- draw2d_nanovg/graphics.cpp draw2d_nanovg/graphics.h draw2d_nanovg/image.cpp draw2d_nanovg/image.h draw2d_nanovg/tests/memory_graphics_lifecycle_test.cpp draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp draw2d_nanovg/tests/gpu_image_fast_path_test.cpp
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d diff --cached --stat
git -C source/app-graphics3d commit -m "Add GPU-backed NanoVG images"
```

Expected: one `source/app-graphics3d` commit containing only the reviewed NanoVG implementation and regression probes.

- [ ] **Step 6: Record nested commits in the root repository only when requested**

The root repository tracks `source` as a nested repository/submodule boundary. Do not stage or commit its pointer automatically. If the user requests the root pointer update after both nested commits are accepted, run:

```powershell
git status --short
git add -- source
git diff --cached --check
git commit -m "Integrate GPU-backed NanoVG images"
```

Expected: the root commit changes only the `source` pointer.
