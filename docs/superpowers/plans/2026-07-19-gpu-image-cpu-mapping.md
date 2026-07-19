# GPU Image CPU Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GPU-backed images honor the established `::image::image` mapped-buffer contract while keeping normal NanoVG rendering entirely GPU-resident.

**Architecture:** `gpu::texture` exposes backend-neutral full-image pixmap transfer hooks. `gpu::image` synchronously maps through its texture's owning GPU context and reuses inherited staging memory; `gpu_opengl::texture` implements readback and upload with orientation, channel-order, fencing, and OpenGL-state preservation.

**Tech Stack:** C++20, SceneFoundry `aura`/`bred` image and GPU abstractions, OpenGL/WGL, NanoVG GL3, Visual Studio/MSBuild, dependency-free C++ source contract tests.

## Global Constraints

- Preserve existing line endings when practical; use Windows CRLF for modified C++ sources and new C++ tests.
- Preserve all unrelated dirty work in the root, `source/app`, and `source/app-graphics3d` repositories.
- `map()` and `unmap()` remain logically `const`; internal staging and synchronization state may change.
- `map()` and `unmap()` execute synchronously through the texture's associated `gpu::context::send()`.
- The first `map()` downloads the complete current GPU texture; repeated mapping while mapped performs no transfer.
- Every matching `unmap()` uploads the complete staging buffer and publishes a texture fence.
- The CPU staging pixmap uses top-left row order and the framework's native channel indexes.
- The existing NanoVG shared-texture fast path remains before CPU mapping and performs no CPU transfer.
- Only OpenGL implements the transfer hooks in this phase; backend-neutral base hooks throw `::not_implemented` for Vulkan and Direct3D until later work.
- Stop the currently running Continuum process gracefully before rebuilding DLLs; do not terminate unrelated processes.

---

## File Structure

- Modify `source/app/bred/gpu/texture.h`: declare backend-neutral `read_pixels` and pixmap-based `write_pixels` hooks.
- Modify `source/app/bred/gpu/texture.cpp`: provide explicit unsupported-backend implementations.
- Modify `source/app/bred/gpu/image.cpp`: implement staging allocation, synchronous map/readback, unmap/upload/fence, and unmap-before-graphics behavior.
- Create `source/app/bred/gpu/tests/gpu_image_mapping_contract_test.cpp`: verify the mapping contract and ordering without linking the framework.
- Modify `source/app/gpu_opengl/texture.h`: override the two pixmap transfer hooks.
- Modify `source/app/gpu_opengl/texture.cpp`: implement state-safe OpenGL readback and upload.
- Create `source/app/gpu_opengl/tests/gpu_image_pixel_transfer_contract_test.cpp`: verify the OpenGL transfer contract and state handling.
- Modify `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp`: verify mapped CPU edits are committed before GPU graphics access.

### Task 1: Backend-neutral image mapping contract

**Files:**
- Modify: `source/app/bred/gpu/texture.h`
- Modify: `source/app/bred/gpu/texture.cpp`
- Modify: `source/app/bred/gpu/image.cpp`
- Modify: `source/app/bred/gpu/tests/gpu_image_contract_test.cpp`
- Create: `source/app/bred/gpu/tests/gpu_image_mapping_contract_test.cpp`

**Interfaces:**
- Consumes: `gpu::texture::context()`, `gpu::texture::wait_fence()`, `gpu::texture::defer_fence()`, `gpu::context::send(const ::procedure &)`, inherited `::image::image::m_memoryMap`, and `::pixmap::create`.
- Produces: `gpu::texture::read_pixels(::pixmap *)`, `gpu::texture::write_pixels(const ::pixmap *)`, functional `gpu::image::map(bool) const`, functional `gpu::image::unmap() const`, and unmap-before-graphics behavior.

- [ ] **Step 1: Write the failing mapping contract test**

Create `source/app/bred/gpu/tests/gpu_image_mapping_contract_test.cpp`:

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

   const auto textureHeader = read_file("bred/gpu/texture.h");
   const auto textureSource = read_file("bred/gpu/texture.cpp");
   const auto imageSource = read_file("bred/gpu/image.cpp");

   assert(textureHeader.find(
      "virtual void read_pixels(::pixmap * ppixmap);") !=
      std::string::npos);
   assert(textureHeader.find(
      "virtual void write_pixels(const ::pixmap * ppixmap);") !=
      std::string::npos);

   const auto baseRead = section(
      textureSource,
      "void texture::read_pixels(",
      "void texture::write_pixels(");
   const auto baseWrite = section(
      textureSource,
      "void texture::write_pixels(",
      "bool texture::is_in_shader_sampling_state(");
   assert(baseRead.find("throw ::not_implemented();") != std::string::npos);
   assert(baseWrite.find("throw ::not_implemented();") != std::string::npos);

   const auto getGraphics = section(
      imageSource,
      "::draw2d::graphics * image::get_graphics() const",
      "::gpu::texture * image::gpu_texture() const");
   assert(getGraphics.find("unmap();") != std::string::npos);
   assert(getGraphics.find("return _get_graphics();") != std::string::npos);

   const auto map = section(
      imageSource,
      "void image::map(",
      "void image::unmap()");
   const auto sendRead = map.find("pgpucontext->send(");
   const auto wait = map.find("wait_fence();", sendRead);
   const auto staging = map.find("pixmap::create(m_memoryMap", wait);
   const auto read = map.find("read_pixels(pthis);", staging);
   const auto mapped = map.find("m_bMapped = true;", read);
   assert(sendRead != std::string::npos);
   assert(wait != std::string::npos);
   assert(staging != std::string::npos);
   assert(read != std::string::npos);
   assert(mapped != std::string::npos);
   assert(sendRead < wait && wait < staging && staging < read && read < mapped);
   assert(map.find("throw ::not_implemented") == std::string::npos);

   const auto unmap = imageSource.substr(
      imageSource.find("void image::unmap()"));
   const auto sendWrite = unmap.find("pgpucontext->send(");
   const auto write = unmap.find("write_pixels(pthis);", sendWrite);
   const auto fence = unmap.find("defer_fence();", write);
   const auto pixmapUnmap = unmap.find("pixmap::unmap();", fence);
   const auto unmapped = unmap.find("m_bMapped = false;", pixmapUnmap);
   assert(sendWrite != std::string::npos);
   assert(write != std::string::npos);
   assert(fence != std::string::npos);
   assert(pixmapUnmap != std::string::npos);
   assert(unmapped != std::string::npos);
   assert(sendWrite < write && write < fence && fence < pixmapUnmap &&
      pixmapUnmap < unmapped);
   assert(unmap.find("throw ::not_implemented") == std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Run the contract test and verify RED**

From a Visual Studio x64 Developer Command Prompt:

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app
cl /nologo /std:c++20 /EHsc bred\gpu\tests\gpu_image_mapping_contract_test.cpp /Fe:$env:TEMP\gpu_image_mapping_contract_test.exe
& $env:TEMP\gpu_image_mapping_contract_test.exe
```

Expected: compilation succeeds and the executable aborts because the texture hooks do not exist and `gpu::image::map()` still throws.

- [ ] **Step 3: Declare the backend-neutral texture hooks**

Add a global forward declaration before `namespace gpu` in `source/app/bred/gpu/texture.h`:

```cpp
struct pixmap;
```

Add after the existing raw `set_pixels` declaration:

```cpp
      virtual void read_pixels(::pixmap * ppixmap);
      virtual void write_pixels(const ::pixmap * ppixmap);
```

- [ ] **Step 4: Add explicit unsupported-backend defaults**

Add between `texture::set_pixels` and `texture::is_in_shader_sampling_state` in `source/app/bred/gpu/texture.cpp`:

```cpp
   void texture::read_pixels(::pixmap *)
   {

      throw ::not_implemented();

   }


   void texture::write_pixels(const ::pixmap *)
   {

      throw ::not_implemented();

   }
```

- [ ] **Step 5: Implement synchronous mapping in `gpu::image`**

Replace `gpu::image::get_graphics`, `map`, and `unmap` in `source/app/bred/gpu/image.cpp` with:

```cpp
   ::draw2d::graphics * image::get_graphics() const
   {

      unmap();

      return _get_graphics();

   }


   void image::map(bool) const
   {

      if (m_bMapped)
      {

         return;

      }

      auto pgputexture = m_pgputexture;

      if (!pgputexture || m_sizeRaw.is_empty())
      {

         throw ::exception(error_wrong_state);

      }

      auto pgpucontext = pgputexture->context();

      if (!pgpucontext)
      {

         throw ::exception(error_wrong_state);

      }

      auto pthis = const_cast < image * >(this);

      pgpucontext->send(
         [pthis, pgputexture]()
         {

            pgputexture->wait_fence();

            pthis->pixmap::create(
               pthis->m_memoryMap,
               pthis->m_sizeRaw,
               pthis->m_sizeRaw.cx * (int)sizeof(::image32_t));

            pgputexture->read_pixels(pthis);
            pthis->pixmap::map(pthis->rectangle());
            pthis->m_bMapped = true;

         });

   }


   void image::unmap() const
   {

      if (!m_bMapped)
      {

         return;

      }

      auto pgputexture = m_pgputexture;

      if (!pgputexture)
      {

         throw ::exception(error_wrong_state);

      }

      auto pgpucontext = pgputexture->context();

      if (!pgpucontext)
      {

         throw ::exception(error_wrong_state);

      }

      auto pthis = const_cast < image * >(this);

      pgpucontext->send(
         [pthis, pgputexture]()
         {

            pgputexture->write_pixels(pthis);
            pgputexture->defer_fence();
            pthis->pixmap::unmap();
            pthis->m_bMapped = false;

         });

   }
```

Keep `m_bMapped` true if the upload throws, so the caller can inspect or retry the mapped staging buffer. Because the dispatch is synchronous, capturing `pthis` is bounded by the lifetime of the active member call.

- [ ] **Step 6: Update the existing contract and normalize Task 1 C++ files**

In `source/app/bred/gpu/tests/gpu_image_contract_test.cpp`, replace:

```cpp
   assert(source.find("throw ::not_implemented();") != std::string::npos);
```

with:

```cpp
   assert(source.find("throw ::not_implemented();") == std::string::npos);
```

Normalize only the Task 1 C++ files to CRLF.

- [ ] **Step 7: Run both backend-neutral contract tests GREEN**

Run:

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app
cl /nologo /std:c++20 /EHsc bred\gpu\tests\gpu_image_mapping_contract_test.cpp /Fe:$env:TEMP\gpu_image_mapping_contract_test.exe
& $env:TEMP\gpu_image_mapping_contract_test.exe
cl /nologo /std:c++20 /EHsc bred\gpu\tests\gpu_image_contract_test.cpp /Fe:$env:TEMP\gpu_image_contract_test.exe
& $env:TEMP\gpu_image_contract_test.exe
```

Expected: both executables exit with code `0`.

- [ ] **Step 8: Build `bred`**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe' solution-windows\SceneFoundry.sln /t:bred /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
```

Expected: exit code `0`, with no compiler or linker errors.

- [ ] **Step 9: Commit only Task 1 files**

```powershell
git -C source/app add -- bred/gpu/texture.h bred/gpu/texture.cpp bred/gpu/image.cpp bred/gpu/tests/gpu_image_mapping_contract_test.cpp bred/gpu/tests/gpu_image_contract_test.cpp
git -C source/app diff --cached --check
git -C source/app commit -m "Add GPU image CPU mapping contract"
```

Expected: the existing unrelated `gpu_opengl/approach.cpp`, `wgl_context.cpp`, `wgl_context.h`, and prior untracked tests remain unstaged.

### Task 2: OpenGL texture readback and upload

**Files:**
- Modify: `source/app/gpu_opengl/texture.h`
- Modify: `source/app/gpu_opengl/texture.cpp`
- Create: `source/app/gpu_opengl/tests/gpu_image_pixel_transfer_contract_test.cpp`

**Interfaces:**
- Consumes: `gpu::texture::read_pixels(::pixmap *)` and `gpu::texture::write_pixels(const ::pixmap *)` from Task 1, OpenGL texture/FBO handles, and `::pixmap` channel indexes and stride.
- Produces: `gpu_opengl::texture::read_pixels(::pixmap *)` and `gpu_opengl::texture::write_pixels(const ::pixmap *)` with top-left CPU orientation, native channel order, and restored OpenGL state.

- [ ] **Step 1: Write the failing OpenGL transfer contract test**

Create `source/app/gpu_opengl/tests/gpu_image_pixel_transfer_contract_test.cpp`:

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

   const auto header = read_file("gpu_opengl/texture.h");
   const auto source = read_file("gpu_opengl/texture.cpp");

   assert(header.find("void read_pixels(::pixmap * ppixmap) override;") !=
      std::string::npos);
   assert(header.find(
      "void write_pixels(const ::pixmap * ppixmap) override;") !=
      std::string::npos);

   const auto state = section(
      source,
      "class scoped_pixel_transfer_state",
      "GLenum pixmap_pixel_format(");
   assert(state.find("GL_READ_FRAMEBUFFER_BINDING") != std::string::npos);
   assert(state.find("GL_DRAW_FRAMEBUFFER_BINDING") != std::string::npos);
   assert(state.find("GL_RENDERBUFFER_BINDING") != std::string::npos);
   assert(state.find("GL_TEXTURE_BINDING_2D") != std::string::npos);
   assert(state.find("GL_PACK_ALIGNMENT") != std::string::npos);
   assert(state.find("GL_PACK_ROW_LENGTH") != std::string::npos);
   assert(state.find("GL_UNPACK_ALIGNMENT") != std::string::npos);
   assert(state.find("GL_UNPACK_ROW_LENGTH") != std::string::npos);

   const auto format = section(
      source,
      "GLenum pixmap_pixel_format(",
      "} // namespace");
   assert(format.find("GL_BGRA") != std::string::npos);
   assert(format.find("GL_RGBA") != std::string::npos);
   assert(format.find("error_not_supported") != std::string::npos);

   const auto read = section(
      source,
      "void texture::read_pixels(",
      "void texture::write_pixels(");
   assert(read.find("glBindFramebuffer(GL_READ_FRAMEBUFFER") !=
      std::string::npos);
   assert(read.find("glFramebufferTexture2D(GL_READ_FRAMEBUFFER") !=
      std::string::npos);
   assert(read.find("glCheckFramebufferStatus(GL_READ_FRAMEBUFFER)") !=
      std::string::npos);
   assert(read.find("glReadPixels(") != std::string::npos);
   assert(read.find("ppixmap->vertical_swap();") != std::string::npos);

   const auto write = source.substr(source.find("void texture::write_pixels("));
   assert(write.find("pixmapFlipped.copy(ppixmap);") != std::string::npos);
   assert(write.find("pixmapFlipped.vertical_swap();") != std::string::npos);
   assert(write.find("glTexSubImage2D(") != std::string::npos);
   assert(write.find("GL_UNPACK_ROW_LENGTH") != std::string::npos);

   return 0;

}
```

- [ ] **Step 2: Run the transfer test and verify RED**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\gpu_image_pixel_transfer_contract_test.cpp /Fe:$env:TEMP\gpu_image_pixel_transfer_contract_test.exe
& $env:TEMP\gpu_image_pixel_transfer_contract_test.exe
```

Expected: compilation succeeds and the executable aborts because the OpenGL overrides do not exist.

- [ ] **Step 3: Declare the OpenGL overrides**

Add after `set_pixels` in `source/app/gpu_opengl/texture.h`:

```cpp
      void read_pixels(::pixmap * ppixmap) override;
      void write_pixels(const ::pixmap * ppixmap) override;
```

- [ ] **Step 4: Add scoped OpenGL state preservation and channel selection**

Before `namespace gpu_opengl` near the top of `source/app/gpu_opengl/texture.cpp`, add:

```cpp
namespace
{


   class scoped_pixel_transfer_state
   {
   public:


      GLint m_iReadFramebuffer = 0;
      GLint m_iDrawFramebuffer = 0;
      GLint m_iRenderbuffer = 0;
      GLint m_iReadBuffer = 0;
      GLint m_iTexture2d = 0;
      GLint m_iPackAlignment = 0;
      GLint m_iPackRowLength = 0;
      GLint m_iUnpackAlignment = 0;
      GLint m_iUnpackRowLength = 0;


      scoped_pixel_transfer_state()
      {

      glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &m_iReadFramebuffer);
      glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &m_iDrawFramebuffer);
      glGetIntegerv(GL_RENDERBUFFER_BINDING, &m_iRenderbuffer);
      glGetIntegerv(GL_READ_BUFFER, &m_iReadBuffer);
      glGetIntegerv(GL_TEXTURE_BINDING_2D, &m_iTexture2d);
      glGetIntegerv(GL_PACK_ALIGNMENT, &m_iPackAlignment);
      glGetIntegerv(GL_PACK_ROW_LENGTH, &m_iPackRowLength);
      glGetIntegerv(GL_UNPACK_ALIGNMENT, &m_iUnpackAlignment);
      glGetIntegerv(GL_UNPACK_ROW_LENGTH, &m_iUnpackRowLength);

      }


      ~scoped_pixel_transfer_state() noexcept
      {

      glBindFramebuffer(GL_READ_FRAMEBUFFER, m_iReadFramebuffer);
      glReadBuffer(m_iReadBuffer);
      glBindFramebuffer(GL_DRAW_FRAMEBUFFER, m_iDrawFramebuffer);
      glBindRenderbuffer(GL_RENDERBUFFER, m_iRenderbuffer);
      glBindTexture(GL_TEXTURE_2D, m_iTexture2d);
      glPixelStorei(GL_PACK_ALIGNMENT, m_iPackAlignment);
      glPixelStorei(GL_PACK_ROW_LENGTH, m_iPackRowLength);
      glPixelStorei(GL_UNPACK_ALIGNMENT, m_iUnpackAlignment);
      glPixelStorei(GL_UNPACK_ROW_LENGTH, m_iUnpackRowLength);

      }


   };


   GLenum pixmap_pixel_format(const ::pixmap * ppixmap)
   {

      const auto & indexes = ppixmap->m_colorindexes;

      if (indexes.red() == 2 && indexes.green() == 1 &&
          indexes.blue() == 0 && indexes.opacity() == 3)
      {

         return GL_BGRA;

      }

      if (indexes.red() == 0 && indexes.green() == 1 &&
          indexes.blue() == 2 && indexes.opacity() == 3)
      {

         return GL_RGBA;

      }

      throw ::exception(
         error_not_supported,
         "Unsupported GPU image CPU pixel channel order.");

   }


} // namespace
```

`texture.cpp` already includes `acme/graphics/image/pixmap.h`; keep that include.

- [ ] **Step 5: Implement OpenGL readback**

Add before the existing raw `texture::set_pixels` implementation:

```cpp
   void texture::read_pixels(::pixmap * ppixmap)
   {

      if (!ppixmap || ppixmap->size() != size() ||
          ppixmap->m_iScan < width() * (int)sizeof(::image32_t) ||
          !ppixmap->m_pimage32Raw || !m_gluTextureID ||
          m_gluType != GL_TEXTURE_2D)
      {

         throw ::exception(error_bad_argument);

      }

      scoped_pixel_transfer_state state;

      auto gluFramebuffer = frame_buffer_object();

      glBindFramebuffer(GL_READ_FRAMEBUFFER, gluFramebuffer);
      ::opengl::check_error("");

      glFramebufferTexture2D(
         GL_READ_FRAMEBUFFER,
         GL_COLOR_ATTACHMENT0,
         GL_TEXTURE_2D,
         m_gluTextureID,
         0);
      ::opengl::check_error("");

      auto eStatus = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER);

      if (eStatus != GL_FRAMEBUFFER_COMPLETE)
      {

         throw ::exception(
            error_wrong_state,
            "GPU image framebuffer is incomplete during CPU mapping.");

      }

      glReadBuffer(GL_COLOR_ATTACHMENT0);
      glPixelStorei(GL_PACK_ALIGNMENT, 1);
      glPixelStorei(
         GL_PACK_ROW_LENGTH,
         ppixmap->m_iScan / (int)sizeof(::image32_t));

      glReadPixels(
         0,
         0,
         width(),
         height(),
         pixmap_pixel_format(ppixmap),
         GL_UNSIGNED_BYTE,
         ppixmap->m_pimage32Raw);
      ::opengl::check_error("");

      ppixmap->vertical_swap();

   }
```

- [ ] **Step 6: Implement OpenGL upload**

Add immediately after `read_pixels`:

```cpp
   void texture::write_pixels(const ::pixmap * ppixmap)
   {

      if (!ppixmap || ppixmap->size() != size() ||
          ppixmap->m_iScan < width() * (int)sizeof(::image32_t) ||
          !ppixmap->m_pimage32Raw || !m_gluTextureID ||
          m_gluType != GL_TEXTURE_2D)
      {

         throw ::exception(error_bad_argument);

      }

      ::memory memoryFlipped;
      ::pixmap pixmapFlipped;
      pixmapFlipped.create(
         memoryFlipped,
         ppixmap->size(),
         ppixmap->m_iScan);
      pixmapFlipped.m_colorindexes = ppixmap->m_colorindexes;
      pixmapFlipped.copy(ppixmap);
      pixmapFlipped.vertical_swap();

      scoped_pixel_transfer_state state;

      glBindTexture(GL_TEXTURE_2D, m_gluTextureID);
      ::opengl::check_error("");
      glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
      glPixelStorei(
         GL_UNPACK_ROW_LENGTH,
         pixmapFlipped.m_iScan / (int)sizeof(::image32_t));

      glTexSubImage2D(
         GL_TEXTURE_2D,
         0,
         0,
         0,
         width(),
         height(),
         pixmap_pixel_format(&pixmapFlipped),
         GL_UNSIGNED_BYTE,
         pixmapFlipped.m_pimage32Raw);
      ::opengl::check_error("");

   }
```

The `gpu::image::unmap()` caller publishes the fence after this method returns; do not add a second fence here.

- [ ] **Step 7: Normalize CRLF and run the OpenGL contract test GREEN**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\gpu_image_pixel_transfer_contract_test.cpp /Fe:$env:TEMP\gpu_image_pixel_transfer_contract_test.exe
& $env:TEMP\gpu_image_pixel_transfer_contract_test.exe
```

Expected: executable exits with code `0`.

- [ ] **Step 8: Stop only the Continuum instance launched for the previous validation**

The previously launched process ID was `20156`. Check that it still points to the Debug Continuum executable, request graceful closure, and wait before building:

```powershell
$p = Get-Process -Id 20156 -ErrorAction SilentlyContinue
if ($p -and $p.Path -eq 'C:\Users\camilo\SceneFoundry\main\time-windows\x64\Debug\shared_app_graphics3d_continuum.exe') {
   [void]$p.CloseMainWindow()
   $p.WaitForExit(10000)
}
```

Expected: that process exits or is reported absent. Do not use `Stop-Process` unless the user separately approves forced termination.

- [ ] **Step 9: Build `gpu_opengl`**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe' solution-windows\SceneFoundry.sln /t:gpu_opengl /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
```

Expected: exit code `0`, with no compiler or linker errors.

- [ ] **Step 10: Commit only the OpenGL transfer files**

```powershell
git -C source/app add -- gpu_opengl/texture.h gpu_opengl/texture.cpp gpu_opengl/tests/gpu_image_pixel_transfer_contract_test.cpp
git -C source/app diff --cached --check
git -C source/app commit -m "Implement OpenGL GPU image pixel transfers"
```

Expected: prior WGL synchronization changes and tests remain unstaged.

### Task 3: NanoVG compatibility and integration verification

**Files:**
- Modify: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp`
- Verify: `source/app-graphics3d/draw2d_nanovg/tests/gpu_image_fast_path_test.cpp`
- Runtime target: `solution-windows/SceneFoundry.sln`, project `shared_app_graphics3d_continuum`

**Interfaces:**
- Consumes: functional `gpu::image::map/unmap`, OpenGL transfer overrides, and the existing direct shared-texture NanoVG path.
- Produces: regression evidence that mapped CPU edits are committed before graphics access while the normal NanoVG path remains map-free.

- [ ] **Step 1: Extend the lifecycle contract before relying on the integration**

Add these reads and assertions to `gpu_image_lifecycle_test.cpp`:

```cpp
   const auto gpuImageSource = read_file("../app/bred/gpu/image.cpp");

   const auto getGraphics = section(
      gpuImageSource,
      "::draw2d::graphics * image::get_graphics() const",
      "::gpu::texture * image::gpu_texture() const");
   const auto unmapBeforeGraphics = getGraphics.find("unmap();");
   const auto returnGraphics = getGraphics.find("return _get_graphics();");
   assert(unmapBeforeGraphics != std::string::npos);
   assert(returnGraphics != std::string::npos);
   assert(unmapBeforeGraphics < returnGraphics);
```

Because this source-level test runs from `source/app-graphics3d`, the relative path reaches the sibling nested repository at `../app/bred/gpu/image.cpp`.

- [ ] **Step 2: Run all focused tests**

From a Visual Studio x64 Developer Command Prompt:

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main\source\app
cl /nologo /std:c++20 /EHsc bred\gpu\tests\gpu_image_contract_test.cpp /Fe:$env:TEMP\gpu_image_contract_test.exe
& $env:TEMP\gpu_image_contract_test.exe
cl /nologo /std:c++20 /EHsc bred\gpu\tests\gpu_image_mapping_contract_test.cpp /Fe:$env:TEMP\gpu_image_mapping_contract_test.exe
& $env:TEMP\gpu_image_mapping_contract_test.exe
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\gpu_image_pixel_transfer_contract_test.cpp /Fe:$env:TEMP\gpu_image_pixel_transfer_contract_test.exe
& $env:TEMP\gpu_image_pixel_transfer_contract_test.exe

Set-Location C:\Users\camilo\SceneFoundry\main\source\app-graphics3d
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\memory_graphics_lifecycle_test.cpp /Fe:$env:TEMP\memory_graphics_lifecycle_test.exe
& $env:TEMP\memory_graphics_lifecycle_test.exe
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\gpu_image_lifecycle_test.cpp /Fe:$env:TEMP\gpu_image_lifecycle_test.exe
& $env:TEMP\gpu_image_lifecycle_test.exe
cl /nologo /std:c++20 /EHsc draw2d_nanovg\tests\gpu_image_fast_path_test.cpp /Fe:$env:TEMP\gpu_image_fast_path_test.exe
& $env:TEMP\gpu_image_fast_path_test.exe
```

Expected: all six executables exit with code `0`.

- [ ] **Step 3: Build the affected libraries and Continuum**

```powershell
Set-Location C:\Users\camilo\SceneFoundry\main
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe'
& $msbuild solution-windows\SceneFoundry.sln /t:bred /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
& $msbuild solution-windows\SceneFoundry.sln /t:gpu_opengl /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
& $msbuild solution-windows\SceneFoundry.sln /t:draw2d_nanovg /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
& $msbuild solution-windows\SceneFoundry.sln /t:shared_app_graphics3d_continuum /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
```

Expected: every command exits with code `0`; existing conversion warnings may remain, but there are no new compiler or linker errors.

- [ ] **Step 4: Review repository boundaries and commit the lifecycle test**

```powershell
git -C source/app status --short
git -C source/app diff --check
git -C source/app-graphics3d status --short
git -C source/app-graphics3d diff --check
git -C source/app-graphics3d add -- draw2d_nanovg/tests/gpu_image_lifecycle_test.cpp
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d commit -m "Test NanoVG mapped GPU image compatibility"
```

Expected: only the lifecycle test is committed in `source/app-graphics3d`; unrelated changes remain untouched.

- [ ] **Step 5: Verify mapped CPU setup followed by GPU drawing in Visual Studio**

Run Debug/x64 `shared_app_graphics3d_continuum` with the OpenGL backend, on-screen rendering, and `draw2d_nanovg`. Set breakpoints on:

```text
gpu::image::map
gpu::image::unmap
gpu_opengl::texture::read_pixels
gpu_opengl::texture::write_pixels
draw2d_nanovg::graphics::_draw_gpu_image
```

Exercise a setup/loading path that maps a GPU-backed image. Expected sequence:

1. `map()` dispatches synchronously to the image graphics' GPU context task.
2. `read_pixels()` returns top-left, correctly colored CPU pixels.
3. CPU edits remain visible through the mapped `::image::image` interface.
4. `unmap()` or `get_graphics()` calls `write_pixels()` before GPU drawing.
5. `_draw_gpu_image` subsequently draws the texture without another `map()`.

- [ ] **Step 6: Verify visual correctness and stability**

Open and scroll the font list and inspect GPU-backed previews. Expected:

- text and images are upright;
- red and blue channels are not swapped;
- premultiplied-alpha edges have no dark or bright fringe;
- normal repeated drawing stays on `_draw_gpu_image` and does not map;
- process memory reaches a steady range after setup;
- shutdown reports no OpenGL error, access violation, or locked-context failure.

- [ ] **Step 7: Record nested repository pointers only when requested**

Do not stage the root `source` pointer automatically. If the user explicitly requests root integration after runtime approval:

```powershell
git add -- source
git diff --cached --check
git commit -m "Integrate GPU image CPU mapping"
```

Expected: the root commit changes only the nested `source` pointer.
