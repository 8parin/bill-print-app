# Windows ZIP Distribution — Lessons Learned

## 1. Batch File Encoding (.bat files)
- **Never use** `chcp 65001` in .bat files — it causes CMD to misparse subsequent `echo` commands, showing "'ho' is not recognized" errors
- **Never use** non-ASCII characters in .bat files (no Thai, no em dash `—`, no smart quotes) — they corrupt parsing
- Save .bat files as plain ASCII/ANSI, not UTF-8 with BOM

## 2. Python Detection on Windows
Windows Python 3.x installs may register as:
- `python` (if "Add Python to PATH" was checked)
- `py` (Windows Launcher — always available, independent of PATH)
- `python3` (less common)

Always try all three in order:
```bat
set PYTHON_CMD=
python --version >nul 2>&1
if not errorlevel 1 set PYTHON_CMD=python
if "%PYTHON_CMD%"=="" (
    py --version >nul 2>&1
    if not errorlevel 1 set PYTHON_CMD=py
)
if "%PYTHON_CMD%"=="" (
    python3 --version >nul 2>&1
    if not errorlevel 1 set PYTHON_CMD=python3
)
```

## 3. goto Inside if () Blocks
`goto` inside parenthesized `if ()` blocks in Windows batch is unreliable — CMD can't find the label.
Use `if not errorlevel 1 set VAR=value` pattern instead of `goto`.

## 4. Desktop Shortcut — Use PowerShell .lnk, NOT a generated .bat
Generated `.bat` shortcut files are unreliable:
- Unicode path chars get corrupted when written via `echo`
- Even with 8.3 short path trick, double-click may silently fail
- `.bat` files can trigger SmartScreen security warnings

**Best approach**: use PowerShell to create a proper `.lnk` shortcut via `WScript.Shell`.
Write the PS script to a temp file first to avoid command-line escaping hell:
```bat
set APP_PATH=%~dp0
set "PS_TEMP=%TEMP%\batchbill_sc.ps1"
> "%PS_TEMP%"  echo $ws = New-Object -ComObject WScript.Shell
>> "%PS_TEMP%" echo $sc = $ws.CreateShortcut("$env:USERPROFILE\Desktop\BatchBill.lnk")
>> "%PS_TEMP%" echo $sc.TargetPath = "cmd.exe"
>> "%PS_TEMP%" echo $sc.Arguments = "/k run.bat"
>> "%PS_TEMP%" echo $sc.WorkingDirectory = "%APP_PATH%"
>> "%PS_TEMP%" echo $sc.Save()
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_TEMP%"
del "%PS_TEMP%" 2>nul
```
- `WorkingDirectory` ensures CMD opens in the app folder — run.bat finds app.py
- `.lnk` files don't trigger SmartScreen warnings
- Tell users to keep folder name English-only (no Thai/Unicode) — still safest

## 5. Working Directory for run.bat
When called from a desktop shortcut, run.bat's working directory is Desktop, not the app folder.
Always add at the top of run.bat:
```bat
cd /d "%~dp0"
```
This makes run.bat always cd to its own folder before running app.py.

## 6. Thai Font in PDF (Windows vs macOS)
Font paths are OS-specific:
- macOS: `/System/Library/Fonts/Supplemental/Tahoma.ttf`
- Windows: `C:\Windows\Fonts\tahoma.ttf` (bold: `tahomabd.ttf`)

Always detect OS and try multiple candidate paths — never hardcode one OS path.
Use `sys.platform == 'win32'` to branch.

**Check ALL places that load fonts** — each PDF generator (bills, sales report, etc.)
loads fonts independently. Fix every one, not just the first you find.

In this project:
- `src/pdf_generator_reportlab.py` → bills PDF
- `app.py` → sales report PDF (separate font loading, same fix needed)

## 7. General Checklist Before Windows Distribution
- [ ] All .bat files are ASCII-only (no Thai, no special chars, no chcp 65001)
- [ ] Python detection tries `python`, `py`, `python3`
- [ ] run.bat starts with `cd /d "%~dp0"`
- [ ] Desktop shortcut uses PowerShell `.lnk` (not generated `.bat`)
- [ ] ALL PDF generators load fonts from OS-appropriate paths (check every file)
- [ ] Folder name is English-only (advise users)
- [ ] Tested with English-only folder path
