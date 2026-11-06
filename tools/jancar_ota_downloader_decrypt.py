#!/usr/bin/env python3
"""Download OTA packages returned for one Jancar product key and decrypt them.

Format confirmed in com.jancar.ota.util.AesUtil:
    4 bytes  : JSON header length, unsigned little-endian
    N bytes  : UTF-8 JSON metadata (left in cleartext)
    remaining: AES-128-ECB ciphertext, Java PKCS5Padding

This script only requests updates for the configured product key. It does not
scan the server, enumerate unrelated product keys, or install downloaded APKs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_IP = "47.107.34.247"
DEFAULT_PRODUCT_KEY = "JCAC20G01-PA1"
BASE_PATH = "/AppUpdate"
AES_KEY = b"car20230717key00"  # Extracted from this APK's AesUtil class.
BLOCK_SIZE_BYTES = 16
MAX_HEADER_SIZE = 1024 * 1024
CHUNK_SIZE = 1024 * 1024  # Multiple of AES block size.


def safe_filename(value: str, fallback: str = "ota_update") -> str:
    """Return a filesystem-safe base name without directory components."""
    name = Path(str(value or "")).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_exact(stream, size: int) -> bytes:
    """Read exactly size bytes or raise EOFError on a truncated OTA file."""
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            raise EOFError(f"Truncated file: expected {size} bytes, read {len(chunks)}")
        chunks.extend(part)
    return bytes(chunks)


def decrypt_ota_file(encrypted_path: Path, output_dir: Path, output_stem: str) -> Path:
    """Decrypt a Jancar OTA container; return the resulting file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_output = output_dir / f"{output_stem}.decrypted.part"

    with encrypted_path.open("rb") as source:
        # AesUtil.bytesToInt() assembles b0 | b1<<8 | b2<<16 | b3<<24.
        raw_length = read_exact(source, 4)
        header_length = int.from_bytes(raw_length, byteorder="little", signed=False)

        if not 20 <= header_length <= MAX_HEADER_SIZE:
            raise ValueError(
                f"Invalid JSON header length ({header_length} bytes). "
                "The file does not appear to match the Jancar OTA format."
            )

        header_bytes = read_exact(source, header_length)
        try:
            header_text = header_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("The JSON header is not valid UTF-8") from exc

        try:
            header_data: Any = json.loads(header_text)
        except json.JSONDecodeError:
            # The Android application logs this field as jsonString but does not
            # parse it in AesUtil. Keep the original text for inspection.
            header_data = header_text

        ciphertext_length = encrypted_path.stat().st_size - 4 - header_length
        if ciphertext_length <= 0:
            raise ValueError("No encrypted data found after the JSON header")
        if ciphertext_length % BLOCK_SIZE_BYTES:
            raise ValueError(
                f"Invalid ciphertext size ({ciphertext_length} bytes, "
                "not a multiple of 16). The download may be incomplete or use a different format."
            )

        decryptor = Cipher(algorithms.AES(AES_KEY), modes.ECB()).decryptor()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()

        try:
            with temp_output.open("wb") as target:
                while True:
                    encrypted_chunk = source.read(CHUNK_SIZE)
                    if not encrypted_chunk:
                        break
                    decrypted_chunk = decryptor.update(encrypted_chunk)
                    unpadded_chunk = unpadder.update(decrypted_chunk)
                    if unpadded_chunk:
                        target.write(unpadded_chunk)

                final_decrypted = decryptor.finalize()
                final_plaintext = unpadder.update(final_decrypted) + unpadder.finalize()
                if final_plaintext:
                    target.write(final_plaintext)

        except Exception:
            temp_output.unlink(missing_ok=True)
            raise

    # A successful PKCS#7 unpadding is not an authenticity/signature check.
    is_zip = zipfile.is_zipfile(temp_output)
    if is_zip:
        with zipfile.ZipFile(temp_output) as archive:
            names = set(archive.namelist())
            is_apk = "AndroidManifest.xml" in names and "classes.dex" in names
        extension = ".apk" if is_apk else ".zip"
    else:
        is_apk = False
        extension = ".decrypted.bin"

    final_path = output_dir / f"{output_stem}{extension}"
    temp_output.replace(final_path)

    print(f"    [+] Decrypted : {final_path}")
    print(f"    [+] Size      : {final_path.stat().st_size:,} bytes")
    print(f"    [+] SHA-256   : {sha256_file(final_path)}")
    print(f"    [+] Format    : {'Android APK' if is_apk else ('Non-APK ZIP' if is_zip else 'Binary (needs inspection)')}")
    print("    [+] Header    :")
    print(json.dumps(header_data, ensure_ascii=False, indent=2)[:4000])

    if not is_apk:
        print("    [!] The output was not recognized as a valid Android APK.")

    return final_path


def download_file(
    session: requests.Session,
    url: str,
    params: dict[str, str],
    encrypted_path: Path,
) -> bool:
    print(f"[*] Downloading : {encrypted_path.name}")
    try:
        encrypted_path.parent.mkdir(parents=True, exist_ok=True)
        with session.get(url, params=params, stream=True, timeout=(10, 90)) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if "application/json" in content_type:
                preview = response.raw.read(500).decode("utf-8", errors="replace")
                raise RuntimeError(f"The server returned JSON instead of a file: {preview}")

            with encrypted_path.open("wb") as target:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        target.write(chunk)

        if encrypted_path.stat().st_size < 4:
            raise RuntimeError("Downloaded response is too short")

        print(f"    [+] Encrypted file kept : {encrypted_path}")
        print(f"    [+] Size : {encrypted_path.stat().st_size:,} bytes")
        return True

    except Exception as exc:
        encrypted_path.unlink(missing_ok=True)
        print(f"    [-] Download failed: {exc}")
        return False


def check_for_updates(ip: str, product_key: str, output_dir: Path) -> int:
    base_url = f"http://{ip}"
    endpoint = f"{base_url}{BASE_PATH}/AppUpdateServlet"

    print(f"[*] OTA server : {base_url}")
    print(f"[*] Product key : {product_key}")
    print(f"[*] Output      : {output_dir.resolve()}")
    print("[!] Plain HTTP: server responses are not authenticated with TLS.")

    session = requests.Session()
    session.headers.update({"User-Agent": "Jancar-OTA-Inspector/1.0"})

    try:
        response = session.get(
            endpoint,
            params={"keyword": product_key},
            timeout=(10, 30),
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise RuntimeError(
                f"Server returned a non-JSON response (HTTP {response.status_code}): "
                f"{response.text[:500]}"
            ) from exc

    except Exception as exc:
        print(f"[-] Failed to query the server: {exc}")
        return 1

    if not isinstance(payload, dict):
        print("[-] Unexpected response format: a JSON object was expected.")
        return 1

    if str(payload.get("code")) != "0":
        print(f"[-] The server returned code={payload.get('code')} : {payload.get('msg', payload)}")
        return 1

    updates = payload.get("data") or []
    if isinstance(updates, dict):
        updates = [updates]
    if not isinstance(updates, list) or not updates:
        print("[-] No updates returned for this product key.")
        return 0

    print(f"[+] Server returned {len(updates)} OTA update(s).")
    download_endpoint = f"{base_url}{BASE_PATH}/DownloadServlet"
    success_count = 0

    # Create the destination before download_file() opens the .ota.enc file.
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[-] Failed to create output directory {output_dir}: {exc}")
        return 1

    for index, update in enumerate(updates, start=1):
        if not isinstance(update, dict):
            print(f"[-] Skipping entry {index}: unexpected format.")
            continue

        apk_name = str(update.get("apkName") or f"ota_update_{index}")
        version = str(update.get("versionName") or "unknown")
        uuid = update.get("uuid")
        try:
            size = int(update.get("size") or 0)
        except (TypeError, ValueError):
            size = 0

        safe_stem = safe_filename(f"{apk_name}_{version}")
        print("\n" + "-" * 64)
        print(f"App       : {apk_name}")
        print(f"Version   : {version}")
        if size:
            print(f"API size: {size / (1024 * 1024):.2f} MiB")
        print(f"UUID      : {uuid or '(missing)'}")

        if not uuid:
            print("[-] UUID is missing; this entry cannot be downloaded.")
            continue

        encrypted_path = output_dir / f"{safe_stem}.ota.enc"
        if not download_file(session, download_endpoint, {"id": str(uuid)}, encrypted_path):
            continue

        try:
            decrypt_ota_file(encrypted_path, output_dir, safe_stem)
            success_count += 1
        except Exception as exc:
            print(f"[-] Decryption failed: {exc}")
            print("    The .ota.enc file has been kept for further analysis.")

    print("\n" + "=" * 64)
    print(f"Finished: successfully decrypted {success_count}/{len(updates)} file(s).")
    print(f"Output directory: {output_dir.resolve()}")
    print("No APK was installed or executed.")
    return 0 if success_count else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query the Jancar OTA server for a product key and decrypt the returned files."
    )
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"OTA server IP address (default: {DEFAULT_IP})")
    parser.add_argument(
        "--product-key",
        default=DEFAULT_PRODUCT_KEY,
        help="Product key to query (default: the key configured in this script)",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("jancar_ota_downloads"), help="Output directory")
    args = parser.parse_args()

    if not args.product_key.strip():
        parser.error("--product-key cannot be empty")

    return check_for_updates(args.ip, args.product_key.strip(), args.out_dir)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[!] Interrupted by user.")
        sys.exit(130)
