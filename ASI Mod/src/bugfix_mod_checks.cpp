#include "stdafx.h"
#include "bugfix_mod_checks.hpp"

#include "common.hpp"
#include "logging.hpp"
#include "version.h"


namespace
{

    struct ModWarningCache
    {
        std::wstring installPath;
        std::wstring installDate;
        std::wstring fixVersion;
        std::unordered_map<std::string, uint32_t> warnCounts;
    };


    std::wstring GetWindowsInstallDate()
    {
        HKEY hKey;
        if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", 0, KEY_READ, &hKey) != ERROR_SUCCESS)
            return L"";

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

    ModWarningCache LoadCache(const std::filesystem::path& file)
    {
        ModWarningCache data;
        if (!std::filesystem::exists(file))
            return data;

        std::ifstream f(file, std::ios::binary);
        if (!f)
            return data;

        uint32_t pathLen = 0, dateLen = 0, verLen = 0, entryCount = 0;

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

        f.read(reinterpret_cast<char*>(&verLen), sizeof(verLen));
        if (verLen)
        {
            std::vector<wchar_t> buf(verLen);
            f.read(reinterpret_cast<char*>(buf.data()), verLen * sizeof(wchar_t));
            data.fixVersion.assign(buf.begin(), buf.end());
        }

        f.read(reinterpret_cast<char*>(&entryCount), sizeof(entryCount));
        for (uint32_t i = 0; i < entryCount; ++i)
        {
            uint32_t keyLen = 0;
            f.read(reinterpret_cast<char*>(&keyLen), sizeof(keyLen));
            std::string key(keyLen, '\0');
            f.read(key.data(), keyLen);

            uint32_t count = 0;
            f.read(reinterpret_cast<char*>(&count), sizeof(count));
            data.warnCounts[key] = count;
        }

        return data;
    }

    void SaveCache(const std::filesystem::path& file, const ModWarningCache& data)
    {
        std::ofstream f(file, std::ios::binary | std::ios::trunc);
        if (!f)
            return;

        uint32_t pathLen = static_cast<uint32_t>(data.installPath.size());
        uint32_t dateLen = static_cast<uint32_t>(data.installDate.size());
        uint32_t verLen = static_cast<uint32_t>(data.fixVersion.size());
        uint32_t entryCount = static_cast<uint32_t>(data.warnCounts.size());

        f.write(reinterpret_cast<const char*>(&pathLen), sizeof(pathLen));
        f.write(reinterpret_cast<const char*>(data.installPath.data()), pathLen * sizeof(wchar_t));

        f.write(reinterpret_cast<const char*>(&dateLen), sizeof(dateLen));
        f.write(reinterpret_cast<const char*>(data.installDate.data()), dateLen * sizeof(wchar_t));

        f.write(reinterpret_cast<const char*>(&verLen), sizeof(verLen));
        f.write(reinterpret_cast<const char*>(data.fixVersion.data()), verLen * sizeof(wchar_t));

        f.write(reinterpret_cast<const char*>(&entryCount), sizeof(entryCount));
        for (const auto& [key, count] : data.warnCounts)
        {
            uint32_t keyLen = static_cast<uint32_t>(key.size());
            f.write(reinterpret_cast<const char*>(&keyLen), sizeof(keyLen));
            f.write(key.data(), keyLen);
            f.write(reinterpret_cast<const char*>(&count), sizeof(count));
        }
    }

    bool ShouldWarn(ModWarningCache& cache, const std::string& key, uint32_t maxWarnings)
    {
        const auto it = cache.warnCounts.find(key);
        const uint32_t count = (it != cache.warnCounts.end()) ? it->second : 0;
        return count < maxWarnings;
    }


    void RecordWarning(ModWarningCache& cache, const std::filesystem::path& file, const std::string& key)
    {
        cache.warnCounts[key]++;
        SaveCache(file, cache);
    }


}



void VerifyInstallation::Check()
{

    const auto cacheFile = sGameSavePath / "AfevisMGS2Bugfix_Mod_Warnings.bin";
    ModWarningCache cache = LoadCache(cacheFile);

    const auto curPath = std::filesystem::current_path().wstring();
    const auto curDate = GetWindowsInstallDate();
    const std::wstring curVersion(sFixVersion.begin(), sFixVersion.end());

    if (cache.installPath != curPath || cache.installDate != curDate || cache.fixVersion != curVersion)
    {
        spdlog::debug("Resetting mod warning cache (environment or version changed)");
        cache.warnCounts.clear();
        cache.installPath = curPath;
        cache.installDate = curDate;
        cache.fixVersion = curVersion;
    }

    // ------------------------------------------------------
    // MGS2: Verify Afevis Bugfix Collection based installation
    // ------------------------------------------------------

    if (const std::filesystem::path afevisBugfixTestPathOne = sExePath / "textures" / "flatlist" / "win" / "col_orange2.bmp.ctxr"; std::filesystem::exists(afevisBugfixTestPathOne) && !Util::SHA1Check(afevisBugfixTestPathOne, "11d03110d40b42adeafde2fa5f5cf65f27d6fc52"))
    {
        spdlog::warn("------------------- ! Afevis Bugfix Compilation (Base) Missing ! -------------------");
        //base installation either missing or overwritten by steam updates, yell at the user to reinstall.

        if (constexpr uint32_t maxWarnings = 3; ShouldWarn(cache, "MGS2_AfevisBugFixCompilation", maxWarnings))
        {
            spdlog::warn("------------------- ! Better Audio Mod Missing ! -------------------");
            MessageBoxA(
                nullptr,
                "Warning:",
                "MGSHDFix - Crash Warning",
                MB_ICONWARNING | MB_OK
            );
            RecordWarning(cache, cacheFile, "MGS2_AfevisBugFixCompilation");
        }
        else
        {
            spdlog::warn("Skipped MGS2 Better Audio pop-up warning (already shown {} times)", maxWarnings);
            spdlog::warn("------------------- ! Better Audio Mod Missing ! -------------------");
        }
    }



    // ------------------------------------------------------
    // MGS2: Check if liqmix AI slop packs are installed
    // ------------------------------------------------------

    if (const std::filesystem::path col_orange2Test = sExePath / "textures" / "flatlist" / "ovr_stm" / "win" / "col_orange2.bmp.ctxr"; std::filesystem::exists(col_orange2Test) && (Util::SHA1Check(col_orange2Test, "96ba1191c0da112d355bf510dcb3828f1183d1b5") || Util::SHA1Check(col_orange2Test, "4ecda248b079ee426262a23b64df6cb05a249088")))
    {
        spdlog::warn("------------------- ! Afevis Bugfix Compilation (Base) Missing ! -------------------");

        if (constexpr uint32_t maxWarnings = 3; ShouldWarn(cache, "MGS2_AfevisBugFixCompilation", maxWarnings))
        {
            spdlog::warn("------------------- ! Better Audio Mod Missing ! -------------------");
            MessageBoxA(
                nullptr,
                "Warning:",
                "MGSHDFix - Crash Warning",
                MB_ICONWARNING | MB_OK
            );
            RecordWarning(cache, cacheFile, "MGS2_AfevisBugFixCompilation");
        }
        else
        {
            spdlog::warn("Skipped MGS2 Better Audio pop-up warning (already shown {} times)", maxWarnings);
            spdlog::warn("------------------- ! Better Audio Mod Missing ! -------------------");
        }
    }


}
