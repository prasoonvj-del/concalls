#!/data/data/com.termux/files/usr/bin/bash
# Installs Concall Summaries in Termux on your tablet.
# Run:  bash ~/storage/shared/Download/ConcallSummaries/setup_tablet.sh
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/ConcallSummaries"

echo "== Installing Python and tools (a few minutes the first time) =="
pkg update -y
pkg install -y python curl termux-tools
pip install --no-cache-dir requests pypdf markdown feedparser

echo "== Copying the tool to $DEST =="
mkdir -p "$DEST"
cp "$SRC/concalls.py" "$SRC/news.py" "$SRC/site_builder.py" "$SRC/daily.py" "$SRC/README.md" "$SRC/schedule_tablet.sh" "$DEST/"
rm -rf "$DEST/web" && cp -r "$SRC/web" "$DEST/web"
# your settings, library and summaries: copied only the first time, never overwritten
for item in config.ini feeds.opml data summaries news; do
  if [ -e "$SRC/$item" ] && [ ! -e "$DEST/$item" ]; then cp -r "$SRC/$item" "$DEST/"; fi
done

echo "== Adding a home-screen shortcut (needs the Termux:Widget app) and a 'concalls' command =="
mkdir -p "$HOME/.shortcuts"
cat > "$HOME/.shortcuts/Concall Summaries" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/ConcallSummaries && python concalls.py
EOS
chmod +x "$HOME/.shortcuts/Concall Summaries"
cat > "$HOME/.shortcuts/Morning Brief" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/ConcallSummaries && python news.py
EOS
chmod +x "$HOME/.shortcuts/Morning Brief"
grep -q "alias concalls=" "$HOME/.bashrc" 2>/dev/null || \
  echo 'alias concalls="cd ~/ConcallSummaries && python concalls.py"' >> "$HOME/.bashrc"
grep -q "alias brief=" "$HOME/.bashrc" 2>/dev/null || \
  echo 'alias brief="cd ~/ConcallSummaries && python news.py"' >> "$HOME/.bashrc"

echo
echo "Done. Close and reopen Termux, then type:  concalls   (or: brief  for the news brief)"
echo "To get the news brief automatically every morning:  bash ~/ConcallSummaries/schedule_tablet.sh"
echo "(or tap the 'Concall Summaries' Termux widget on your home screen)"
