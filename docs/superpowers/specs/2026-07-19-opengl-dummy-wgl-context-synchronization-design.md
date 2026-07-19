# OpenGL Dummy and Share-Root WGL Context Synchronization Design

## Problem

On Windows, `gpu_opengl::approach` owns one lazily created dummy WGL context. Both window and offscreen WGL-context creation use `scoped_dummy_wgl_context`, which selects this shared context during bootstrap and unselects it when the scope ends.

Font-list layout can create multiple memory drawing contexts concurrently. That path reaches the dummy context through:

`font_list worker -> create_memory_graphics() -> create_draw2d_context() -> create_offscreen_wgl_context() -> scoped_dummy_wgl_context`

Without synchronization, two threads can overlap `select/use/unselect` operations on the same dummy context. The mutable task ownership fields in `wgl_context` and the WGL current-context state therefore race.

The existing `m_hglrcShare` ownership also points at the first ordinary rendering context. Serializing the handle read and assignment does not prevent that rendering context from being current on another GPU thread when a later context is created. Windows then reports `ERROR_BUSY` (`170`) from `wglCreateContextAttribsARB`. The raw alias can also outlive the ordinary context that owns and deletes the handle.

## Design

Use the existing `gpu_opengl::approach` synchronization object, backed by recursive `::mutex`, as the single lock for the dummy WGL context.

1. Ensure the approach creates its synchronization object during initialization.
2. Lock the approach synchronization inside `approach::dummy_wgl_context()` so lazy construction and publication of `m_pwglcontextDummy` happen once and are thread-safe.
3. Make `scoped_dummy_wgl_context` retain a lock on the same approach synchronization for its complete lifetime.
4. Perform operations in this order:
   - acquire the recursive approach lock for exclusive use;
   - obtain or create the dummy context, re-entering the same `::mutex` through the getter when necessary;
   - select it on the current thread;
   - load the required WGL/OpenGL entry points when needed;
   - perform the caller's WGL bootstrap work;
   - unselect it on the same thread;
   - release the approach lock.
5. If extension loading fails after selection, unselect the dummy context before propagating the exception.
6. Lock the same recursive approach `::mutex` directly inside `wgl_context::_create_wgl_context()`.
7. Treat `approach::m_hglrcShare` as a dedicated share-root context owned by the approach, never as an alias to an ordinary rendering context:
   - on the first ordinary context creation, create the root with `wglCreateContextAttribsARB(m_hdc, nullptr, contextAttribs)`;
   - never assign the root to `wgl_context::m_hglrc`;
   - never select the root or use it for rendering;
   - create the first and every later ordinary context with the root as `hShareContext`;
   - retain the root even if an ordinary child creation fails, so a later creation attempt can reuse it;
   - delete the root in `approach::~approach()` under the same recursive mutex and clear the handle.
8. Distinguish root-creation failure from ordinary child-context failure in exception messages and diagnostics.

The lock covers only dummy-context initialization and WGL context bootstrap. It does not serialize normal rendering on the independently created GPU contexts.

The dedicated root may be deleted when the approach is destroyed even if child contexts are subsequently released during base/member teardown; deleting one context does not dissolve the share group while other contexts remain. No context creation may occur after approach destruction begins.

## Call Sites Covered

The current active `scoped_dummy_wgl_context` call sites are:

- `wgl_context::create_window_wgl_context()`;
- `wgl_context::create_offscreen_wgl_context()`.

`defer_load_wgl_extensions()` accesses `dummy_wgl_context()` while invoked from the scoped dummy-context constructor. Recursive `::mutex` semantics permit that getter access while the scope already owns the approach synchronization. The getter's own lock also makes direct or future lazy access safe.

## Alternatives Rejected

- Locking only `dummy_wgl_context()` would protect lazy construction but leave the shared `select/use/unselect` interval racy.
- Creating one dummy WGL context per thread would avoid sharing but add lifecycle, window, device-context, and extension-loading complexity that is not needed for bootstrap.
- Using a separate mutex would duplicate ownership semantics and could introduce lock-order problems. The requested approach synchronization is already the correct ownership boundary.
- Continuing to use the first ordinary rendering context as `m_hglrcShare` would require coordinating every rendering `select/unselect` with context creation and could serialize normal rendering.
- Using the legacy dummy context itself as the share root would couple extension bootstrap, temporary current-context state, and the resource share-group lifetime.

## Verification

- Add a focused regression that checks the approach synchronization is initialized, the getter protects lazy creation, and the scoped wrapper retains the approach lock across selection and unselection.
- Check that `_create_wgl_context()` takes the approach synchronization, creates `m_hglrcShare` with a null share parameter, and then creates every ordinary context as a child of that dedicated root.
- Check that no ordinary `hglrc` is assigned to `m_hglrcShare` and that the approach destructor deletes and clears the root under the approach mutex.
- Build the Windows `gpu_opengl` target in Debug x64 through `SceneFoundry.sln`.
- Runtime-check concurrent font-list population and creation of multiple memory drawing contexts, confirming that dummy-context ownership exceptions no longer occur.
