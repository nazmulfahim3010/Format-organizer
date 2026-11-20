# SmartDoc — How to Start & Run the Application

This guide explains how to run the latest version of the **SmartDoc** application on your machine.

---

## ⚡ 1. The Fastest Way: Single Command to Run Latest Program

To automatically compile the latest frontend changes, free up port 8000, open your browser, and start the unified server, run **one** of the following:

### Option A: PowerShell (Terminal)
From the project root (`Format-organizer`), run:
```powershell
.\run.ps1
```
> *Or run as a direct one-liner without scripts:*
> ```powershell
> npm --prefix frontend run build; python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
> ```

### Option B: Command Prompt (CMD)
```cmd
run.bat
```
> *Or run as a direct one-liner:*
> ```cmd
> npm --prefix frontend run build && python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
> ```

### Option C: Windows File Explorer (One-Click)
* Double-click **`run.bat`** in this folder.

### What this single command does automatically:
1. **Compiles latest frontend code** (`npm --prefix frontend run build` $\rightarrow$ `frontend/dist/`), ensuring all your recent UI edits are live.
2. **Frees port 8000** if an old or unresponsive server process is running.
3. **Opens your default browser** to **[http://localhost:8000/](http://localhost:8000/)**.
4. **Starts the SmartDoc FastAPI backend** that serves both the REST API and the React frontend.

---

## 🟢 2. Live Application Access

Once started, access the app at:
* **Web Application:** [http://localhost:8000/](http://localhost:8000/) *(or [http://127.0.0.1:8000/](http://127.0.0.1:8000/))*
* **Backend API Health Check:** [http://localhost:8000/api/health](http://localhost:8000/api/health)
  * Expected response: `{"status": "ok", "pdf_export": true}`

---

## 💻 3. Development Mode (Live Hot Reloading / HMR)

Use this mode if you are actively editing frontend React code or backend Python code and want live hot-reloading without rebuilding each time:

### Step 1: Start Backend (Terminal 1)
```powershell
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

### Step 2: Start Vite Dev Server (Terminal 2)
```powershell
npm --prefix frontend run dev
```

* Open the Vite dev server at **`http://localhost:5173`**.
* Any edits to files in `frontend/src/` update instantly in your browser via Vite HMR.
* API calls from `:5173/api/...` are automatically proxied to `:8000`.

---

## 🛠️ 4. Troubleshooting & FAQ

### Issue: Port 8000 is occupied (`[Errno 10048]`)
`run.bat` and `run.ps1` automatically detect and terminate any stuck process on port 8000 before starting.

To manually free port 8000 in PowerShell:
```powershell
$p = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
if ($p) { Stop-Process -Id $p -Force }
```

### Issue: `python3` command fails on Windows
If `python3` displays `"The file cannot be accessed by the system"`, run `python` instead of `python3`. Windows uses `python.exe`.

### Issue: PDF Export disabled (`"pdf_export": false`)
**Cause:** LibreOffice was not detected in the default program directory.

**Fix:** Set the path in PowerShell before starting:
```powershell
$env:SMARTDOC_SOFFICE="C:\Program Files\LibreOffice\program\soffice.exe"
```

---

## 📖 5. Quick Walkthrough: Using SmartDoc

1. **Open the App:** Navigate to [http://localhost:8000/](http://localhost:8000/).
2. **Create Account:** Click **Register** and sign up with an email and password.
3. **Upload Template:**
   - Go to the **Templates** tab.
   - Upload any `.docx` file (e.g. university dissertation, journal paper, company memo).
   - Review the auto-detected styles, table rules, and language settings.
   - Click **Approve**.
4. **Create a Document:**
   - Go to the **Documents** tab and click **+ New Document**.
   - Select your approved template.
5. **Paste Content:**
   - Open the **Paste zone**.
   - Copy content from Microsoft Word, Google Docs, ChatGPT, or Excel and paste (`Ctrl+V`).
   - Click **Insert**.
6. **Preview & Download:**
   - Review live in-browser preview on the right panel.
   - Click **Download DOCX** or **Export PDF**.
