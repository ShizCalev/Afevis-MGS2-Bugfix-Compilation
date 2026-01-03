#pragma once
#if !defined(_CRT_SECURE_NO_WARNINGS)
#define _CRT_SECURE_NO_WARNINGS
#endif

#include <string>

namespace ConfigKeys
{
   
    // Internal
    constexpr const char* CheckForUpdates_Section = "Update Notifications";
    constexpr const char* CheckForUpdates_Setting = "Check For MGS2 Commmunity Bugfix Updates";
    constexpr const char* CheckForUpdates_Help = "";
    constexpr const char* CheckForUpdates_Tooltip = "If the mod should should notify you when launching the game if a new MGS2 Commmunity Bugfix update is available for download.";

    constexpr const char* UpdateConsoleNotifications_Section = "Update Notifications";
    constexpr const char* UpdateConsoleNotifications_Setting = "In-Game Update Notifications";
    constexpr const char* UpdateConsoleNotifications_Help = "";
    constexpr const char* UpdateConsoleNotifications_Tooltip = "If you want a visible notification when starting the game if an MGS2 Commmunity Bugfix update is available.\n"
                                                               "\n"
                                                               "Notifications will still be printed to the log file while disabled.";


}


