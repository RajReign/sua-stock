"""Decrypt a published (locked) sheet back to its built HTML, for a fix that does not need fresh Zoho data.

Usage: python3 unlock_sheet.py <locked index.html> <keys.json> <SCHOOL_CODE> <out.html>
The lock step adds a robots meta tag inside <head>; it is removed here so re-locking does not add it twice.
"""
import base64, json, re, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

page, keys_path, code, out = sys.argv[1:5]
keys = json.load(open(keys_path))[code]
data = json.loads(re.search(r"const D = (\{.*?\});\n", open(page, encoding="utf-8").read()).group(1))
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(data["salt"]),
                 iterations=data["iter"]).derive(keys["password"].strip().lower().encode())
html = AESGCM(key).decrypt(base64.b64decode(data["iv"]), base64.b64decode(data["ct"]), None).decode("utf-8")
html = html.replace('<head>\n<meta name="robots" content="noindex, nofollow">', "<head>", 1)
open(out, "w", encoding="utf-8").write(html)
print(code, "unlocked", len(html))
