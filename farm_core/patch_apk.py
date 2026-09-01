import zipfile
import hashlib
import base64
import os
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7

def patch_and_sign_apk(src_apk, dst_apk):
    print(f"Reading {src_apk}...")
    file_data = {}
    file_compression = {}
    
    with zipfile.ZipFile(src_apk, "r") as z_in:
        for info in z_in.infolist():
            name = info.filename
            if name.startswith("META-INF/"):
                continue
            content = z_in.read(name)
            if name == "resources.arsc":
                # Patch string
                old_str = b"\x1b\x1bA11Y Companion (Phone Farm)\x00"
                new_str = b"\x13\x13A11Y Companion (PF)\x00\x00\x00\x00\x00\x00\x00\x00"
                if old_str in content:
                    content = content.replace(old_str, new_str)
                    print("Successfully replaced 'Phone Farm' -> 'PF' in resources.arsc!")
                else:
                    print("Warning: old string pattern not found in resources.arsc")
            
            file_data[name] = content
            file_compression[name] = info.compress_type

    # 1. Generate RSA key & certificate
    print("Generating RSA key pair and self-signed certificate...")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Android Debug"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Android"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=10000))
        .sign(private_key, hashes.SHA256())
    )

    # 2. Build MANIFEST.MF
    manifest_lines = [
        "Manifest-Version: 1.0",
        "Created-By: 1.0 (Android)",
        ""
    ]
    for name, content in file_data.items():
        digest = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
        manifest_lines.append(f"Name: {name}")
        manifest_lines.append(f"SHA-256-Digest: {digest}")
        manifest_lines.append("")
    
    manifest_bytes = "\r\n".join(manifest_lines).encode("utf-8")

    # 3. Build CERT.SF
    sf_lines = [
        "Signature-Version: 1.0",
        "Created-By: 1.0 (Android)",
        f"SHA-256-Digest-Manifest: {base64.b64encode(hashlib.sha256(manifest_bytes).digest()).decode('ascii')}",
        ""
    ]
    for name, content in file_data.items():
        entry_str = f"Name: {name}\r\nSHA-256-Digest: {base64.b64encode(hashlib.sha256(content).digest()).decode('ascii')}\r\n\r\n"
        entry_hash = base64.b64encode(hashlib.sha256(entry_str.encode("utf-8")).digest()).decode("ascii")
        sf_lines.append(f"Name: {name}")
        sf_lines.append(f"SHA-256-Digest: {entry_hash}")
        sf_lines.append("")

    sf_bytes = "\r\n".join(sf_lines).encode("utf-8")

    # 4. Build CERT.RSA
    options = [pkcs7.PKCS7Options.DetachedSignature]
    cert_rsa_bytes = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(sf_bytes)
        .add_signer(cert, private_key, hashes.SHA256())
        .sign(serialization.Encoding.DER, options)
    )

    # 5. Write new APK preserving exact original compression per file
    print(f"Writing signed APK to {dst_apk}...")
    with zipfile.ZipFile(dst_apk, "w") as z_out:
        for name, content in file_data.items():
            c_type = file_compression.get(name, zipfile.ZIP_STORED)
            z_out.writestr(name, content, compress_type=c_type)
        z_out.writestr("META-INF/MANIFEST.MF", manifest_bytes, compress_type=zipfile.ZIP_DEFLATED)
        z_out.writestr("META-INF/CERT.SF", sf_bytes, compress_type=zipfile.ZIP_DEFLATED)
        z_out.writestr("META-INF/CERT.RSA", cert_rsa_bytes, compress_type=zipfile.ZIP_DEFLATED)

    print("APK successfully patched and signed with preserved compression!")

if __name__ == "__main__":
    src = r"C:\Users\a.feoktistov\Desktop\апк\апук\app-debug.apk"
    dst = r"C:\Users\a.feoktistov\Desktop\апк\апук\app-debug-pf.apk"
    patch_and_sign_apk(src, dst)
