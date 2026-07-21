# OpenGL Dummy WGL Context Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serialize initialization and complete `select/use/unselect` use of the shared dummy WGL context with the OpenGL approach synchronization backed by recursive `::mutex`.

**Architecture:** `gpu_opengl::approach` creates and owns its synchronization object. The public dummy-context getter briefly locks it around lazy creation, while `scoped_dummy_wgl_context` retains a `synchronous_lock` member across its full lifetime so window and offscreen WGL bootstrap cannot overlap across threads. Recursive `::mutex` semantics allow the scope to call the locking getter and extension loader safely.

**Tech Stack:** C++20, Win32 WGL, GLAD, SceneFoundry particle synchronization, Visual Studio 2026/MSBuild, standalone source-level C++ regression.

## Global Constraints

- Use the existing `gpu_opengl::approach` synchronization backed by recursive `::mutex`; do not introduce a separate mutex.
- Serialize dummy-context bootstrap only; do not serialize normal rendering on created GPU contexts.
- Preserve existing public signatures except for adding private state to `scoped_dummy_wgl_context`.
- Preserve existing user changes and unrelated dirty files.
- Use Windows CRLF line endings for modified C++ and Markdown files.

---

### Task 1: Protect dummy WGL context creation and scoped use

**Files:**
- Create: `source/app/gpu_opengl/tests/dummy_wgl_context_synchronization_test.cpp`
- Modify: `source/app/gpu_opengl/approach.cpp:49-55,187-205`
- Modify: `source/app/gpu_opengl/wgl_context.h:4-8,12-16,69-80`
- Modify: `source/app/gpu_opengl/wgl_context.cpp:14-22,663-686`

**Interfaces:**
- Consumes: `particle::defer_create_synchronization()`, `particle::synchronization()`, recursive `::mutex`, `synchronous_lock`, `approach::dummy_wgl_context()`, `wgl_context::select()`, and `wgl_context::unselect()`.
- Produces: thread-safe `approach::dummy_wgl_context()` lazy initialization and a `scoped_dummy_wgl_context` whose lifetime exclusively owns dummy-context use.

- [x] **Step 1: Write the failing synchronization regression**

Create `source/app/gpu_opengl/tests/dummy_wgl_context_synchronization_test.cpp`:

```cpp
#include <cassert>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>


namespace
{


   std::string read_text(const std::filesystem::path & path)
   {

      std::ifstream stream(path, std::ios::binary);
      assert(stream.is_open());

      std::ostringstream output;
      output << stream.rdbuf();
      return output.str();

   }


   std::string function_body(
      const std::string & source,
      const std::string & signature,
      const std::string & nextSignature)
   {

      const auto begin = source.find(signature);
      assert(begin != std::string::npos);

      const auto end = source.find(nextSignature, begin + signature.size());
      assert(end != std::string::npos);

      return source.substr(begin, end - begin);

   }


} // namespace


int main()
{

   const auto testPath = std::filesystem::absolute(__FILE__);
   const auto gpuOpenGlPath = testPath.parent_path().parent_path();

   const auto approach = read_text(gpuOpenGlPath / "approach.cpp");
   const auto wglHeader = read_text(gpuOpenGlPath / "wgl_context.h");
   const auto wglSource = read_text(gpuOpenGlPath / "wgl_context.cpp");

   const auto initialize = function_body(
      approach,
      "void approach::initialize(",
      "void approach::defer_init_gpu_library(");

   assert(initialize.find("defer_create_synchronization();") !=
      std::string::npos);

   const auto getter = function_body(
      approach,
      "approach::dummy_wgl_context()",
      "//void approach::gpu_on_before_create_window");

   const auto getterLock = getter.find(
      "synchronous_lock synchronouslock(this->synchronization()");
   const auto getterCheck = getter.find("if (!m_pwglcontextDummy)");
   const auto getterCreate = getter.find(
      "m_pwglcontextDummy->create_dummy_wgl_context();");

   assert(getterLock != std::string::npos);
   assert(getterCheck != std::string::npos);
   assert(getterCreate != std::string::npos);
   assert(getterLock < getterCheck);
   assert(getterCheck < getterCreate);

   const auto createContext = function_body(
      wglSource,
      "void wgl_context::_create_wgl_context(",
      "void wgl_context::create_offscreen_wgl_context(");

   const auto shareLock = createContext.find(
      "synchronous_lock synchronouslock(pgpuapproach->synchronization()");
   const auto shareRead = createContext.find("pgpuapproach->m_hglrcShare");
   const auto shareWrite = createContext.find(
      "pgpuapproach->m_hglrcShare = hglrc;");

   assert(shareLock != std::string::npos);
   assert(shareRead != std::string::npos);
   assert(shareWrite != std::string::npos);
   assert(shareLock < shareRead);
   assert(shareRead < shareWrite);

   assert(wglHeader.find(
      "#include \"acme/parallelization/synchronous_lock.h\"") !=
      std::string::npos);
   assert(wglHeader.find(
      "::pointer < ::gpu_opengl::approach > m_pgpuapproach;") !=
      std::string::npos);
   assert(wglHeader.find("synchronous_lock m_synchronouslock;") !=
      std::string::npos);

   const auto scopedConstructor = function_body(
      wglSource,
      "scoped_dummy_wgl_context::scoped_dummy_wgl_context(",
      "scoped_dummy_wgl_context::~scoped_dummy_wgl_context(");

   const auto approachMember = scopedConstructor.find("m_pgpuapproach(");
   const auto lifetimeLock = scopedConstructor.find(
      "m_synchronouslock(m_pgpuapproach->synchronization()");
   const auto select = scopedConstructor.find(
      "pwglcontextDummy->select();");
   const auto loadExtensions = scopedConstructor.find(
      "defer_load_wgl_extensions(pparticle);");
   const auto cleanup = scopedConstructor.find("catch (...)");
   const auto cleanupUnselect = scopedConstructor.find(
      "pwglcontextDummy->unselect();", cleanup);

   assert(approachMember != std::string::npos);
   assert(lifetimeLock != std::string::npos);
   assert(select != std::string::npos);
   assert(loadExtensions != std::string::npos);
   assert(cleanup != std::string::npos);
   assert(cleanupUnselect != std::string::npos);
   assert(approachMember < lifetimeLock);
   assert(lifetimeLock < select);
   assert(select < loadExtensions);

   const auto scopedDestructor = wglSource.substr(
      wglSource.find("scoped_dummy_wgl_context::~scoped_dummy_wgl_context("));

   assert(scopedDestructor.find(
      "m_pgpuapproach->dummy_wgl_context()->unselect();") !=
      std::string::npos);

   return 0;

}
```

- [x] **Step 2: Compile and run the regression to verify RED**

Run from `C:\Users\camilo\SceneFoundry\main\source\app` in Visual Studio Developer PowerShell:

```powershell
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\dummy_wgl_context_synchronization_test.cpp /Fe:dummy_wgl_context_synchronization_test.exe
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\dummy_wgl_context_synchronization_test.exe
```

Expected: compilation succeeds and execution fails at the first missing synchronization assertion, because `approach::initialize()` does not yet call `defer_create_synchronization()`.

- [x] **Step 3: Initialize and use the approach synchronization in the getter**

In `source/app/gpu_opengl/approach.cpp`, add synchronization initialization after the base initialization:

```cpp
   void approach::initialize(::particle * pparticle)
   {

      ::object::initialize(pparticle);

      defer_create_synchronization();

      if (m_papplication->m_gpu.m_bUseSwapChainWindow)
```

Lock the complete lazy getter body with the recursive approach synchronization:

```cpp
   ::gpu_opengl::wgl_context * approach::dummy_wgl_context()
   {

      synchronous_lock synchronouslock(this->synchronization(), DEFAULT_SYNCHRONOUS_LOCK_SUFFIX);

      if (!m_pwglcontextDummy)
      {

         construct_newø(m_pwglcontextDummy);

         m_pwglcontextDummy->create_dummy_wgl_context();

      }

      return m_pwglcontextDummy;

   }
```

- [x] **Step 4: Add the lifetime lock state to `scoped_dummy_wgl_context`**

In `source/app/gpu_opengl/wgl_context.h`, include the lock definition:

```cpp
#include "acme/parallelization/synchronous_lock.h"
```

Forward-declare the approach before `wgl_context`:

```cpp
   class approach;
```

Add the approach pointer before the lock member so C++ initialization order makes the approach available to the lock constructor:

```cpp
      ::particle * m_pparticle;
      ::pointer < ::gpu_opengl::approach > m_pgpuapproach;
      synchronous_lock m_synchronouslock;
```

- [x] **Step 5: Retain the recursive approach lock across select/use/unselect**

In `source/app/gpu_opengl/wgl_context.cpp`, add a file-local checked approach resolver inside `namespace gpu_opengl`:

```cpp
   static ::gpu_opengl::approach * opengl_approach(::particle * pparticle)
   {

      ::cast < ::gpu_opengl::approach > pgpuapproach =
         pparticle->m_papplication->gpu_approach();

      if (!pgpuapproach)
      {

         throw ::exception(
            error_wrong_state,
            "The active GPU approach is not gpu_opengl::approach.");

      }

      return pgpuapproach;

   }
```

Initialize the approach member first and the lifetime lock second. Clean up the selected context if extension loading throws:

```cpp
   scoped_dummy_wgl_context::scoped_dummy_wgl_context(::particle * pparticle) :
      m_pparticle(pparticle),
      m_pgpuapproach(opengl_approach(pparticle)),
      m_synchronouslock(m_pgpuapproach->synchronization(), pparticle, SYNCHRONOUS_LOCK_SUFFIX)
   {

      auto pwglcontextDummy = m_pgpuapproach->dummy_wgl_context();

      pwglcontextDummy->select();

      try
      {

         defer_load_wgl_extensions(pparticle);

      }
      catch (...)
      {

         pwglcontextDummy->unselect();

         throw;

      }

   }


   scoped_dummy_wgl_context::~scoped_dummy_wgl_context()
   {

      m_pgpuapproach->dummy_wgl_context()->unselect();

   }
```

The recursive `::mutex` permits the getter calls in both constructor and destructor while `m_synchronouslock` is held. Member destruction happens after the destructor body, so unselection precedes unlocking.

- [x] **Step 6: Normalize modified source files to CRLF**

Run from `C:\Users\camilo\SceneFoundry\main`:

```powershell
$paths = @(
  'source\app\gpu_opengl\approach.cpp',
  'source\app\gpu_opengl\wgl_context.cpp',
  'source\app\gpu_opengl\wgl_context.h',
  'source\app\gpu_opengl\tests\dummy_wgl_context_synchronization_test.cpp'
)
foreach ($path in $paths) {
  $full = (Resolve-Path -LiteralPath $path).Path
  $content = [System.IO.File]::ReadAllText($full)
  $content = $content -replace "`r?`n", "`r`n"
  [System.IO.File]::WriteAllText($full, $content, [System.Text.UTF8Encoding]::new($false))
}
```

In `wgl_context::_create_wgl_context()`, protect the complete `m_hglrcShare` transaction with the same recursive approach synchronization:

```cpp
   void wgl_context::_create_wgl_context(::i32 * contextAttribs)
   {

      ::cast<approach> pgpuapproach = m_papplication->get_gpu_approach();

      synchronous_lock synchronouslock(pgpuapproach->synchronization(), DEFAULT_SYNCHRONOUS_LOCK_SUFFIX);

      auto hglrc = wglCreateContextAttribsARB(
         m_hdc,
         pgpuapproach->m_hglrcShare,
         contextAttribs);
```

Keep the existing null check and first assignment inside this function so they remain within the lock lifetime.

- [x] **Step 7: Compile and run the regression to verify GREEN**

Run from `C:\Users\camilo\SceneFoundry\main\source\app`:

```powershell
cl /nologo /std:c++20 /EHsc gpu_opengl\tests\dummy_wgl_context_synchronization_test.cpp /Fe:dummy_wgl_context_synchronization_test.exe
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\dummy_wgl_context_synchronization_test.exe
```

Expected: exit code `0` with no assertion failures.

- [x] **Step 8: Build the Windows OpenGL GPU target**

Run from `C:\Users\camilo\SceneFoundry\main`:

```powershell
& 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe' solution-windows\SceneFoundry.sln /t:gpu_opengl /p:Configuration=Debug /p:Platform=x64 /p:BuildProjectReferences=false /m:1 /nodeReuse:false /nologo /v:minimal
```

Expected: `gpu_opengl.vcxproj` compiles and links successfully. If generated configuration is missing, first run the same command without `/p:BuildProjectReferences=false`; unrelated dependency/PDB-lock failures must be reported separately rather than attributed to this change.

- [x] **Step 9: Check source hygiene and remove generated test artifacts**

Run:

```powershell
git -C source/app diff --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$testArtifacts = @(
  'C:\Users\camilo\SceneFoundry\main\source\app\dummy_wgl_context_synchronization_test.exe',
  'C:\Users\camilo\SceneFoundry\main\source\app\dummy_wgl_context_synchronization_test.obj'
)
foreach ($path in $testArtifacts) {
  if ([System.IO.Path]::GetDirectoryName($path) -ne
      'C:\Users\camilo\SceneFoundry\main\source\app') {
    throw "Refusing to remove unexpected path: $path"
  }
  [System.IO.File]::Delete($path)
}
```

Expected: diff check exits `0`, and generated standalone-test artifacts are absent from `git -C source/app status --short`.

- [ ] **Step 10: Runtime verification checkpoint**

Run an OpenGL application path that populates the font list with multiple concurrent workers and creates multiple memory drawing contexts.

Expected:

- no `context already selected in this or other thread` exception;
- no `context already selected on other thread` exception;
- no `context not selected` exception;
- font enumeration and memory-context creation complete normally;
- normal rendering remains concurrent after WGL bootstrap.

- [ ] **Step 11: Commit after runtime confirmation**

From `C:\Users\camilo\SceneFoundry\main\source\app`, stage only the scoped files:

```powershell
git add -- gpu_opengl/approach.cpp gpu_opengl/wgl_context.cpp gpu_opengl/wgl_context.h gpu_opengl/tests/dummy_wgl_context_synchronization_test.cpp
git diff --cached --check
git commit -m "Synchronize shared dummy WGL context"
```

Expected: one nested `source/app` commit containing only the dummy-context synchronization and its focused regression. Do not stage unrelated files from the root, `source`, or `source/app-graphics3d` repositories.
