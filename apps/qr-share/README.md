# QR Share

Render useful data as a high-contrast QR code on a SolarOS graphic display.
With no arguments, QR Share reads only the public half of the default SSH key
pair through `solaros.ssh_keys` and displays it for copying to another machine.
Private key material is never opened.

Usage:

```text
python qrshare.py
python qrshare.py --ssh
python qrshare.py solar-os.eu
python qrshare.py --text "hello from SolarOS"
python qrshare.py --file /notes/wifi.txt
```

The compact encoder uses QR Model 2 byte mode, low error correction, versions
1 through 15, and supports up to 520 UTF-8 bytes. This keeps a typical RSA or
Ed25519 OpenSSH public key at three physical pixels per QR module on the
400×300 Waveshare display.

File input is limited to 520 bytes. Larger files are rejected before encoding;
QR Share displays the limit and file path and waits for Escape.

Controls:

- R reloads the selected public key or file.
- Escape or Q exits.

Requires a graphic display and SolarOS 4.6.8. Automatic SSH-key mode also
requires a firmware flavor with the SSH service.
