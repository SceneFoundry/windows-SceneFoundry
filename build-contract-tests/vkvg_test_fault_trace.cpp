#include <windows.h>
#include <dbghelp.h>
#include <cstdio>

static LONG WINAPI fault(EXCEPTION_POINTERS *p) {
    HANDLE process = GetCurrentProcess();
    SymSetOptions(SYMOPT_LOAD_LINES | SYMOPT_UNDNAME);
    SymInitialize(process, nullptr, TRUE);
    CONTEXT context = *p->ContextRecord;
    STACKFRAME64 frame{};
    frame.AddrPC.Offset = context.Rip;
    frame.AddrStack.Offset = context.Rsp;
    frame.AddrFrame.Offset = context.Rbp;
    frame.AddrPC.Mode = frame.AddrStack.Mode = frame.AddrFrame.Mode = AddrModeFlat;
    std::fprintf(stderr, "Exception %lx at %p\n", p->ExceptionRecord->ExceptionCode, p->ExceptionRecord->ExceptionAddress);
    for (unsigned n = 0; n < 20; ++n) {
        char buffer[sizeof(SYMBOL_INFO) + MAX_SYM_NAME]{};
        auto symbol = reinterpret_cast<SYMBOL_INFO *>(buffer);
        symbol->SizeOfStruct = sizeof(SYMBOL_INFO);
        symbol->MaxNameLen = MAX_SYM_NAME;
        DWORD64 displacement = 0;
        IMAGEHLP_LINE64 line{};
        line.SizeOfStruct = sizeof(line);
        DWORD offset = 0;
        if (SymFromAddr(process, frame.AddrPC.Offset, &displacement, symbol))
            std::fprintf(stderr, "%s + %llu", symbol->Name, displacement);
        else
            std::fprintf(stderr, "%llx", frame.AddrPC.Offset);
        if (SymGetLineFromAddr64(process, frame.AddrPC.Offset, &offset, &line))
            std::fprintf(stderr, " %s:%lu", line.FileName, line.LineNumber);
        std::fputc('\n', stderr);
        if (!StackWalk64(IMAGE_FILE_MACHINE_AMD64, process, GetCurrentThread(), &frame, &context,
                        nullptr, SymFunctionTableAccess64, SymGetModuleBase64, nullptr))
            break;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}
struct install_fault_trace {
    install_fault_trace() { SetUnhandledExceptionFilter(fault); }
} install;
