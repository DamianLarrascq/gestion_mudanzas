"""
decode_requirements.py
Convierte requirements.txt de UTF-16 (generado en Windows) a UTF-8.
Produce requirements_utf8.txt que pip puede leer normalmente.
Llamado desde el workflow de GitHub Actions.
"""
import sys

with open("requirements.txt", "rb") as f:
    raw = f.read()

BOM_LE = bytes([0xFF, 0xFE])
BOM_BE = bytes([0xFE, 0xFF])

if raw[:2] == BOM_LE or raw[:2] == BOM_BE:
    content = raw.decode("utf-16")
    print(f"Detectado: UTF-16 ({len(raw)} bytes)")
else:
    content = raw.decode("utf-8")
    print("Detectado: UTF-8")

with open("requirements_utf8.txt", "w", encoding="utf-8") as f:
    f.write(content)

lines = [l.strip() for l in content.splitlines() if l.strip()]
print(f"OK — {len(lines)} paquetes en requirements_utf8.txt")
for line in lines[:8]:
    print(f"  {line}")
if len(lines) > 8:
    print(f"  ... y {len(lines) - 8} más")

# Verificar que Django está presente
django_lines = [l for l in lines if l.lower().startswith("django")]
if not django_lines:
    print("ERROR: Django no encontrado en requirements!", file=sys.stderr)
    sys.exit(1)
print(f"Django detectado: {django_lines}")
