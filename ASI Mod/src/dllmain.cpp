#include "common.hpp"
#include "logging.hpp"
#include "submodule_initiailization.hpp"
#include "version_checking.hpp"


static bool DetectGame()
{
    eGameType = UNKNOWN;
    // Special handling for launcher.exe
    if (sExeName == "launcher.exe")
    {
        for (const auto& [type, info] : kGames)
        {
            auto gamePath = sExePath.parent_path() / info.ExeName;
            if (std::filesystem::exists(gamePath))
            {
                spdlog::info("Detected launcher for game: {} (app {})", info.GameTitle.c_str(), info.SteamAppId);
                eGameType = LAUNCHER;
                unityPlayer = GetModuleHandleA("UnityPlayer.dll");
                game = &info;
                return true;
            }
        }

        spdlog::error("Failed to detect supported game, unknown launcher");
        FreeLibraryAndExitThread(baseModule, 1);
    }

    for (const auto& [type, info] : kGames)
    {
        if (info.ExeName == sExeName)
        {
            spdlog::info("Detected game: {} (app {})", info.GameTitle.c_str(), info.SteamAppId);
            eGameType = type;
            game = &info;

            sGameSavePath = sExePath / (eGameType & MG ? "mg12_savedata_win" : eGameType & MGS2 ? "mgs2_savedata_win" : "mgs3_savedata_win");
            spdlog::info("Game Save Path: {}", sGameSavePath.string());
            if (engineModule = GetModuleHandleA("Engine.dll"); !engineModule)
            {
                spdlog::error("Failed to get Engine.dll module handle");
            }
            return true;
        }
    }

    spdlog::error("Failed to detect supported game, {} isn't supported by Afevis-MGS2-Bugfix-Compilation", sExeName.c_str());
    FreeLibraryAndExitThread(baseModule, 1);
}



static void InitializeSubsystems()
{
    //Initialization order (these systems initialize vars used by following ones.)
    INITIALIZE(g_Logging.LogSysInfo());            //0
    INITIALIZE(DetectGame());                      //1
    if (!(eGameType & LAUNCHER))
    {
        INITIALIZE(CheckForUpdates());
    }
}

std::mutex mainThreadFinishedMutex;
std::condition_variable mainThreadFinishedVar;
bool mainThreadFinished = false;

DWORD __stdcall Main(void*)
{
    g_Logging.initStartTime = std::chrono::high_resolution_clock::now();
    g_Logging.Initialize();

    INITIALIZE(InitializeSubsystems());

    // Signal any threads (e.g., the memset hook) that are waiting for initialization to finish.
    {
        std::lock_guard lock(mainThreadFinishedMutex);
        mainThreadFinished = true;
    }
    mainThreadFinishedVar.notify_all();

    return TRUE;
}

std::mutex memsetHookMutex;
bool memsetHookCalled = false;
static void* (__cdecl* memset_Fn)(void* Dst, int Val, size_t Size); // Pointer to the next function in the memset chain (could be another hook or the real CRT memset).
static void* __cdecl memset_Hook(void* Dst, int Val, size_t Size) // Our memset hook, which blocks the game's main thread until initialization is complete.
{
    std::lock_guard lock(memsetHookMutex);

    if (!memsetHookCalled)
    {
        memsetHookCalled = true;

        // Restore the original (or previously-hooked) memset in the IAT.
        // This ensures future memset calls bypass our hook and run at full speed.
        Memory::WriteIAT(baseModule, "VCRUNTIME140.dll", "memset", memset_Fn);

        // Block the current thread here until our main initialization is complete.
        std::unique_lock finishedLock(mainThreadFinishedMutex);
        mainThreadFinishedVar.wait(finishedLock, []
            {
                return mainThreadFinished;
            });
    }

    // Forward the memset call to the next function (another hook or the real memset).
    return reinterpret_cast<decltype(memset_Fn)>(memset_Fn)(Dst, Val, Size);
}


BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved)
{
    if (ul_reason_for_call == DLL_PROCESS_ATTACH)
    {
        DisableThreadLibraryCalls(hModule);
        HMODULE vcruntime140 = GetModuleHandleA("VCRUNTIME140.dll");
        if (vcruntime140)
        {
            // Read the current IAT entry for memset in the base module.
            // Note: it may already point to another mod's hook if they loaded first.
            void* currentIATMemset = Memory::ReadIAT(baseModule, "VCRUNTIME140.dll", "memset");

            // Save the current pointer so we can call it later (chaining to the next hook or real memset).
            memset_Fn = reinterpret_cast<decltype(memset_Fn)>(currentIATMemset);

            // Overwrite the IAT entry with our memset_Hook, so our code intercepts memset calls.
            // We always overwrite unconditionally to ensure our hook is active.
            // This will prevent other mods that also hook memset from unpausing the main thread before our Main() has finished.
            Memory::WriteIAT(baseModule, "VCRUNTIME140.dll", "memset", &memset_Hook);
        }

        // Create our main thread, which runs the initialization logic.
        if (const HANDLE mainHandle = CreateThread(nullptr, 0, Main, nullptr, CREATE_SUSPENDED, nullptr))
        {
            SetThreadPriority(mainHandle, THREAD_PRIORITY_TIME_CRITICAL); // Give our thread higher priority than the game's.
            ResumeThread(mainHandle);
            CloseHandle(mainHandle);
        }

        // Prevent monitor or system sleep while the game is running.
        SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED);
    }

    return TRUE;
}
