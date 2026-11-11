# NX Duo Tap

NX Duo Tap is the Switch side of **NX Duo**, the local-multiplayer-at-a-distance
mode of [NX Paradox](https://testpilotx.net/nx-paradox/). It is an Atmosphère
sysmodule that sends the console's picture and sound to the PC over USB and
receives the remote player's controller.

NX Duo Tap is a modified version of **[Switch Frame Tap](https://github.com/TomasUribe/switch-frame-tap)**
by Tomas Uribe. All the credit for the original work is his. NX Duo Tap is
maintained by TestPilotX so NX Duo can follow new Switch firmware and
Atmosphère releases quickly.

## Install

NX Paradox installs it for you: **NX Duo → Prepare Switch and PC**.

To install it by hand, unzip `nx-duo-tap-<version>-switch.zip` from the
[releases](https://github.com/TestPilotX-Dev/nx-duo-tap/releases) over the root of
the microSD card and restart the console. It uses the same files and title IDs
as Switch Frame Tap (`0100000000000C20` and `0100000000000C21`), so it replaces
it in place.

## Build

The Switch side is built in GitHub Actions: **Actions → NX Duo Tap · Switch
build → Run workflow**, with the version, the Atmosphère tag and the libnx ref
to build against. The workflow runs `tools/make_release.sh` in the
`devkitpro/devkita64` image and keeps the sysmodule's ELF next to the zip, to
read crash reports.

## License

GPL-2.0, like Switch Frame Tap and Atmosphère. See `LICENSE` and `NOTICE`.
The source of every release is the tagged commit of this repository.
