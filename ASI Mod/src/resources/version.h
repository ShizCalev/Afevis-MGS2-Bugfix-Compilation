// ReSharper disable CppClangTidyModernizeMacroToEnum
#pragma once

// Core name & version
#define FIX_NAME "Afevis-MGS2-Bugfix-Compilation"
#define PRIMARY_REPO_URL "https://github.com/ShizCalev/Afevis-MGS2-Bugfix-Compilation"
#define FALLBACK_REPO_URL "https://gitlab.com/ShizCalev/Afevis-MGS2-Bugfix-Compilation"

#define VERSION_MAJOR 2
#define VERSION_MINOR 0
#define VERSION_PATCH 0

#define STRINGIFY_HELPER(x) #x
#define STRINGIFY(x) STRINGIFY_HELPER(x)
#define VERSION_STRING STRINGIFY(VERSION_MAJOR) "." STRINGIFY(VERSION_MINOR) "." STRINGIFY(VERSION_PATCH)

inline constexpr std::string sFixVersion = VERSION_STRING;
inline const std::string sFixName = FIX_NAME;

// Metadata
#define COMPANY_NAME      "Afevis"
#define PRODUCT_NAME      FIX_NAME
#define FILE_DESCRIPTION  FIX_NAME " ASI Plugin"
#define INTERNAL_NAME     FIX_NAME ".asi"
#define ORIGINAL_FILENAME FIX_NAME ".asi"
#define PRODUCT_VERSION   VERSION_STRING
#define FILE_VERSION      VERSION_STRING
#define LEGAL_COPYRIGHT   "© 2025 Afevis. Licensed under the MIT License."
#define LEGAL_TRADEMARKS  ""
#define COMMENTS          ""
