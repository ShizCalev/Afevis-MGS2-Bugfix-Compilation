# MGS2 Community Bugfix Compilation

A community-driven bugfix pack fixing invisible textures/models, missing audio, typos, consistency problems, and more; including re-importing the higher quality PS2 NPOT textures, upgrading many low-LOD models to their full-quality versions, and hand-remastering a number of low quality assets.

**Created, curated, and maintained by Afevis.**



This compilation should be considered a perpetual work-in-progress. (I love MGS2 and find new things to fix up CONSTANTLY.)


<br>
<br>
<br>

## Community contributions to the pack are absolutely encouraged.

*Files generated/upscaled through AI upscaling will NOT be accepted into the base pack.

The repo IS set up to easily contribute corrections (via CSV files) for **ALL** translations of the game. If you know of any typos in the French, Spanish, Japanese, ect versions, PLEASE feel free to submit those corrections as well!

<br>


NOTE: OPTIONAL ADDON 2X & 4X AI UPSCALED RELEASES OF THIS PACK ARE PROVIDED. As this pack already replaces nearly all of the game's textures, our upscaled packs do FULLY REPLACE LiqMix's AI Slop texture packs.

<br>

------------


Please report any issues found with the pack, or any issues that are not already corrected, to our GitHub here:
https://github.com/ShizCalev/Afevis-MGS2-Bugfix-Compilation/issues

<br>

------------

Recommended Mod Load Order (from first to last):

1. [MGSHDFix](https://github.com/Lyall/MGSHDFix)
2. [Knight_Killer](https://www.nexusmods.com/profile/KnightKiIIer)'s [MGS2 Better Audio Mod](https://www.nexusmods.com/metalgearsolid2mc/mods/3)
3. MGS2 Community Bugfix Compilation - Base
4. MGS2 Community Bugfix Compilation - AI Upscaled Texture Pack (if desired)
5. MGS2 Demastered Texture Pack (if installed)
6. [IroquoisPliskin1972](https://www.nexusmods.com/profile/IroquoisPliskin1972)'s [Solid Snake and Pliskin fixes and overhaul﻿](https://www.nexusmods.com/metalgearsolid2mc/mods/45)
7. [GuyOnAChair](https://www.nexusmods.com/profile/GuyOnAChair)'s [MGS2MC Solid Snake Hair Fix﻿](https://www.nexusmods.com/metalgearsolid2mc/mods/10)
5. All other mods


<br>

- As this pack already replaces nearly all of the game's textures, our upscaled packs do **FULLY REPLACE** LiqMix's AI Slop texture packs.

------------

<br>
<br>

## List of fixes [brackets denote what version the bug was introduced, ie Sons of Liberty, Substance, HD Collection, Master Collection]. Contributors will be listed afterward version seperated by a “|”. If no contributor is listed, the fix was made by Afevis:

### Bug Fixes:

- Fixed compression artifacting/pixelization present with 11970 textures (an issue originally introduced in the 2002 Xbox port of Substance) by re-exporting all 15221 textures from each of the original PS2 versions of MGS2, manually identifying each texture, and fully rebuilding the game's file structure. (This process took hundreds of hours over of the course of a year and a half to complete.) [2002 Xbox]

	- For a technical explanation of how the issue originated; its roots span back to the 2002 Xbox Substance port.

	- The vast majority of textures in the original PS2 version of MGS2 had dimensions that were not a power of 2, ie 2, 4, 8, 16, 32, 64, 128, 256, 512, ect. Early DirectX & OpenGL rendering did not support textures with non-^2 dimensions (referred to as arbitrary dimension textures, or [NPOT Textures](https://www.khronos.org/opengl/wiki/NPOT_Texture)) until OpenGL 2.0's release in 2004 which added the ARB_texture_non_power_of_two extension, well after both ports were created, and GPU's at the time ALSO had to be upgraded to support that new OpenGL feature level. As such, to even support the majority of console & PC hardware at the time - the team that handled the ports to the Xbox & PC ran all the textures through an automatic resizer, resizing all the textures' dimensions up to the next power of 2 (for example, a 130x70 texture would be sized up to 256x128), which introduced significant JPEG-type artifacting / haloing, blurred (and in some cases outright removed) fine details, and added randomly color lines along the edges of a LOT of the game's textures.
	
	- Bluepoint used these corrupted texture for the HD Remaster, and all versions of MGS2 released from the 2011 HD Collection onward all have this same issue with their textures.

- Stripped the unused alpha channel from 9505 opaque textures, a leftover from PS2 versions, which resulted in increased VRAM usage and z-fighting problems. [2011 HDC]

- Removes mipmaps that are incorrectly applied to 786 textures, correcting issues ranging from broken texture atlases, blurriness, and specular map quality issues. (They will be broken down further below) [2011 HDC]

- Fixed numerous partially (and in some cases fully) transparent textures (which even let you fully see enemies through walls in some places.) [2011 HDC]

- Fixed numerous textures which were not transparent enough (resulting in reflection effects not working on them.) [2011 HDC]

- Removed mipmaps from atlas map textures (ie magazines, item box words, ect), which lead to wrong parts/words being seen at a distance. [2011 HDC]

- All ocean textures have had their aspect ratios corrected, restoring the quality seen in the original PS2 versions. (The ocean UV tiling/repeat density was messed up in the 2002 Xbox port.) [2002 Substance]

- Fixed the flipped & reversed flag in shell 1 core b1. [2001 SOL]

- Fixed an incorrect wall texture at bottom of shell 2 strut l / oil fence (w32a_asi00.bmp) [2011 HDC]

- Fixed the sonar antennas having a corrupt texture when viewed from inside the Tanker's bridge. (w00a_pol1.bmp) [2001 SOL]

- Fixed a remastered overhead pipe texture Deck 2 being applied to the wrong pipe, and not actually being visible.  (w03a_pp02.bmp_09b1a01b9996f568e8ca8e878bee4475 -> w03a_pp02.bmp) [2011 HDC]

- Fixed a prebaked shadow on a vertical pipe in Deck 2 not properly reflecting the surrounding geometry (likely due to a layout revision during development. w03a_pp02.bmp) [2001 SOL]

- Fixed rogue lime green & sky blue pixels on the edge of most rivets on the pipes in Deck 2. (4 textures starting with crd_pp05.bmp) [2001 SOL]

- Corrected aspect ratios of the Snake Tales & Basic Actions background screens. (They were simply stretched from 4:3 → 16:9.) [2011 HDC]

- Corrected stretched VR mission completion camera effect (Again, it was simply stretched from 4:3 → 16:9.) [2011 HDC]

- Corrected repeat tiling on the Previous Stories background static. (These were nearest-neighbor upscaled by Bluepoint, when they should've just been repeated.) [2011 HDC]

- Corrected typos on several barrels. [2011 HDC]

- Corrected typos on PAN cards (previously said “SECULITY” instead of “SECURITY”.) [2001 SOL]

- Corrected NUMEROUS typos in Snake Tales stories (ie describing Emma as Otacon's sister-in-law/sister of spouse instead of stepsister, and Fatman's body as being “prostate” instead of “prostrate”, “Do you know where is it planted?”.)

- Corrected several typos in “In the Darkness of Shadow Moses” (ie Ocelot having learned torture methods in the cells of Lubianka - which means rural cities in Poland instead of Lubyanka - the KGB HQ in Moscow, Spetznaz instead of Spetsnaz, inconsistent capitalization of SOCOM pistol.)

- Fixed 1 pixel tall banding on the bottom edge of the center floor markings in Arsenal's Rectum, as well as numerous floating screens throughout Arsenal. (w46a_line_05_1, w45a_efct_disp_05_noiz_alp_add_ovl.bmp) [2001 SOL]

- Fixed broken/missing shadowmap on Fatman's shoes.

- Fixed reversed text on shutters in Shell A Sea Dock Elevator area (w11a) [2011 HDC]

- Fixed wrist-holders on the torture table NOT being transparent [2011 HDC]

- Fixed the wrist-holder mounts on the torture table BEING transparent. [2011 HDC]

- Fixed multiple wall & floor textures throughout arsenal not matching the lighting of the surrounding areas (not all of them could be corrected due to a model issue introduced in the 2011 HDC. A fix is still being pursuited.) [2011 HDC]

- Fixed misaligned parts of Snake's vest [2001 SOL]

- Fixed a few typos in the opening credits (ie “Viblation Artist” → “Vibration Artist”)

- Corrected typos on item-box text popups. (ibox_tx_all_alp.bmp) [2001 SoL]

- Fixed various corruption issues on numerous typos NOT related to NPOT's. (w00a_blc_t1.bmp_7f11fc01c0e5875532e7dd318d7c9e68, w03c_rfc00a_mog.bmp_23f594b4ce6d874272c3a003c35f7740) [2001 SoL]

- Replaced a poorly upscaled power generator texture with its higher-quality PS2 version. [2011 HDC]

- Fixed a hole in the top of the HH-60 Helicopters used by the SEALS during the Plant intro. [2001 SoL] Contributed by [Jacky720](https://github.com/Jacky720) / Space Core

<br>

------------

### Continuity Fixes:

- Corrected the color of the gloves on Snake's super-high polygon cutscene LOD model (which is only used for close-ups of the hands in ~4 cutscenes - the very first GW bridge cutscene, picking up the USP, Snake pointing to his Bandana, and after Tengu 2, and is also used in First Person View) to match his standard cutscene & gameplay LOD models. [2001 SOL]

- Fixed blood-trails on the ground in the bottom floor of Shell 1 Strut F during Snake Tales & VR missions. [2002 Substance]

- Fixed a quality & color inconsistency between Pliskin & the other SEALs boots. [2011 HDC]

- Corrected inconsistent height markings on the legs of Struts. [2001 SOL]

- Updated the Colonel's MG2:SS MSX portrait to accurately reflect his 2004 sprite change. (The bug which causes the sprite to be positioned incorrectly during the relevant codec calls is still present, but I've fixed the texture anyway in the event someone does fix that issue in the future.) [2011 HDC]

- Fixed dark skinned US Marines in the Holds having light skinned arms. [2001 SOL] (Note: A similar issue is present with the hostages in Shell 1 Core, which is an actual model issue that cannot be resolved at this time.)

- Fixed Emma's id swapping background colors / quality between gameplay and cutscenes. [2001 SOL]

<br>

------------


### Restored Content:

- Restored Fatman's glock to its original version (the slide serrations & slide release were simplified in HDC → MC, presumably for copyright reasons.) [2023 MC]

- Restored the secret Konami.jp reward screen for collecting all dogtags using the new Konami.com archival site, utilizing a tinyurl & QR code to make it easier to open. (The original URL has been dead since 2007, and Konami removed the screen with the MC release.) [2011 HDC/2023 MC]

- Restored numerous crosses changed from red to green. [2023 MC]

- Restored missing audio track in Guard Rush boss intro cutscene. [2003 Substance] | Contributed by [Knight_Killer](https://www.nexusmods.com/profile/KnightKiIIer)

- Restored censored blood particle effects during Guard Rush boss intro cutscene. [2002 EU-SoL] | Contributed by [Knight_Killer﻿](https://www.nexusmods.com/profile/KnightKiIIer)

- Restored missing audio track during Vamp vs Seals cutscene. [2003 Substance] | Contributed by [Knight_Killer﻿](https://www.nexusmods.com/profile/KnightKiIIer)

- Restored censored blood particle effects during Vamp vs Seals cutscene. [2002 EU-SoL] | Contributed by [Knight_Killer﻿](https://www.nexusmods.com/profile/KnightKiIIer)

- Restored censored blood particle effects during Shell 2 Core B1 cutscene. [2002 EU-SoL] | Contributed by [Knight_Killer﻿](https://www.nexusmods.com/profile/KnightKiIIer)



<br>

------------

### Quality Improvements:

- Replaced MOST* Low-Poly LOD models (shown when chacters are far away from the screen, and also used for reflections on floors & such) with their higher polygon versions.

	- *Not all LOD models could be replaced as they vary in formats. Proper code modification of the executable to alter LOD draw distance would be needed to override the remaining models.

    - This in turn corrects a number of texture inconsistencies that were present on the low-poly LOD models, as those models are no longer used.

    - The [Solid Snake and Pliskin face fixes](https://www.nexusmods.com/metalgearsolid2mc/mods/45) mod made by [IroquoisPliskin1972](https://www.nexusmods.com/metalgearsolid2mc/users/51924501) is still recommended to be installed alongside this mod for the remaining LOD models.

- Replaced a LOT of low resolution mipmap textures (used for far away areas when on the plant's connecting bridges) with their higher quality versions.

- Removed mipmaps from mod1120 textures (emaps/reflections maps, full resolution ground elements, ect), improving reflection / specular quality at distance.

- Removed mipmaps from all character bump maps, leading to higher fidelity shadows at greater distances.

- Remade the ranking codename animal pixel art utilizing the original PS2 texture.

- Resaved all 2500 remaining CTXR files using Kaiser window mips for consistent, higher quality mipmaps.

<br>

------------

### Remade Assets:

* All remade assets are located in the following folder and can be deleted without issue for purist who only want the base PS2 reimport & mipmap/opacity fixes.

\ovr_stm\ovr_eu\_win

Feel free to inquire about texture file names if you need assistance pinpointing certain things!

- A number of text assets (using the original source fonts) that were either their original PS2 resolutions, or had serious aliasing issues from being machine upscaled multiple times over the years:

	- Title cards, Smithsonian quotes, ect, at the start of both main chapters
	- Location / setting cards (ie Verrazano Bridge, Big Shell Disposal Facility, ect.)
	- Snake Tales title cards

- Remade all KojiPro posters (ie MGS Ghost Babel, Policenauts, Zone of Enders), using their original real-life promotional posters as the higher quality base / reference material.

- Remade the low resolution statue of liberty postcard found in some lockers.

- Remade ocean reflection maps utilizing their source assets.



<br>
<br>
<br> 

## Tools used for this project:

* Tons of self-made C++ & Python based tooling for file management, image identification & metadata handling, extraction of .tri files and fully rebuilding them into their original source file structures, and much, much more.
* Chainner
* Blender
* Autodesk Maya
* Adobe Photoshop 2025 (using self-made scripts for proper UV edge padding on export due to a legacy photoshop bug with transparent textures.)
* Adobe Substance 3D Painter
* Gimp
* Nvidia Texture Export Tool (using self-made presets for production quality Kaiser mipmaps. More than happy to share with other modders at request to generate the highest quality mipmaps possible!)
* Funduc's Duplicate File Finder
* Voidtool's Everything
* i2ocr's Japanese Optical Character Recognition
* PCSX2
* Noesis Model Viewer / Exporter
* Jayveer's MGS2 Master Collection & PS2 Noesis plugins
* 316austin316's CTXR3
* Jayveer's CTXRTool (using self-made batch scripts for automated mipmap generation using Nvidia texture tool)
* Visual Studio Code (bp_asset & manifest file management)
* Notepad++ (bp_asset & manifest file management)


--------

Built using [MGS2-PS2-Textures](https://github.com/dotlessone/MGS2-PS2-Textures), made by Afevis.
