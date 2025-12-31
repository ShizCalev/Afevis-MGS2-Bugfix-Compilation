#include "stdafx.h"
#include "bugfix_mod_checks.hpp"

#include "common.hpp"
#include "logging.hpp"
#include "version.h"


namespace
{
}



void VerifyInstallation::Check()
{


    // ------------------------------------------------------
    // MGS2: Verify Afevis Bugfix Collection based installation
    // ------------------------------------------------------

    if (const std::filesystem::path afevisBugfixTestPathOne = sExePath / "textures" / "flatlist" / "_win" / "col_orange2.bmp.ctxr"; std::filesystem::exists(afevisBugfixTestPathOne) && !Util::SHA1Check(afevisBugfixTestPathOne, "11d03110d40b42adeafde2fa5f5cf65f27d6fc52"))
    {

        spdlog::warn("------------------- ! Community Bugfix Compilation (Base) Missing ! -------------------");
        spdlog::warn("Community Bugfix Compilation installation issue detected, base package is NOT found.");
        spdlog::warn("This can occur if steam has verified integrity and replaced your mod files, or if the Base Bugfix Compilation zip wasn't installed.");
        spdlog::warn("The base package is required for proper functionality, even when 2x & 4x packages are installed.");
        spdlog::warn("Please install the Community Bugfix Compilation -> Base <- package to ensure proper game functionality.");
        spdlog::warn("------------------- ! Community Bugfix Compilation (Base) Missing ! -------------------");
        if (int result = MessageBoxA(
            nullptr,
            "Community Bugfix Compilation installation issue detected, base package is NOT found.\n"
            "\n"
            "This can occur if steam has verified integrity and replaced your mod files, or if the Base Bugfix Compilation zip wasn't installed.\n"
            "\n"
            "The base package is required for proper functionality, even when 2x & 4x packages are installed.\n"
            "Please install the Community Bugfix Compilation -> Base <- package to ensure proper game functionality.\n"
            "\n"
            "Would you like to open the Community Bugfix Nexus download page now to download the base package?",
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





    if (const std::filesystem::path col_orange2OvrStmTest = sExePath / "textures" / "flatlist" / "ovr_stm" / "_win" / "col_orange2.bmp.ctxr"; std::filesystem::exists(col_orange2OvrStmTest))
    {

            // ------------------------------------------------------
            // MGS2: Check if liqmix AI slop packs are installed
            // ------------------------------------------------------
        if (Util::SHA1Check(col_orange2OvrStmTest, "96ba1191c0da112d355bf510dcb3828f1183d1b5") || Util::SHA1Check(col_orange2OvrStmTest, "4ecda248b079ee426262a23b64df6cb05a249088")) //liqmix 2x & 4x hashes
        {
            spdlog::warn("------------------- ! Community Bugfix Compilation - Mod Compatibility Issue ! -------------------");
            spdlog::warn("LiqMix's AI Slop AI Upscaled texture pack has been detected.");
            spdlog::warn("LiqMix's AI Slop texture pack is VERY out of date and has been replaced by the MGS2 Community Bugfix Compilation's Upscaled texture packs, which includes all the texture fixes from the base version.");
            spdlog::warn("Please uninstall LiqMix's AI Slop Upscaled texture pack to ensure proper game functionality.");
            spdlog::warn("------------------- ! Community Bugfix Compilation - Mod Compatibility Issue ! -------------------");
            if (int result = MessageBoxA(
                nullptr,
                "LiqMix's AI Slop AI Upscaled texture pack has been detected.\n"
                "LiqMix's AI Slop texture pack is VERY out of date and has been replaced by the Community Bugfix Compilation's upscaled packs, which includes all the texture fixes from the base version."
                "Please remove LiqMix's AI Slop Upscaled texture pack to ensure proper game functionality.\n"
                "\n"
                "Would you like to open the Community Bugfix Nexus download page now to download the base package?",
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
            if (const std::filesystem::path SelfRemade_4x_ovr_eu_obj_hos_book = sExePath / "textures" / "flatlist" / "ovr_stm" / "ovr_eu" / "_win" / "obj_hos_book.bmp.ctxr"; 
                std::filesystem::exists(SelfRemade_4x_ovr_eu_obj_hos_book) && !Util::SHA1Check(SelfRemade_4x_ovr_eu_obj_hos_book, "debb808bec01c4a4e129864294bb68d6b83306fb"))
            {
                

                spdlog::warn("------------------- ! Community Bugfix Compilation (4x Upscaled Pack) Installation Issue ! -------------------");
                
                spdlog::warn("Community Bugfix Compilation 4x Texture Pack installation issue detected.");
                spdlog::warn("Unable to get proper texture hash for the 4x Upscaled pack's obj_hos_book, this usually indicates that the base package was installed (or loaded) after the 4x Upscaled pack.");
                spdlog::warn("The 4x Upscaled pack must be installed (or loaded) AFTER the base package to ensure proper functionality.");
                spdlog::warn("Please reinstall the Community Bugfix Compilation 4x Upscaled package to ensure proper game functionality.");
                spdlog::warn("(Or, if using a mod manager, ensure the 4x Upscaled pack & any collisions are loaded AFTER the base package.)");
                spdlog::warn("------------------- ! Community Bugfix Compilation (4x Upscaled Pack) Installation Issue ! -------------------");
                
                if (int result = MessageBoxA(
                    nullptr,
                    "Community Bugfix Compilation installation issue detected, base package is NOT found.\n"
                    "\n"
                    "This can occur if steam has verified integrity and replaced your mod files, or if the Base Bugfix Compilation zip wasn't installed.\n"
                    "\n"
                    "The base package is required for proper functionality, even when 2x & 4x packages are installed.\n"
                    "Please install the Community Bugfix Compilation -> Base <- package to ensure proper game functionality.\n"
                    "\n"
                    "Would you like to open the Community Bugfix Nexus download page now to download the base package?",
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

            
        }
    }

    //better audio mod -> check if p07/vamp is correct 

    //check load order, check if col_orange2 in ovr_stm exists & matches hash of 4x/2x, if true, verify one of the hashes in ovr_eu



}
