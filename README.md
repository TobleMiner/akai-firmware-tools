AKAI firmware tools
===================

Tools to inspect and modify AKAI firmware update images.

Make sure to install all requiremets listed in `requirements.txt`

# fwtool.py

For Linux firmware update images. Tested with Denon SC6000M firmware.

## Usage

```
Usage: fwtool.py [OPTIONS] COMMAND [ARGS]...

  Tool to inspect and modify AKAI Linux firmware update images

Options:
  --help  Show this message and exit.

Commands:
  copy            Self-test command, fully parses, destructures and...
  extract-rootfs  Extract rootfs from firmware update image
  info            Show header and partition information for a firmware...
  replace-rootfs  Replace rootfs within firmware update image, rootfs...
```

## Attributions

Inspired by [MPC-LiveXplore](https://github.com/TheKikGen/MPC-LiveXplore)
