#include "stdafx.h"
#include "bugfix_mod_checks.hpp"

#include "common.hpp"
#include "logging.hpp"
#include "version.h"


namespace
{
    // ==========================================================
    // POLICY
    // ==========================================================
    struct WarningPolicy
    {
        uint32_t initialWarningCount = 3; // initial warning phase budget
        uint32_t cooldownDays = 30;       // after initial phase, allow 1 warning per cooldownDays
    };

    // ==========================================================
    // CACHE
    // ==========================================================
    constexpr uint32_t kCacheMagic = 'ABFC'; // Mod Warning Cache File
    constexpr uint32_t kCacheVersion = 3;

    struct WarningEntry
    {
        uint32_t shownCount = 0;           // total times shown (monotonic)
        uint64_t lastShownUnix = 0;        // seconds since epoch (when we actually showed it)
        bool initialPhaseComplete = false; // true once initial warning phase is exhausted
    };

    struct ModWarningCache
    {
        std::wstring installPath;
        std::wstring installDate;
        std::unordered_map<std::string, WarningEntry> warn;
    };

    uint64_t NowUnixSeconds()
    {
        using namespace std::chrono;
        return static_cast<uint64_t>(duration_cast<seconds>(system_clock::now().time_since_epoch()).count());
    }

    uint64_t DaysToSeconds(uint32_t days)
    {
        return static_cast<uint64_t>(days) * 24ull * 60ull * 60ull;
    }

    std::wstring GetWindowsInstallDate()
    {
        HKEY hKey;
        if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", 0, KEY_READ, &hKey) != ERROR_SUCCESS)
        {
            return L"";
        }

        DWORD installDate = 0;
        DWORD size = sizeof(installDate);

        if (RegQueryValueExW(hKey, L"InstallDate", nullptr, nullptr, reinterpret_cast<LPBYTE>(&installDate), &size) != ERROR_SUCCESS)
        {
            RegCloseKey(hKey);
            return L"";
        }

        RegCloseKey(hKey);

        wchar_t buf[64];
        swprintf_s(buf, L"%u", installDate);
        return buf;
    }

    // ==========================================================
    // LOAD/SAVE
    // ==========================================================
    static ModWarningCache LoadCache(const std::filesystem::path& file)
    {
        ModWarningCache data;

        if (!std::filesystem::exists(file))
            return data;

        std::ifstream f(file, std::ios::binary);
        if (!f)
            return data;

        uint32_t magic = 0;
        uint32_t version = 0;

        f.read(reinterpret_cast<char*>(&magic), sizeof(magic));
        f.read(reinterpret_cast<char*>(&version), sizeof(version));

        if (!f || magic != kCacheMagic || version != kCacheVersion)
        {
            // Wrong file or incompatible version: start clean.
            return ModWarningCache {};
        }

        uint32_t pathLen = 0;
        uint32_t dateLen = 0;
        uint32_t entryCount = 0;

        f.read(reinterpret_cast<char*>(&pathLen), sizeof(pathLen));
        if (pathLen)
        {
            std::vector<wchar_t> buf(pathLen);
            f.read(reinterpret_cast<char*>(buf.data()), pathLen * sizeof(wchar_t));
            data.installPath.assign(buf.begin(), buf.end());
        }

        f.read(reinterpret_cast<char*>(&dateLen), sizeof(dateLen));
        if (dateLen)
        {
            std::vector<wchar_t> buf(dateLen);
            f.read(reinterpret_cast<char*>(buf.data()), dateLen * sizeof(wchar_t));
            data.installDate.assign(buf.begin(), buf.end());
        }

        f.read(reinterpret_cast<char*>(&entryCount), sizeof(entryCount));

        for (uint32_t i = 0; i < entryCount; ++i)
        {
            uint32_t keyLen = 0;
            f.read(reinterpret_cast<char*>(&keyLen), sizeof(keyLen));

            std::string key(keyLen, '\0');
            f.read(key.data(), keyLen);

            WarningEntry e;
            f.read(reinterpret_cast<char*>(&e.shownCount), sizeof(e.shownCount));
            f.read(reinterpret_cast<char*>(&e.lastShownUnix), sizeof(e.lastShownUnix));

            uint8_t phaseComplete = 0;
            f.read(reinterpret_cast<char*>(&phaseComplete), sizeof(phaseComplete));
            e.initialPhaseComplete = (phaseComplete != 0);

            data.warn[key] = e;
        }

        return data;
    }

    static void SaveCache(const std::filesystem::path& file, const ModWarningCache& data)
    {
        std::ofstream f(file, std::ios::binary | std::ios::trunc);
        if (!f)
            return;

        f.write(reinterpret_cast<const char*>(&kCacheMagic), sizeof(kCacheMagic));
        f.write(reinterpret_cast<const char*>(&kCacheVersion), sizeof(kCacheVersion));

        const uint32_t pathLen = static_cast<uint32_t>(data.installPath.size());
        const uint32_t dateLen = static_cast<uint32_t>(data.installDate.size());
        const uint32_t entryCount = static_cast<uint32_t>(data.warn.size());

        f.write(reinterpret_cast<const char*>(&pathLen), sizeof(pathLen));
        if (pathLen)
            f.write(reinterpret_cast<const char*>(data.installPath.data()), pathLen * sizeof(wchar_t));

        f.write(reinterpret_cast<const char*>(&dateLen), sizeof(dateLen));
        if (dateLen)
            f.write(reinterpret_cast<const char*>(data.installDate.data()), dateLen * sizeof(wchar_t));

        f.write(reinterpret_cast<const char*>(&entryCount), sizeof(entryCount));

        for (const auto& kv : data.warn)
        {
            const std::string& key = kv.first;
            const WarningEntry& e = kv.second;

            const uint32_t keyLen = static_cast<uint32_t>(key.size());
            f.write(reinterpret_cast<const char*>(&keyLen), sizeof(keyLen));
            f.write(key.data(), keyLen);

            f.write(reinterpret_cast<const char*>(&e.shownCount), sizeof(e.shownCount));
            f.write(reinterpret_cast<const char*>(&e.lastShownUnix), sizeof(e.lastShownUnix));

            const uint8_t phaseComplete = e.initialPhaseComplete ? 1u : 0u;
            f.write(reinterpret_cast<const char*>(&phaseComplete), sizeof(phaseComplete));
        }
    }

    // ==========================================================
    // MESSAGE HELPERS
    // ==========================================================
    static std::string BuildInitialPhaseTail(uint32_t remainingAfterThis)
    {
        if (remainingAfterThis > 0)
        {
            return "(This warning will be hidden after " + std::to_string(remainingAfterThis) + " more launch" + (remainingAfterThis == 1 ? "" : "es") + ".)";
        }

        return "(This is the final warning before cooldown.)";
    }

    static std::string BuildCooldownTail(uint32_t cooldownDays)
    {
        return "(This reminder will appear at most once every " +
            std::to_string(cooldownDays) + " days.)";
    }

    // ==========================================================
    // WARNING LOGIC
    // ==========================================================
    static uint32_t GetWarningsRemaining(ModWarningCache& cache, const std::string& key, const WarningPolicy& policy)
    {
        const auto it = cache.warn.find(key);
        if (it == cache.warn.end())
        {
            return policy.initialWarningCount;
        }

        WarningEntry& e = it->second;

        if (!e.initialPhaseComplete)
        {
            const uint32_t used = (e.shownCount >= policy.initialWarningCount) ? policy.initialWarningCount : e.shownCount;
            return policy.initialWarningCount - used;
        }

        const uint64_t now = NowUnixSeconds();
        return (e.lastShownUnix == 0 || now >= e.lastShownUnix + DaysToSeconds(policy.cooldownDays)) ? 1u : 0u;
    }

    static bool ShouldWarn(ModWarningCache& cache, const std::string& key, const WarningPolicy& policy)
    {
        return GetWarningsRemaining(cache, key, policy) > 0;
    }

    static void RecordWarning(ModWarningCache& cache, const std::filesystem::path& file, const std::string& key, const WarningPolicy& policy)
    {
        WarningEntry& e = cache.warn[key];

        if (!e.initialPhaseComplete)
        {
            const uint32_t used = (e.shownCount >= policy.initialWarningCount) ? policy.initialWarningCount : e.shownCount;

            if (used + 1 >= policy.initialWarningCount)
            {
                e.initialPhaseComplete = true;
            }
        }

        e.shownCount++;
        e.lastShownUnix = NowUnixSeconds();

        SaveCache(file, cache);
    }

    static void HardResetIfEnvironmentChanged(ModWarningCache& cache, const std::filesystem::path& file)
    {
        const std::wstring curPath = std::filesystem::current_path().wstring();
        const std::wstring curDate = GetWindowsInstallDate();

        if (cache.installPath == curPath && cache.installDate == curDate)
        {
            return;
        }

        spdlog::info("Resetting mod warning cache (environment changed)");

        cache.warn.clear();
        cache.installPath = curPath;
        cache.installDate = curDate;

        SaveCache(file, cache);
    }
}



void VerifyInstallation::Check()
{

    const WarningPolicy policy { 3, 1 };

    const auto cacheFile = sGameSavePath / "AfevisMGS2Bugfix_Mod_Warnings.bin";
    ModWarningCache cache = LoadCache(cacheFile);

    HardResetIfEnvironmentChanged(cache, cacheFile);


    // ------------------------------------------------------
    // MGS2: Verify Afevis Bugfix Collection based installation
    // ------------------------------------------------------

    if (const std::filesystem::path afevisBugfixTestPathOne = sExePath / "textures" / "flatlist" / "_win" / "col_orange2.bmp.ctxr"; std::filesystem::exists(afevisBugfixTestPathOne) && !Util::SHA1Check(afevisBugfixTestPathOne, "11d03110d40b42adeafde2fa5f5cf65f27d6fc52"))
    {
        const std::string key = "AfevisMGS2Bugfix_Base";

        spdlog::warn("------------------- ! Afevis Bugfix Compilation (Base) Missing ! -------------------");
        const uint32_t remaining = GetWarningsRemaining(cache, key, policy);

        if (ShouldWarn(cache, key, policy))
        {
            const bool inInitialPhase = !cache.warn[key].initialPhaseComplete;

            std::string message;
            if (inInitialPhase)
            {
                const uint32_t remainingAfterThis = (remaining > 0) ? (remaining - 1) : 0;
                message =
                    "Warning: base corruption\n"
                    "\n"
                    "Would you like to open the mod page now?\n"
                    "\n" +
                    BuildInitialPhaseTail(remainingAfterThis);
            }
            else
            {
                message =
                    "Reminder: The MGS2 Better Audio mod is not currently installed.\n"
                    "\n"
                    "This mod fixes a critical hang/crash that occurs very late into the game.\n"
                    "It is HIGHLY recommended to install the mod, otherwise you will most likely be unable to finish the game.\n"
                    "\n"
                    "Would you like to open the mod page now?\n"
                    "\n" +
                    BuildCooldownTail(policy.cooldownDays);
            }

            spdlog::warn(message);
            if (int result = MessageBoxA(
                nullptr,
                message.c_str(),
                "MGSHDFix - Bugfix Warning",
                MB_ICONWARNING | MB_YESNO);
                result == IDYES)
            {
                ShellExecuteA(
                    nullptr,
                    "open",
                    "https://www.nexusmods.com/metalgearsolid2mc/mods/3",
                    nullptr,
                    nullptr,
                    SW_SHOWNORMAL
                );
            }

            RecordWarning(cache, cacheFile, key, policy);
        }

    }



    // ------------------------------------------------------
    // MGS2: Check if liqmix AI slop packs are installed
    // ------------------------------------------------------

    if (const std::filesystem::path col_orange2Test = sExePath / "textures" / "flatlist" / "ovr_stm" / "_win" / "col_orange2.bmp.ctxr"; std::filesystem::exists(col_orange2Test) && (Util::SHA1Check(col_orange2Test, "96ba1191c0da112d355bf510dcb3828f1183d1b5") || Util::SHA1Check(col_orange2Test, "4ecda248b079ee426262a23b64df6cb05a249088")))
    {
        const std::string key = "LiqMixAISlop";

        spdlog::warn("------------------- ! Afevis Bugfix Compilation (Base) Missing ! -------------------");
        const uint32_t remaining = GetWarningsRemaining(cache, key, policy);

        if (ShouldWarn(cache, key, policy))
        {
            const bool inInitialPhase = !cache.warn[key].initialPhaseComplete;

            std::string message;
            if (inInitialPhase)
            {
                const uint32_t remainingAfterThis = (remaining > 0) ? (remaining - 1) : 0;
                message =
                    "Warning: liqmix\n\
                    n" +
                    BuildInitialPhaseTail(remainingAfterThis);
            }
            else
            {
                message =
                    "Reminder: liqmix\n"
                    "\n" +
                    BuildCooldownTail(policy.cooldownDays);
            }

            spdlog::warn(message);
            if (int result = MessageBoxA(
                nullptr,
                message.c_str(),
                "MGSHDFix - Bugfix Warning",
                MB_ICONWARNING | MB_YESNO);
                result == IDYES)
            {
                ShellExecuteA(
                    nullptr,
                    "open",
                    "https://www.nexusmods.com/metalgearsolid2mc/mods/3",
                    nullptr,
                    nullptr,
                    SW_SHOWNORMAL
                );
            }

            RecordWarning(cache, cacheFile, key, policy);
        }


    }
}
