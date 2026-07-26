# Continuum Live Monitor Texture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Continuum's 3D screen quad display the resolved virtual-monitor texture containing the ocean wallpaper and the live, proportionally positioned HelloMultiverse window.

**Architecture:** `main_scene::on_before_render` continues to own the wallpaper/application composition and the MSAA resolve. After a successful resolve into the single-sample `m_pgputextureMonitor2`, the scene publishes that stable texture object to the screen quad's underlying `graphics3d::renderable`; the generic `texture_render_system` remains unchanged and binds the published texture during the later scene render.

**Tech Stack:** C++20, SceneFoundry `gpu` and `graphics3d` abstractions, OpenGL MSAA resolve through `gpu::context::copy`, MSVC command-line contract test, Visual Studio/MSBuild Debug x64.

## Global Constraints

- Preserve existing line endings when practical.
- Use Windows CRLF line endings for the new C++ contract test and the modified C++ source.
- Publish `m_pgputextureMonitor2`, which is single-sample; never publish `m_pgputextureMonitorMultisample` to a `sampler2D` consumer.
- Publish only after `gpu::context::copy` returns successfully.
- Keep `texture_render_system` generic; do not add Continuum-specific resolve or selection logic there.
- Do not add another monitor texture, allocation, or full-screen GPU copy.
- Do not change the wallpaper/overlay shader, desktop coordinate mapping, opacity behavior, application MSAA policy, or NanoVG antialiasing policy.
- Preserve unrelated existing edits under `source/app/gpu_opengl`.

---

## File Structure

- Create `source/app-graphics3d/continuum/tests/live_monitor_texture_contract_test.cpp`: dependency-free source contract proving that the quad receives the resolved texture after the copy and that the generic texture renderer consumes that member.
- Modify `source/app-graphics3d/continuum/main_scene.cpp`: publish the successfully resolved monitor texture to the screen quad.
- Verify `solution-windows/SceneFoundry.sln`: build the existing `app_graphics3d_continuum` target; no solution or project-file modification is required because the contract is compiled independently.

### Task 1: Publish the Resolved Monitor Texture

**Files:**

- Create: `source/app-graphics3d/continuum/tests/live_monitor_texture_contract_test.cpp`
- Modify: `source/app-graphics3d/continuum/main_scene.cpp:623`
- Inspect only: `source/app/bred/graphics3d/render_system/texture_render_system.cpp:281`

**Interfaces:**

- Consumes: `graphics3d::scene_renderable::renderable() -> graphics3d::renderable *`, `graphics3d::renderable::m_ptextureTexture`, `gpu::context::copy(gpu::texture *, gpu::texture *, pointer<gpu::fence> *)`.
- Produces: after every successful monitor resolve, the screen quad's `m_ptextureTexture` points to `main_scene::m_pgputextureMonitor2`.

- [ ] **Step 1: Write the failing source contract**

Create `source/app-graphics3d/continuum/tests/live_monitor_texture_contract_test.cpp` with:

```cpp
#include <cassert>
#include <fstream>
#include <iterator>
#include <string>


namespace
{


   std::string read_file(const char *pszPath)
   {

      std::ifstream stream(pszPath, std::ios::binary);

      assert(stream);

      return {
         std::istreambuf_iterator<char>(stream),
         std::istreambuf_iterator<char>()};

   }


   std::string section(
      const std::string &source,
      const std::string &beginMarker,
      const std::string &endMarker)
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

   const auto sceneSource = read_file("continuum/main_scene.cpp");
   const auto renderSystemSource = read_file(
      "../app/bred/graphics3d/render_system/texture_render_system.cpp");

   const auto beforeRender = section(
      sceneSource,
      "void main_scene::on_before_render(",
      "void main_scene::on_render(");

   const auto resolve = beforeRender.find(
      "pgpucontext->copy(m_pgputextureMonitor2, "
      "m_pgputextureMonitorMultisample, nullptr);");
   const auto sceneRenderableGuard =
      beforeRender.find("if (m_prenderable)", resolve);
   const auto renderableLookup = beforeRender.find(
      "auto prenderableMonitor = m_prenderable->renderable();",
      sceneRenderableGuard);
   const auto renderableGuard =
      beforeRender.find("if (prenderableMonitor)", renderableLookup);
   const auto publish = beforeRender.find(
      "prenderableMonitor->m_ptextureTexture = "
      "m_pgputextureMonitor2;",
      renderableGuard);

   assert(resolve != std::string::npos);
   assert(sceneRenderableGuard != std::string::npos);
   assert(renderableLookup != std::string::npos);
   assert(renderableGuard != std::string::npos);
   assert(publish != std::string::npos);
   assert(resolve < sceneRenderableGuard);
   assert(sceneRenderableGuard < renderableLookup);
   assert(renderableLookup < renderableGuard);
   assert(renderableGuard < publish);
   assert(beforeRender.find(
      "m_ptextureTexture = m_pgputextureMonitorMultisample") ==
      std::string::npos);

   assert(renderSystemSource.find(
      "prenderable->m_ptextureTexture->binding_slot_set(") !=
      std::string::npos);

   return 0;

}
```

Save the new file with CRLF line endings.

- [ ] **Step 2: Compile and run the contract to verify it fails**

Run from `C:\Users\camilo\SceneFoundry\main`:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$installationPath = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
$vcvars = Join-Path $installationPath 'VC\Auxiliary\Build\vcvars64.bat'
$testRoot = 'C:\Users\camilo\SceneFoundry\main\source\app-graphics3d'
$testExe = Join-Path $env:TEMP 'live_monitor_texture_contract_test.exe'
cmd.exe /d /c "`"$vcvars`" >nul && cd /d `"$testRoot`" && cl.exe /nologo /std:c++20 /EHsc continuum\tests\live_monitor_texture_contract_test.cpp /Fe:`"$testExe`" && `"$testExe`""
```

Expected: compilation succeeds, then the executable exits nonzero at the missing `sceneRenderableGuard`, `renderableLookup`, `renderableGuard`, or `publish` assertion. This proves the current code resolves the composite but does not publish it to the quad.

- [ ] **Step 3: Add the minimal publication after the successful resolve**

In `main_scene::on_before_render`, immediately after:

```cpp
pgpucontext->copy(m_pgputextureMonitor2, m_pgputextureMonitorMultisample, nullptr);
```

insert:

```cpp
if (m_prenderable)
{

   auto prenderableMonitor = m_prenderable->renderable();

   if (prenderableMonitor)
   {

      prenderableMonitor->m_ptextureTexture = m_pgputextureMonitor2;

   }

}
```

Do not assign the multisample source texture. Do not allocate a new texture, copy again, or modify `texture_render_system.cpp`.

- [ ] **Step 4: Run the focused contract to verify it passes**

Repeat the Step 2 PowerShell command.

Expected: compilation succeeds and `live_monitor_texture_contract_test.exe` exits with code `0`.

- [ ] **Step 5: Review the scoped diff and line endings**

Run:

```powershell
git -C source/app-graphics3d diff --check -- continuum/main_scene.cpp continuum/tests/live_monitor_texture_contract_test.cpp
git -C source/app-graphics3d diff -- continuum/main_scene.cpp continuum/tests/live_monitor_texture_contract_test.cpp
$paths = @(
   'source/app-graphics3d/continuum/main_scene.cpp',
   'source/app-graphics3d/continuum/tests/live_monitor_texture_contract_test.cpp'
)
foreach ($path in $paths) {
   $bytes = [System.IO.File]::ReadAllBytes((Resolve-Path $path))
   $text = [System.Text.Encoding]::UTF8.GetString($bytes)
   if ($text -match '(?<!\r)\n') { throw "Non-CRLF newline found in $path" }
}
```

Expected: `git diff --check` has no output; the diff contains only the contract and the guarded resolved-texture assignment; the newline check does not throw.

- [ ] **Step 6: Commit the tested change in the correct nested repository**

Run:

```powershell
git -C source/app-graphics3d add -- continuum/main_scene.cpp continuum/tests/live_monitor_texture_contract_test.cpp
git -C source/app-graphics3d diff --cached --check
git -C source/app-graphics3d commit -m "Fix live monitor texture publishing"
```

Expected: one commit in `source/app-graphics3d` containing exactly the two Task 1 files.

### Task 2: Integration and Runtime Verification

**Files:**

- Verify only: `solution-windows/SceneFoundry.sln`
- Verify only: `source/app-graphics3d/continuum/app_graphics3d_continuum.vcxproj`
- Inspect only: the running Debug x64 Continuum application and Visual Studio debugger/output

**Interfaces:**

- Consumes: Task 1's invariant that the screen quad points to the stable single-sample `m_pgputextureMonitor2`.
- Produces: build evidence and runtime evidence that the composed monitor updates live without framebuffer errors.

- [ ] **Step 1: Re-run the focused contract from a clean process**

Run from `C:\Users\camilo\SceneFoundry\main`:

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$installationPath = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
$vcvars = Join-Path $installationPath 'VC\Auxiliary\Build\vcvars64.bat'
$testRoot = 'C:\Users\camilo\SceneFoundry\main\source\app-graphics3d'
$testExe = Join-Path $env:TEMP 'live_monitor_texture_contract_test.exe'
cmd.exe /d /c "`"$vcvars`" >nul && cd /d `"$testRoot`" && cl.exe /nologo /std:c++20 /EHsc continuum\tests\live_monitor_texture_contract_test.cpp /Fe:`"$testExe`" && `"$testExe`""
if ($LASTEXITCODE -ne 0) { throw 'live monitor texture contract failed' }
```

Expected: exit code `0`.

- [ ] **Step 2: Build the affected Continuum target from the requested solution**

Continue in the same PowerShell session:

```powershell
$msbuild = Join-Path $installationPath 'MSBuild\Current\Bin\MSBuild.exe'
& $msbuild 'C:\Users\camilo\SceneFoundry\main\solution-windows\SceneFoundry.sln' /t:app_graphics3d_continuum /m:1 /nr:false /p:Configuration=Debug /p:Platform=x64 /v:minimal
if ($LASTEXITCODE -ne 0) { throw 'app_graphics3d_continuum Debug x64 build failed' }
```

Expected: MSBuild exits with code `0` and reports `Build succeeded`.

- [ ] **Step 3: Verify the live virtual-monitor composition**

Run the Debug x64 Continuum application with the OpenGL backend, MSAA enabled, and HelloMultiverse producing bitmap-source frames. Observe the screen quad while moving, resizing, and changing content in the HelloMultiverse window.

Confirm all of the following:

1. The ocean wallpaper fills the virtual monitor.
2. HelloMultiverse appears over the wallpaper at the same proportional desktop position and size supplied by the bitmap source.
3. Content changes in HelloMultiverse appear on the quad continuously rather than freezing on the wallpaper.
4. Moving or resizing HelloMultiverse updates its projected rectangle.
5. The debugger/output contains no `GL_INVALID_FRAMEBUFFER_OPERATION`, incomplete-multisample exception, or sampler-type error.
6. The rest of the 3D scene and NanoVG on-screen rendering remain correctly antialiased.

Expected: all six observations pass. If any observation fails, capture the debugger exception/output and the last visible monitor frame before making another code change.

- [ ] **Step 4: Record final repository state**

Run:

```powershell
git -C source/app-graphics3d status --short
git -C source/app-graphics3d log -1 --oneline
git status --short
```

Expected: `source/app-graphics3d` has no uncommitted Task 1 changes, its latest commit is `Fix live monitor texture publishing`, and the root status still preserves unrelated pre-existing `source` changes.
