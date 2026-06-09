import subprocess, glob, sys

files = glob.glob("**/*.py", recursive=True)
errors = []
for f in files:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", f],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        errors.append(f"HATA: {f}\n{result.stderr}")

if errors:
    for e in errors: print(e)
else:
    print("✅ Tüm .py dosyaları temiz, syntax hatası yok")