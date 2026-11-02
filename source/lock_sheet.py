"""Wrap a built stock sheet in a password screen, so the published page holds only scrambled text.

Usage: python3 lock_sheet.py <sheet.html> <keys.json> <SCHOOL_CODE> <out_dir>

keys.json holds, per school code: path (the link code), password, salt (hex). It is private and is
never published. The sheet is encrypted with AES-256-GCM under a key derived from the password by
PBKDF2-SHA256 (600,000 iterations). The school's browser derives the same key and decrypts the
sheet; nothing readable is in the published file. The salt stays fixed per school, so a device
that chose "Remember me" keeps working after each weekly update until the password changes.
"""
import base64, json, os, re, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 600_000

SHELL = r"""<!DOCTYPE html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root { --navy: #001A4A; --raspberry: #D6416F; --slate: #4A5568; --line: #D9DDE5; --cool: #F3F3F1; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: 'Archivo', sans-serif; background: var(--cool); color: var(--navy); }
  header { background: var(--navy); border-bottom: 4px solid var(--raspberry); padding: 22px 20px; text-align: center; }
  header img { height: 44px; }
  main { max-width: 420px; margin: 40px auto; padding: 0 20px; }
  .card { background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 26px 24px; }
  h1 { font-size: 20px; margin: 0 0 6px; }
  p { font-size: 15px; line-height: 1.55; color: var(--slate); margin: 0 0 18px; }
  label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 6px; }
  input[type=password] { width: 100%; height: 46px; font: 400 16px 'Archivo', sans-serif; border: 1.5px solid var(--line); border-radius: 4px; padding: 0 12px; }
  input[type=password]:focus { outline: 2px solid var(--navy); outline-offset: 1px; }
  .remember { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--slate); margin: 14px 0 18px; font-weight: 400; }
  button { width: 100%; font: 600 13px 'Archivo', sans-serif; letter-spacing: 0.13em; text-transform: uppercase; background: var(--raspberry); color: #fff; border: 0; border-radius: 4px; padding: 15px; cursor: pointer; }
  button:disabled { opacity: 0.5; }
  .err { color: #B42318; font-size: 14px; min-height: 20px; margin: 12px 0 0; }
  .help { font-size: 13px; text-align: center; margin-top: 18px; }
</style>
</head>
<body>
<header><img src="__LOGO__" alt="School Uniforms Australia"></header>
<main>
  <form class="card" id="f">
    <h1>__SCHOOL__</h1>
    <p>Enter the password we gave you to open your weekly stock sheet.</p>
    <label for="pw">Password</label>
    <input type="password" id="pw" autocomplete="current-password" required>
    <label class="remember"><input type="checkbox" id="rem" checked> Remember me on this computer</label>
    <button id="go">Open stock sheet</button>
    <div class="err" id="err" aria-live="polite"></div>
  </form>
  <p class="help">Forgotten the password? Email aman@schooluniformsaustralia.com.au</p>
</main>
<script>
const D = __DATA__;
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const STORE = 'sua-key-' + D.id;
async function keyFromPassword(pw) {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: b64(D.salt), iterations: D.iter }, base, 256);
  return new Uint8Array(bits);
}
async function open(raw) {
  const key = await crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['decrypt']);
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(D.iv) }, key, b64(D.ct));
  const html = new TextDecoder().decode(plain);
  document.open(); document.write(html); document.close();
}
const toB64 = u => btoa(String.fromCharCode(...u));
(async () => {
  let saved = null;
  try { saved = localStorage.getItem(STORE); } catch (e) {}
  if (saved) { if (document.readyState !== 'complete') await new Promise(r => window.addEventListener('load', r)); try { await open(b64(saved)); return; } catch (e) { try { localStorage.removeItem(STORE); } catch (e2) {} } }
  document.getElementById('pw').focus();
})();
document.getElementById('f').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('go'), err = document.getElementById('err');
  btn.disabled = true; err.textContent = '';
  try {
    const remember = document.getElementById('rem').checked;
    const raw = await keyFromPassword(document.getElementById('pw').value.trim().toLowerCase());
    await open(raw);
    if (remember) { try { localStorage.setItem(STORE, toB64(raw)); } catch (e2) {} }
  } catch (x) {
    btn.disabled = false;
    err.textContent = 'That password did not work. Please check it and try again.';
  }
});
</script>
</body>
</html>
"""


def lock(sheet_path, keys_path, code, out_dir):
    keys = json.load(open(keys_path))[code]
    html = open(sheet_path, encoding="utf-8").read()
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    school = title.replace(" weekly stock", "")
    logo = re.search(r"data:image/svg\+xml;base64,[A-Za-z0-9+/=]+", html).group(0)
    # keep the sheet out of search engines once decrypted too
    html = html.replace("<head>", '<head>\n<meta name="robots" content="noindex, nofollow">', 1)
    salt = bytes.fromhex(keys["salt"])
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(
        keys["password"].strip().lower().encode())
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, html.encode("utf-8"), None)
    data = {"id": keys["path"], "salt": base64.b64encode(salt).decode(), "iv": base64.b64encode(iv).decode(),
            "iter": ITER, "ct": base64.b64encode(ct).decode()}
    page = (SHELL.replace("__TITLE__", title).replace("__SCHOOL__", school).replace("__LOGO__", logo)
            .replace("__DATA__", json.dumps(data)))
    d = os.path.join(out_dir, keys["path"])
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(page)
    assert "each inc GST" not in page and "in stock" not in page  # nothing readable left
    print(code, "->", keys["path"] + "/index.html", len(page))


if __name__ == "__main__":
    lock(*sys.argv[1:5])
