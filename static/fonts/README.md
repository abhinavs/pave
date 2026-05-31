# Fonts

Self-hosted woff2 type. Pave does not fetch fonts from Google at runtime, so
they ship in the repo as static assets.

| File                       | Family         | Role             | Notes                |
|----------------------------|----------------|------------------|----------------------|
| `inter.woff2`              | Inter          | sans (body, UI)  | variable, 100 - 900  |
| `newsreader.woff2`         | Newsreader     | serif (display)  | variable, 200 - 800  |
| `ibm-plex-mono-400.woff2`  | IBM Plex Mono  | mono (code)      | static, regular      |
| `ibm-plex-mono-600.woff2`  | IBM Plex Mono  | mono (code)      | static, semibold     |

Inter and Newsreader are the **latin** subset of each family's variable font.
IBM Plex Mono ships as discrete static weights upstream rather than a single
variable file, so we carry 400 and 600 individually - the only weights
`source.css` actually addresses. If a site grows to other scripts, swap in
the matching subset (cyrillic, greek, vietnamese, ...) using the same recipe.

## Refresh recipe

Google Fonts redeploys subset URLs occasionally; if a font looks broken, refetch:

```bash
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
cd static/fonts

# Variable fonts - one file per family, the wght range is the axis.
for spec in \
  "Inter:wght@100..900|inter" \
  "Newsreader:opsz,wght@6..72,200..800|newsreader"; do
  family=${spec%|*}
  name=${spec##*|}
  css=$(curl -s -A "$UA" "https://fonts.googleapis.com/css2?family=$family&display=swap")
  url=$(echo "$css" | awk '/\/\* latin \*\//{flag=1;next} flag && /src:/{print; flag=0}' | grep -oE 'https://[^)]+\.woff2' | head -1)
  curl -sS -o "$name.woff2" "$url"
done

# IBM Plex Mono - static weights, one file per weight.
for w in 400 600; do
  css=$(curl -s -A "$UA" "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@${w}&display=swap")
  url=$(echo "$css" | awk '/\/\* latin \*\//{flag=1;next} flag && /src:/{print; flag=0}' | grep -oE 'https://[^)]+\.woff2' | head -1)
  curl -sS -o "ibm-plex-mono-${w}.woff2" "$url"
done
```

The modern Chrome User-Agent is required: the bare default UA returns static
woff URLs instead of variable woff2s (and worse fallbacks for Plex Mono).
