# Weather Underground API Key Configuration

Complete guide for setting up and managing your Weather Underground API key.

## 🔑 Overview

Weather Underground requires an API key for authentication. This guide explains all configuration methods and best practices.

**Get your API key:** https://www.wunderground.com/member/api-keys

---

## Configuration Methods (Priority Order)

The system checks for API keys in this order (highest to lowest priority):

1. **Environment Variable** ⭐ (RECOMMENDED)
2. **Config File** (Fallback)
3. **CLI Argument** (Temporary override)

---

## Method 1: Environment Variable (Recommended)

### Why Use This Method?
- ✅ Most secure (not stored in code)
- ✅ Works across all projects
- ✅ Easy to update without editing files
- ✅ Safe for version control (key not in repo)

### Setup Instructions

**For Current Session:**
```bash
export WU_API_KEY="your_api_key_here"
```

**For Persistence (macOS/Linux):**

Add to your shell profile:
```bash
# For zsh (default on macOS)
echo 'export WU_API_KEY="your_api_key_here"' >> ~/.zshrc
source ~/.zshrc

# For bash
echo 'export WU_API_KEY="your_api_key_here"' >> ~/.bashrc
source ~/.bashrc
```

**Verify it's set:**
```bash
echo $WU_API_KEY
# Should output your API key
```

**Test in Python:**
```python
import os
print(os.environ.get('WU_API_KEY'))
```

---

## Method 2: Config File (Fallback)

### When to Use
- Quick testing
- If you can't set environment variables
- As a temporary fallback

### Setup Instructions

1. Open `config.py` in this folder
2. Find the `WU_API_KEY` constant (around line 255)
3. Set your key:
   ```python
   WU_API_KEY = 'your_api_key_here'  # Fallback only - use env var instead
   ```

**⚠️ Important:**
- This method is less secure
- Don't commit API keys to version control
- Consider using environment variable instead

---

## Method 3: CLI Argument (Temporary)

### When to Use
- One-time fetch without permanent setup
- Testing different API keys
- Overriding existing configuration

### Usage

```bash
python src/fetch_data/main.py wu \
    --api-key your_api_key_here \
    -s KNYNEWYO1805 \
    --start 2024-01-01 \
    --end 2024-01-30
```

This overrides both environment variable and config file for that single command.

---

## How It Works

The `get_api_key()` function in `config.py` automatically handles the priority:

```python
def get_api_key():
    import os
    # Priority: env var > config file
    api_key = os.environ.get('WU_API_KEY') or WU_API_KEY
    
    if not api_key or api_key == '':
        raise ValueError(
            "WU_API_KEY not found. Set it as environment variable:\n"
            "  export WU_API_KEY='your_key_here'\n"
            "Or add to ~/.zshrc for persistence."
        )
    
    return api_key
```

**Flow:**
1. Check `WU_API_KEY` environment variable
2. If not found, check `WU_API_KEY` in config.py
3. If still not found, raise error with instructions

---

## Verification

### Test Your Configuration

**Option 1: Quick Test**
```bash
python -c "from weather_underground.config import get_api_key; print('✓ API key found:', get_api_key()[:10] + '...')"
```

**Option 2: Fetch Test Data**
```bash
python src/fetch_data/main.py wu -s KNYNEWYO1805 --start 2024-01-01 --end 2024-01-02
```

If successful, you'll see data being fetched. If not, you'll get a clear error message.

---

## Troubleshooting

### Error: "WU_API_KEY not found"

**Solution 1:** Set environment variable
```bash
export WU_API_KEY="your_key"
```

**Solution 2:** Add to config.py
```python
WU_API_KEY = 'your_key_here'
```

**Solution 3:** Use CLI flag
```bash
python src/fetch_data/main.py wu ... --api-key your_key_here
```

### Error: "Invalid API key" or "Authentication failed"

- Verify your API key is correct
- Check if your API key is active at https://www.wunderground.com/member/api-keys
- Ensure no extra spaces or quotes around the key
- Try regenerating a new API key

### Environment Variable Not Persisting

- Make sure you added it to the correct shell profile (`~/.zshrc` or `~/.bashrc`)
- Run `source ~/.zshrc` (or `source ~/.bashrc`) after editing
- Open a new terminal window to test
- Check with `echo $WU_API_KEY`

### Multiple API Keys

If you need to use different keys for different projects:

**Option 1:** Use CLI flag for specific runs
```bash
python src/fetch_data/main.py wu ... --api-key different_key
```

**Option 2:** Set per-project environment variable
```bash
# In project directory
export WU_API_KEY="project_specific_key"
```

---

## Security Best Practices

1. **Never commit API keys to version control**
   - Use `.gitignore` to exclude config files with keys
   - Use environment variables instead

2. **Use environment variables for production**
   - More secure than hardcoding
   - Easy to rotate keys

3. **Rotate keys regularly**
   - Generate new keys periodically
   - Revoke old keys when no longer needed

4. **Limit API key permissions**
   - Only grant necessary permissions
   - Monitor API usage

---

## Quick Reference

| Method | Security | Persistence | Best For |
|--------|----------|-------------|----------|
| Environment Variable | ⭐⭐⭐⭐⭐ | ✅ Yes | Production, shared repos |
| Config File | ⭐⭐ | ✅ Yes | Quick testing, local dev |
| CLI Argument | ⭐⭐⭐⭐ | ❌ No | One-time use, testing |

---

## Related Files

- **`config.py`** - Contains `get_api_key()` function and fallback key
- **`README.md`** - Main documentation for WU data fetching
- **`wu_fetch.py`** - Uses `get_api_key()` for API calls
- **`main.py`** - CLI interface that accepts `--api-key` flag

---

## Need Help?

- **API Key Issues:** https://www.wunderground.com/member/api-keys
- **Main Documentation:** See `README.md` in this folder
- **CLI Usage:** See `src/fetch_data/USAGE.md`
