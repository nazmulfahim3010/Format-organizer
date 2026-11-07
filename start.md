# SmartDoc — How to Start & Run the Application

This guide explains how to start, run, and access the **SmartDoc** application on your machine.

---

## 🟢 1. Current Live Status

The SmartDoc application is **currently running right now**:

* **Web Application URL:** [http://localhost:8000/](http://localhost:8000/) *(or [http://127.0.0.1:8000/](http://127.0.0.1:8000/))*
* **Backend Health Check:** [http://localhost:8000/api/health](http://localhost:8000/api/health)
* **Status:** `{"status": "ok", "pdf_export": true}` (FastAPI server active, LibreOffice PDF engine ready)

> Simply click or open **[http://localhost:8000/](http://localhost:8000/)** in your browser to use the application immediately!

---

## ⚡ 2. One-Click Start (Easiest Way on Windows)

We provide one-click runner scripts in the root project folder:

* **Double-click `run.bat`** (or right-click `run.ps1` $\rightarrow$ Run with PowerShell):
  * Automatically detects and frees port 8000 if an old or frozen process is using it.
  * Launches the SmartDoc backend and frontend server.
  * Automatically opens **[http://localhost:8000/](http://localhost:8000/)** in your default web browser.

---

## 🚀 3. Manual Command-Line Startup

### Option A: All-in-One Mode (Recommended)

In this mode, the FastAPI backend automatically serves both the **REST API** (`/api/...`) and the pre-built **React Frontend** (`/`) from a single command on **Port 8000**.

#### Windows (PowerShell / Command Prompt):
> **Note for Windows:** Use `python`, not `python3` (Windows Store execution alias can cause `python3` to fail with "The file cannot be accessed by the system").

```powershell
# 1. Navigate to the project root
cd "c:\Users\Acer\OneDrive\Desktop\project_for_automated_docx formated"

# 2. Start the Uvicorn server
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

#### macOS / Linux (Terminal):
```bash
cd "/path/to/project_for_automated_docx formated"
python3 -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

* Once started, open **`http://localhost:8000`** in your browser.

---

### Option B: Development Mode (Active Coding & Hot Reloading)

Use this mode if you are actively editing frontend React code or backend Python code and want live hot-reloading (HMR).

#### Step 1: Start Backend (Terminal 1)
```powershell
cd "c:\Users\Acer\OneDrive\Desktop\project_for_automated_docx formated\backend"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

#### Step 2: Start Frontend Dev Server (Terminal 2)
```powershell
cd "c:\Users\Acer\OneDrive\Desktop\project_for_automated_docx formated\frontend"
npm run dev
```

* In development mode, open the Vite dev server at: **`http://localhost:5173`**
* Changes to frontend files reload instantly in the browser.

---

### Option C: Rebuilding the Frontend After Code Changes

If you modify code in `frontend/src/` and want to compile it for the all-in-one server on port 8000:

```powershell
cd "c:\Users\Acer\OneDrive\Desktop\project_for_automated_docx formated\frontend"
npm run build
```

This compiles your changes into `frontend/dist/`.

---

## 🛠️ 4. Troubleshooting & FAQ

### Issue: Port 8000 is already in use (`[Errno 10048]`)
If you see:
```text
ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000)
```
**Cause:** A background Python or Uvicorn process is already bound to port 8000.

**Fix (Automated):**
Run `run.bat` or `run.ps1` — they automatically terminate any stuck process on port 8000 and restart the server.

**Fix (Manual via PowerShell):**
```powershell
# 1. Find and kill the process holding port 8000
$p = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique
if ($p) { Stop-Process -Id $p -Force }

# 2. Start the server
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

---

### Issue: `python3` command fails on Windows
If running `python3` displays:
```text
The file cannot be accessed by the system
```
**Fix:** Run `python` instead of `python3`. Windows uses `python.exe`.

---

### Issue: PDF Export is disabled (`"pdf_export": false`)
**Cause:** LibreOffice was not detected on the standard paths.

**Fix:**
Set the explicit path in PowerShell:
```powershell
$env:SMARTDOC_SOFFICE="C:\Program Files\LibreOffice\program\soffice.exe"
```
Then restart the backend server.

---

## 📖 5. Quick Walkthrough: Using SmartDoc

1. **Open the App:** Navigate to [http://localhost:8000/](http://localhost:8000/).
2. **Create Account:** Click **Register** and sign up with your email and password.
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
   - Check the live in-browser preview on the right panel.
   - Click **Download DOCX** for the final Word document, or **Export PDF** for a publication-ready PDF.
