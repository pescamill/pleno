#!/bin/sh
# Instalador de Pleno para Mac y Linux.
#   curl -LsSf https://raw.githubusercontent.com/pescamill/pleno/main/instalar.sh | sh
# Instala uv (que trae su propio Python), descarga Pleno en ~/Pleno, crea un acceso directo y lo abre.
set -e
DEST="${PLENO_DIR:-$HOME/Pleno}"
ZIP_URL="https://github.com/pescamill/pleno/archive/refs/heads/main.zip"

echo ""
echo "  Instalando Pleno en $DEST"
echo ""

if ! command -v uv >/dev/null 2>&1; then
  echo "  1/3  Instalando uv (administra Python por ti)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

echo "  2/3  Descargando Pleno…"
TMP="$(mktemp -d)"
curl -LsSf "$ZIP_URL" -o "$TMP/pleno.zip"
unzip -q "$TMP/pleno.zip" -d "$TMP"
mkdir -p "$DEST"
# Keep the person's data (data/) when updating an existing install.
(cd "$TMP"/pleno-main && tar cf - --exclude ./data .) | (cd "$DEST" && tar xf -)
rm -rf "$TMP"

echo "  3/3  Preparando Python y dependencias (la primera vez tarda un poco)…"
(cd "$DEST" && uv sync --quiet)

LAUNCHER="$DEST/Abrir Pleno.command"
cat > "$LAUNCHER" <<LAUNCH
#!/bin/sh
export PATH="\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH"
cd "$DEST" && exec uv run --quiet python -m pleno abrir
LAUNCH
chmod +x "$LAUNCHER"

if [ "$(uname)" = "Darwin" ]; then
  cp "$LAUNCHER" "$HOME/Desktop/Pleno.command" 2>/dev/null && chmod +x "$HOME/Desktop/Pleno.command" || true
  echo ""
  echo "  Listo. En tu Escritorio quedó «Pleno»: dale doble clic para abrirlo cuando quieras."
else
  mkdir -p "$HOME/.local/bin"
  cp "$LAUNCHER" "$HOME/.local/bin/pleno" && chmod +x "$HOME/.local/bin/pleno"
  echo ""
  echo "  Listo. Para abrirlo cuando quieras, escribe:  pleno"
fi
echo "  Abriendo Pleno en tu navegador…"
echo ""
exec "$LAUNCHER"
