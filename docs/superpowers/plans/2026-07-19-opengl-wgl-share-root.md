# OpenGL WGL Share-Root Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the first-render-context `m_hglrcShare` alias with a dedicated, approach-owned WGL share-root context that is never made current.

**Architecture:** The recursive OpenGL approach mutex continues to serialize WGL bootstrap. On the first ordinary context creation, `_create_wgl_context()` creates a non-rendering root with a null share parameter, stores it in `approach::m_hglrcShare`, and then creates the requested ordinary context as a child; every later context shares with the same idle root. The approach destructor deletes and clears the root under the same mutex.

**Tech Stack:** C++20, Win32 WGL, `WGL_ARB_create_context`, SceneFoundry recursive `::mutex`, Visual Studio 2026/MSBuild, standalone source-level regression.

## Global Constraints

- Keep the existing recursive approach synchronization; do not add another mutex.
- Never assign the dedicated root to `wgl_context::m_hglrc`.
- Never select the dedicated root or use it for rendering.
- Preserve the existing dummy WGL context exclusively for extension bootstrap.
- Preserve unrelated dirty files and the earlier synchronization implementation.
- Use Windows CRLF line endings for modified C++ and Markdown files.

---

### Task 1: Establish an approach-owned idle share root

**Files:**
- Modify: `source/app/gpu_opengl/tests/dummy_wgl_context_synchronization_test.cpp`
- Modify: `source/app/gpu_opengl/wgl_context.cpp:202-230`
- Modify: `source/app/gpu_opengl/approach.cpp:49-53`

**Interfaces:**
- Consumes: `approach::m_hglrcShare`, recursive `approach::synchronization()`, `wglCreateContextAttribsARB(HDC, HGLRC, const int *)`, and `wglDeleteContext(HGLRC)`.
- Produces: a dedicated root HGLRC owned by `gpu_opengl::approach`; every `wgl_context::m_hglrc` is a child ordinary context and never the root.

- [x] **Step 1: Extend the regression to require dedicated-root creation**

In `source/app/gpu_opengl/tests/dummy_wgl_context_synchronization_test.cpp`, replace the existing `createContext` share-handle assertions with:

```cpp
   const auto createContext = function_body(
      wglSource,
      "void wgl_context::_create_wgl_context(",
      "void wgl_context::create_offscreen_wgl_context(");

   const auto shareLock = createContext.find(
      "synchronous_lock synchronouslock(pgpuapproach->synchronization()");
   const auto rootGuard = createContext.find(
      "if (!pgpuapproach->m_hglrcShare)");
   const auto rootCreate = createContext.find(
      "wglCreateContextAttribsARB(m_hdc, nullptr, contextAttribs)");
   const auto rootAssign = createContext.find(
      "pgpuapproach->m_hglrcShare = hglrcShare;");
   const auto childCreate = createContext.find(
      "wglCreateContextAttribsARB(m_hdc, pgpuapproach->m_hglrcShare, contextAttribs)");

   assert(shareLock != std::string::npos);
   assert(rootGuard != std::string::npos);
   assert(rootCreate != std::string::npos);
   assert(rootAssign != std::string::npos);
   assert(childCreate != std::string::npos);
   assert(shareLock < rootGuard);
   assert(rootGuard < rootCreate);
   assert(rootCreate < rootAssign);
   assert(rootAssign < childCreate);
   assert(createContext.find("pgpuapproach->m_hglrcShare = hglrc;") ==
      std::string::npos);
```

Add approach-destruction assertions after the getter assertions:

```cpp
   const auto approachDestructor = function_body(
      approach,
      "approach::~approach()",
      "void approach::initialize(");

   const auto destructorLock = approachDestructor.find(
      "synchronous_lock synchronouslock(this->synchronization()");
   const auto rootDelete = approachDestructor.find(
      "wglDeleteContext(m_hglrcShare)");
   const auto rootClear = approachDestructor.find(
      "m_hglrcShare = nullptr;");

   assert(destructorLock != std::string::npos);
   assert(rootDelete != std::string::npos);
   assert(rootClear != std::string::npos);
   assert(destructorLock < rootDelete);
   assert(rootDelete < rootClear);
```

- [x] **Step 2: Run the regression to verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\source\app` in Visual Studio Developer PowerShell:

```powershell
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\dummy_wgl_context_synchronization_test.cpp /Fe:dummy_wgl_context_synchronization_test.exe
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\dummy_wgl_context_synchronization_test.exe
```

Expected: execution fails at `rootCreate != std::string::npos`, because current code passes the first ordinary rendering context directly into `m_hglrcShare` instead of creating a separate null-share root.

- [x] **Step 3: Create the root before every ordinary child context**

Replace `wgl_context::_create_wgl_context()` in `source/app/gpu_opengl/wgl_context.cpp` with:

```cpp
   void wgl_context::_create_wgl_context(::i32 * contextAttribs)
   {

      ::cast<approach> pgpuapproach = m_papplication->get_gpu_approach();

      synchronous_lock synchronouslock(pgpuapproach->synchronization(), DEFAULT_SYNCHRONOUS_LOCK_SUFFIX);

      if (!pgpuapproach->m_hglrcShare)
      {

         ::SetLastError(ERROR_SUCCESS);

         auto hglrcShare = wglCreateContextAttribsARB(m_hdc, nullptr, contextAttribs);

         if (!hglrcShare)
         {

            auto lasterror = ::windows::last_error();

            throw ::exception(
               error_failed,
               {lasterror},
               "Failed to create dedicated WGL share-root context");

         }

         pgpuapproach->m_hglrcShare = hglrcShare;

      }

      ::SetLastError(ERROR_SUCCESS);

      auto hglrc = wglCreateContextAttribsARB(m_hdc, pgpuapproach->m_hglrcShare, contextAttribs);

      if (!hglrc)
      {

         auto lasterror = ::windows::last_error();

         throw ::exception(
            error_failed,
            {lasterror},
            "Failed to create WGL rendering context sharing with the dedicated root");

      }

      m_hglrc = hglrc;

   }
```

The root remains stored if child creation fails. A later attempt reuses the same valid, never-current root.

- [x] **Step 4: Delete the dedicated root during approach teardown**

Replace the empty destructor in `source/app/gpu_opengl/approach.cpp` with:

```cpp
   approach::~approach()
   {

      synchronous_lock synchronouslock(this->synchronization(), DEFAULT_SYNCHRONOUS_LOCK_SUFFIX);

      if (m_hglrcShare)
      {

         if (!::wglDeleteContext(m_hglrcShare))
         {

            auto lasterror = ::windows::last_error();

            warning(
               "wglDeleteContext failed for dedicated share root; last error: %d",
               (int)lasterror.m_uLastError);

         }

         m_hglrcShare = nullptr;

      }

}
```

The destructor reports `windows::last_error::m_uLastError` using the established numeric logging pattern and does not throw.

- [x] **Step 5: Normalize all modified files to CRLF**

Run:

```powershell
$paths = @(
  'source\app\gpu_opengl\approach.cpp',
  'source\app\gpu_opengl\wgl_context.cpp',
  'source\app\gpu_opengl\wgl_context.h',
  'source\app\gpu_opengl\tests\dummy_wgl_context_synchronization_test.cpp',
  'docs\superpowers\plans\2026-07-19-opengl-wgl-share-root.md'
)
foreach ($path in $paths) {
  $full = (Resolve-Path -LiteralPath $path).Path
  $content = [System.IO.File]::ReadAllText($full)
  $content = $content -replace "`r?`n", "`r`n"
  [System.IO.File]::WriteAllText($full, $content, [System.Text.UTF8Encoding]::new($false))
}
```

- [x] **Step 6: Run the regression to verify GREEN**

Run:

```powershell
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\dummy_wgl_context_synchronization_test.cpp /Fe:dummy_wgl_context_synchronization_test.exe
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\dummy_wgl_context_synchronization_test.exe
```

Expected: exit code `0` with all dedicated-root ownership and ordering assertions passing.

- [x] **Step 7: Build `gpu_opengl` Debug x64**

Run from `C:\Users\camilo\SceneFoundry\main`:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:gpu_opengl /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /nodeReuse:false /nologo /v:minimal
```

Expected: `gpu_opengl.vcxproj` compiles and links. Report unrelated existing conversion warnings separately.

- [x] **Step 8: Check hygiene and remove generated artifacts**

Run:

```powershell
git -C source/app diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$artifactRoot = 'C:\Users\camilo\SceneFoundry\main\source\app'
foreach ($name in @(
  'dummy_wgl_context_synchronization_test.exe',
  'dummy_wgl_context_synchronization_test.obj')) {
  $path = Join-Path $artifactRoot $name
  if ([System.IO.Path]::GetDirectoryName($path) -ne $artifactRoot) {
    throw "Unexpected artifact path: $path"
  }
  [System.IO.File]::Delete($path)
}
```

Expected: diff check exits `0`; generated test artifacts are absent from repository status.

- [ ] **Step 9: Runtime verification checkpoint**

Run the OpenGL application path that concurrently populates the font list and creates memory drawing contexts.

Expected:

- no `ERROR_BUSY` (`170`) from root creation or child context creation;
- no dummy-context ownership exceptions;
- font-list population completes;
- normal rendering remains concurrent;
- shutdown does not report share-root deletion failure.

- [ ] **Step 10: Commit after runtime confirmation**

From `C:\Users\camilo\SceneFoundry\main\source\app`:

```powershell
git add -- gpu_opengl/approach.cpp gpu_opengl/wgl_context.cpp gpu_opengl/wgl_context.h gpu_opengl/tests/dummy_wgl_context_synchronization_test.cpp
git diff --cached --check
git commit -m "Use dedicated WGL share root"
```

Expected: one nested `source/app` commit containing the synchronization, dedicated root, and regression. Do not stage unrelated root, `source`, or `source/app-graphics3d` changes.
