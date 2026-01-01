#include "stdafx.h"
#include "bugfix_mod_checks.hpp"

#include "common.hpp"
#include "logging.hpp"
#include "version.h"




void VerifyInstallation::Check()
{


    // ------------------------------------------------------
    // MGS2: Verify Afevis Bugfix Collection (base) installation
    // ------------------------------------------------------

    if (const std::filesystem::path afevisBugfixTestPathOne = sExePath / "textures" / "flatlist" / "_win" / "col_orange2.bmp.ctxr"; //verify base bugfix compilation is installed
        std::filesystem::exists(afevisBugfixTestPathOne) && !Util::SHA1Check(afevisBugfixTestPathOne, "11d03110d40b42adeafde2fa5f5cf65f27d6fc52"))
    {

        spdlog::warn("------------------- ! Community Bugfix Compilation (Base) Missing ! -------------------");
        spdlog::warn("Community Bugfix Compilation installation issue detected, base package is NOT found.");
        spdlog::warn("This can occur if Steam has verified integrity and damaged your mod files, or if the Base Bugfix Compilation zip wasn't installed.");
        spdlog::warn("The base package is required for proper functionality, even when 2x & 4x packages are installed.");
        spdlog::warn("Please install the Community Bugfix Compilation -> Base <- package to ensure proper game functionality.");
        spdlog::warn("Please visit our Nexus page at: https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files to download the base package.");
        spdlog::warn("Or our GitHub releases page at: https://github.com/ShizCalev/Afevis-MGS2-Bugfix-Compilation/releases");
        spdlog::warn("------------------- ! Community Bugfix Compilation (Base) Missing ! -------------------");
        if (int result = MessageBoxA(
            nullptr,
            "Community Bugfix Compilation installation issue detected, base package is NOT found.\n"
            "\n"
            "This can occur if Steam has verified integrity and damaged your mod files, or if the Base Bugfix Compilation zip wasn't installed.\n"
            "\n"
            "The base package is required for proper functionality, even when 2x & 4x packages are installed.\n"
            "Please install the Community Bugfix Compilation -> Base <- package to ensure proper game functionality.\n"
            "\n"
            "Would you like to open the Community Bugfix Nexus download page now to download the base package?\n"
            "(You can also find a link to our GitHub releases on the Nexus page if preferred.)",
            "Community Bugfix Compilation (Base) Missing",
            MB_ICONWARNING | MB_YESNO);
            result == IDYES)
        {
            ShellExecuteA(
                nullptr,
                "open",
                "https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files",
                nullptr,
                nullptr,
                SW_SHOWNORMAL
            );
        }
        

    }


    if (const std::filesystem::path col_orange2OvrStmTest = sExePath / "textures" / "flatlist" / "ovr_stm" / "_win" / "col_orange2.bmp.ctxr"; //upscaled texture pack installation checks
        std::filesystem::exists(col_orange2OvrStmTest))
    {

            // ------------------------------------------------------
            // MGS2: Check if liqmix AI slop packs are installed
            // ------------------------------------------------------
        if (Util::SHA1Check(col_orange2OvrStmTest, "96ba1191c0da112d355bf510dcb3828f1183d1b5") || Util::SHA1Check(col_orange2OvrStmTest, "4ecda248b079ee426262a23b64df6cb05a249088")) //liqmix 2x & 4x hashes
        {
            spdlog::warn("------------------- ! Community Bugfix Compilation - Mod Compatibility Issue ! -------------------");
            spdlog::warn("LiqMix's AI Slop AI Upscaled texture pack has been detected.");
            spdlog::warn("LiqMix's AI Slop texture pack is VERY out of date and has been damaged by the MGS2 Community Bugfix Compilation's Upscaled texture packs, which includes all the texture fixes from the base version.");
            spdlog::warn("Please uninstall LiqMix's AI Slop Upscaled texture pack to ensure proper game functionality.");
            spdlog::warn("Please visit our Nexus page at: https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files to download our upscaled texture package.");
            spdlog::warn("Or our GitHub releases page at: https://github.com/ShizCalev/Afevis-MGS2-Bugfix-Compilation/releases");
            spdlog::warn("------------------- ! Community Bugfix Compilation - Mod Compatibility Issue ! -------------------");
            if (int result = MessageBoxA(
                nullptr,
                "LiqMix's AI Slop AI Upscaled texture pack has been detected.\n"
                "LiqMix's AI Slop texture pack is VERY out of date and has been damaged by the Community Bugfix Compilation's upscaled packs, which includes all the texture fixes from the base version."
                "Please remove LiqMix's AI Slop Upscaled texture pack to ensure proper game functionality.\n"
                "\n"
                "Would you like to open the Community Bugfix Nexus download page now to download the base package?"
                "(You can also find a link to our GitHub releases on the Nexus page if preferred.)",
                "Community Bugfix Compilation (Base) Missing",
                MB_ICONWARNING | MB_YESNO);
            result == IDYES)
            {
                ShellExecuteA(
                    nullptr,
                    "open",
                    "https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files",
                    nullptr,
                    nullptr,
                    SW_SHOWNORMAL
                );
            }
        }
            // ------------------------------------------------------
            // MGS2: Verify community bugfix upscaled pack is loaded AFTER the base pack
            // ------------------------------------------------------
        else if (Util::SHA1Check(col_orange2OvrStmTest, "ecf723350dac8790e01ee7470b3e45761e79a939")) //community fix 4x is installed
        {
            if (const std::filesystem::path SelfRemade_4x_ovr_eu_seculitycard_lv2_alp = sExePath / "textures" / "flatlist" / "ovr_stm" / "ovr_eu" / "_win" / "seculitycard_lv2_alp.bmp.ctxr"; 
                std::filesystem::exists(SelfRemade_4x_ovr_eu_seculitycard_lv2_alp) && !Util::SHA1Check(SelfRemade_4x_ovr_eu_seculitycard_lv2_alp, "004e54e6d30a76394b2d801c60479fcf0c7bdb51"))
            {


                spdlog::warn("------------------- ! Community Bugfix Compilation (4x Upscaled Pack) Installation Issue ! -------------------");

                spdlog::warn("Community Bugfix Compilation 4x Texture Pack installation issue detected.");
                spdlog::warn("Unable to get the expected texture hash for seculitycard_lv2_alp in the 4x Upscaled pack. This usually means the base package was installed or loaded after the 4x pack.");
                spdlog::warn("The 4x Upscaled pack must be installed or loaded AFTER the base package.");
                spdlog::warn("Please reinstall the 4x Upscaled pack to ensure correct behavior.");
                spdlog::warn("If you are using a mod manager, make sure the 4x Upscaled pack is loaded AFTER the base package.");
                spdlog::warn("Please visit our Nexus page at: https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files to redownload the 4x upscaled package.");
                spdlog::warn("Or our GitHub releases page at: https://github.com/ShizCalev/Afevis-MGS2-Bugfix-Compilation/releases");
                spdlog::warn("------------------- ! Community Bugfix Compilation (4x Upscaled Pack) Installation Issue ! -------------------");


                if (int result = MessageBoxA(
                    nullptr,
                    "Community Bugfix Compilation 4x Texture Pack installation issue detected.\n"
                    "\n"
                    "Unable to get the expected texture hash for seculitycard_lv2_alp in the 4x Upscaled pack. This usually means the base package was installed or loaded after the 4x pack.\n"
                    "The 4x Upscaled pack must be installed or loaded AFTER the base package.\n"
                    "\n"
                    "Please reinstall the 4x Upscaled pack to ensure correct behavior."
                    "If you are using a mod manager, make sure the 4x Upscaled pack is loaded AFTER the base package."
                    "\n"
                    "Would you like to open the Community Bugfix Nexus download page now to redownload the 4x upscaled package?\n"
                    "(You can also find a link to our GitHub releases on the Nexus page if preferred.)",
                    "Community Bugfix Compilation (4x Upscale) Installation Issue",
                    MB_ICONWARNING | MB_YESNO);
                result == IDYES)
                {
                    ShellExecuteA(
                        nullptr,
                        "open",
                        "https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files",
                        nullptr,
                        nullptr,
                        SW_SHOWNORMAL
                    );
                }
            }
        }

        /*
        else if (Util::SHA1Check(col_orange2OvrStmTest, "ecf723350dac8790e01ee7470b3e45761e79a939")) //community fix 2x is installed
        {
            if (const std::filesystem::path SelfRemade_2x_ovr_eu_seculitycard_lv2_alp = sExePath / "textures" / "flatlist" / "ovr_stm" / "ovr_eu" / "_win" / "seculitycard_lv2_alp.bmp.ctxr";
                std::filesystem::exists(SelfRemade_2x_ovr_eu_seculitycard_lv2_alp) && !Util::SHA1Check(SelfRemade_2x_ovr_eu_seculitycard_lv2_alp, "004e54e6d30a76394b2d801c60479fcf0c7bdb51")) //NEEDS 2X HASH
            {


                spdlog::warn("------------------- ! Community Bugfix Compilation (2x Upscaled Pack) Installation Issue ! -------------------");

                spdlog::warn("Community Bugfix Compilation 2x Texture Pack installation issue detected.");
                spdlog::warn("Unable to get the expected texture hash for seculitycard_lv2_alp in the 2x Upscaled pack. This usually means the base package was installed or loaded after the 2x pack.");
                spdlog::warn("The 2x Upscaled pack must be installed or loaded AFTER the base package.");
                spdlog::warn("Please reinstall the 2x Upscaled pack to ensure correct behavior.");
                spdlog::warn("If you are using a mod manager, make sure the 2x Upscaled pack is loaded AFTER the base package.");
                spdlog::warn("Please visit our Nexus page at: https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files to redownload the 4x upscaled package.");
                spdlog::warn("Or our GitHub releases page at: https://github.com/ShizCalev/Afevis-MGS2-Bugfix-Compilation/releases");
                spdlog::warn("------------------- ! Community Bugfix Compilation (2x Upscaled Pack) Installation Issue ! -------------------");


                if (int result = MessageBoxA(
                    nullptr,
                    "Community Bugfix Compilation 2x Texture Pack installation issue detected.\n"
                    "\n"
                    "Unable to get the expected texture hash for seculitycard_lv2_alp in the 2x Upscaled pack. This usually means the base package was installed or loaded after the 2x pack.\n"
                    "The 2x Upscaled pack must be installed or loaded AFTER the base package.\n"
                    "\n"
                    "Please reinstall the 2x Upscaled pack to ensure correct behavior."
                    "If you are using a mod manager, make sure the 2x Upscaled pack is loaded AFTER the base package."
                    "\n"
                    "Would you like to open the Community Bugfix Nexus download page now to redownload the 2x upscaled package?\n"
                    "(You can also find a link to our GitHub releases on the Nexus page if preferred.)",
                    "Community Bugfix Compilation (2x Upscale) Installation Issue",
                    MB_ICONWARNING | MB_YESNO);
                result == IDYES)
                {
                    ShellExecuteA(
                        nullptr,
                        "open",
                        "https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files",
                        nullptr,
                        nullptr,
                        SW_SHOWNORMAL
                    );
                }
            }
        }
        */


    }

            // ------------------------------------------------------
            // MGS2: Verify community bugfix upscaled pack is loaded AFTER better audio mod
            // ------------------------------------------------------


    if (const std::filesystem::path afevisBugfixTestPathOne = sExePath / "us" / "demo" / "_bp" / "p010_01_p01g.sdt"; //vamp cutscene decensor fix
        std::filesystem::exists(afevisBugfixTestPathOne) && !Util::SHA1Check(afevisBugfixTestPathOne, "c0bc4f6cb9ec1aebb447b1c5fb1aadc7bd91635f"))
    {


        spdlog::warn("------------------- ! Community Bugfix Compilation (Base) - Installation Issue ! -------------------");
        spdlog::warn("Community Bugfix Compilation installation issue detected!");
        spdlog::warn("Unexpected SHA-1 hash for p010_01_p01g.sdt.");
        spdlog::warn("This can occur if Steam has verified integrity and damaged your mod files, or if the Community Bugfix Compilation (Base) was loaded BEFORE KnightKiller's Better Audio Mod.");
        spdlog::warn("Please reinstall the Community Bugfix Compilation (Base) to ensure correct behavior.");
        spdlog::warn("If you are using a mod manager, make sure Community Bugfix Compilation (Base) is loaded AFTER Better Audio Mod.");
        spdlog::warn("Please visit our Nexus page at: https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files to redownload the base package.");
        spdlog::warn("Or our GitHub releases page at: https://github.com/ShizCalev/Afevis-MGS2-Bugfix-Compilation/releases");
        spdlog::warn("------------------- ! Community Bugfix Compilation (Base) Missing ! -------------------");
        if (int result = MessageBoxA(
            nullptr,
            "Community Bugfix Compilation installation issue detected!\n"
            "\n"
            "Unexpected SHA-1 hash for p010_01_p01g.sdt.\n"
            "This can occur if Steam has verified integrity and damaged your mod files, or if the Community Bugfix Compilation (Base) was loaded BEFORE KnightKiller's Better Audio Mod.\n"
            "\n"
            "Please reinstall the Community Bugfix Compilation (Base) to ensure correct behavior.\n"
            "If you are using a mod manager, make sure Community Bugfix Compilation (Base) is loaded AFTER Better Audio Mod.\n"
            "\n"
            "Would you like to open the Community Bugfix Nexus download page now to download the base package?\n"
            "(You can also find a link to our GitHub releases on the Nexus page if preferred.)",
            "Community Bugfix Compilation (Base) Missing",
            MB_ICONWARNING | MB_YESNO);
        result == IDYES)
        {
            ShellExecuteA(
                nullptr,
                "open",
                "https://www.nexusmods.com/metalgearsolid2mc/mods/52?tab=files",
                nullptr,
                nullptr,
                SW_SHOWNORMAL
            );
        }
    }


    // ------------------------------------------------------
    // MGS2: Check if Higher Resolution KojiPro posters mod is installed
    // ------------------------------------------------------

    if (const std::filesystem::path afevisBugfixTestPathOne = sExePath / "textures" / "flatlist" / "ovr_stm" / "_win" / "zoe_pos_n.bmp.ctxr"; //Higher Resolution KojiPro Posters check. we damaged it.
        std::filesystem::exists(afevisBugfixTestPathOne) && Util::SHA1Check(afevisBugfixTestPathOne, "ce3fe5bd55aebb046103b5dba1cffa736b08abd2"))
    {


        spdlog::warn("------------------- ! Community Bugfix Compilation - Installation Issue ! -------------------");
        spdlog::warn("Community Bugfix Compilation installation issue detected.");
        spdlog::warn("j1llm4r13's Higher Resolution KojiPro Posters mod has been detected.");
        spdlog::warn("This mod has been damaged by the Community Bugfix Compilation, which hand-remakes the original source assets.");
        spdlog::warn("We already override the old mod's files, so we're just noting that it's unneeded here. <3");
        spdlog::warn("------------------- ! Community Bugfix Compilation (Base) Missing ! -------------------");

    }
    


}
