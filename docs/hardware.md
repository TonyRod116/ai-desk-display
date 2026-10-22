# Hardware and installation boundaries

The reference device is a **NerdMiner V2 with a 2.8-inch touchscreen**, based on **ESP32-2432S028R (Cheap Yellow Display / CYD), 320×240**. NerdMiner V2 is also available on other boards: confirm the board model and controller before flashing. Installing AI Desk Display firmware replaces the mining application. Build the correct ILI9341 (`cyd`) or ST7789 (`cyd_st7789`) firmware for your panel; see [firmware instructions](../firmware/board/README.md). No prebuilt flash image or vendored web-flasher dependencies are shipped in this source checkout; build and prepare them first.

A GeekMagic SmallTV Ultra uses a different image-upload integration. Do not flash the ESP32 touch firmware onto it. See [SmallTV Ultra](smalltv-ultra.md).

The Python host renders static backgrounds and uploads bounded animation instructions. Firmware plays supported sprites/waves locally. A running host supplies fresh quotas and heartbeats; loss of fresh data is shown as unavailable. Photo scenes are not proof of compatibility with a different display.

Keep runtime configuration, Wi-Fi credentials, account bindings and pairing secrets private. Start with the offline gallery; then follow [setup](setup.md). Account readers and the optional browser extension require explicit local setup for your own account. Never copy somebody else's pairing files.

Other displays can be supported by adapting rendering dimensions and transport, and sometimes the firmware. AI assistance can help develop that adapter but does not replace hardware testing.
