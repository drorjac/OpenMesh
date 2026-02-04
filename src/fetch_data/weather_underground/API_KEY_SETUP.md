# Weather Underground API Key Setup

You need an API key to fetch WU data. This page explains how to get one and how to set it up so the pipeline can use it.

---

## 1. Get your API key

1. Go to: https://www.wunderground.com/member/api-keys  
2. Sign in or create an account.  
3. Create an API key and copy it (you can use the free tier).

Keep the key private. Do not commit it to the repo or share it.

---

## 2. Configure the key (choose one)

The pipeline looks for the key in this order: environment variable, then `config.py` in this folder, then the `--api-key` flag on the command line.

### Option A: Environment variable (recommended)

**One-time (current terminal only):**
```bash
export WU_API_KEY="paste_your_key_here"
```

**So it stays set in every new terminal:**  
Add the same line to your shell startup file so it runs automatically when you open a terminal.

- On macOS (and many Linux setups), that file is `~/.zshrc`.  
- On some systems it’s `~/.bashrc`.

Open the file (e.g. `nano ~/.zshrc` or `open -e ~/.zshrc`), add this line at the end:
```bash
export WU_API_KEY="paste_your_key_here"
```
Save, then in the terminal run:
```bash
source ~/.zshrc
```
(Use `source ~/.bashrc` if you use bash.)

After that, every new terminal will have `WU_API_KEY` set. To check: `echo $WU_API_KEY` — you should see your key.

### Option B: Config file (fallback)

If you prefer not to use environment variables, open `config.py` in this folder, find the line with `WU_API_KEY` (around line 252), and set it to your key. Do not commit that change if the repo is shared; use Option A instead.

### Option C: Pass the key when you run a command

You can pass the key only for that run:
```bash
python src/fetch_data/main.py wu --api-key paste_your_key_here -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-30
```

---

## 3. Run the pipeline

**From the command line (from project root):**
```bash
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-30
```
If the key is set (Option A or B), you don’t need `--api-key`. Data is saved under `dataset/raw/fetched/wu/`.

**From the notebook:**  
Open `wu_pipeline.ipynb`, set stations and date range in the config cell, then run all cells. The notebook uses the same key (env var or config).

**Quick test:**  
To confirm the key is found:
```bash
python -c "from weather_underground.config import get_api_key; print('Key found:', get_api_key()[:8] + '...')"
```
Or run a short fetch:
```bash
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-02
```

---

## If something goes wrong

**"WU_API_KEY not found"**  
Set the key using one of the options above. If you used Option A, check with `echo $WU_API_KEY` in the same terminal where you run the script; if it’s empty, run `source ~/.zshrc` (or `~/.bashrc`) or open a new terminal.

**API says invalid key**  
Check the key at https://www.wunderground.com/member/api-keys, make sure there are no extra spaces or quotes when you paste it, and try creating a new key if needed.

For full CLI options see `src/fetch_data/USAGE.md`. The key is used in `config.py` (`get_api_key`) and by `wu_fetch.py` and `main.py`.
