"""
PDF Tool — FastAPI Backend
Compresor y Divisor de PDF usando Ghostscript.

Uso:
    pip install fastapi uvicorn
    python main.py

Luego abre frontend/index.html en el navegador.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import signal
import tkinter as tk
from tkinter import filedialog
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

CONFIG_FILE = "pdf_tool_config.json"

if sys.platform == "win32":
    DEFAULT_GS = r"C:\Program Files\gs\gs10.06.0\bin\gswin64c.exe"
    SUBPROCESS_FLAGS = 0x08000000
else:
    DEFAULT_GS = "gs"
    SUBPROCESS_FLAGS = 0

PROFILES = {
    "1": {
        "name": "Compresión Extrema",
        "settings": "/screen",
        "color_res": "72", "gray_res": "72", "mono_res": "96",
        "description": "Máxima compresión posible, calidad muy básica",
        "reduction": "80–95%",
        "icon": "💥",
    },
    "2": {
        "name": "Máxima Compresión",
        "settings": "/screen",
        "color_res": "96", "gray_res": "96", "mono_res": "150",
        "description": "Archivos muy pequeños, calidad básica. Ideal para web y email.",
        "reduction": "70–85%",
        "icon": "🔥",
    },
    "3": {
        "name": "Alta (eBooks/Tablets)",
        "settings": "/ebook",
        "color_res": "150", "gray_res": "150", "mono_res": "300",
        "description": "Buen equilibrio entre tamaño y calidad visual.",
        "reduction": "50–70%",
        "icon": "📱",
    },
    "4": {
        "name": "Media (Impresión)",
        "settings": "/printer",
        "color_res": "300", "gray_res": "300", "mono_res": "600",
        "description": "Calidad de impresión estándar, tamaño moderado.",
        "reduction": "30–50%",
        "icon": "🖨️",
    },
    "5": {
        "name": "Mínima (Alta calidad)",
        "settings": "/prepress",
        "color_res": "300", "gray_res": "300", "mono_res": "1200",
        "description": "Máxima calidad conservada, reducción mínima.",
        "reduction": "10–30%",
        "icon": "💎",
    },
    "6": {
        "name": "Personalizado",
        "settings": "custom",
        "color_res": "150", "gray_res": "150", "mono_res": "300",
        "description": "Configuración manual de resolución y calidad JPEG.",
        "reduction": "Variable",
        "icon": "⚙️",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# DATACLASS CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PDFToolConfig:
    input_dir: str = ""
    output_dir: str = ""
    gs_path: str = DEFAULT_GS
    operation: str = "1"          # "1"=compress, "2"=split, "3"=both
    profile_id: str = "3"
    pages_per_file: int = 20
    custom_resolution: int = 150
    custom_jpeg_quality: float = 0.8
    open_output: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    input_dir: str
    output_dir: str
    gs_path: str = DEFAULT_GS
    operation: str = "1"
    profile_id: str = "3"
    pages_per_file: int = 20
    custom_resolution: int = 150
    custom_jpeg_quality: float = 0.8
    open_output: bool = False


class ConfigSaveRequest(BaseModel):
    config: dict


# ─────────────────────────────────────────────────────────────────────────────
# WORKER BRIDGE
# ─────────────────────────────────────────────────────────────────────────────

class OperationCancelled(Exception):
    pass


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self.active_process: Optional[subprocess.Popen] = None

    def cancel(self) -> None:
        self._cancelled.set()
        proc = self.active_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                for _ in range(10):
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def check(self) -> None:
        if self._cancelled.is_set():
            raise OperationCancelled()


class WorkerBridge:
    def __init__(self) -> None:
        self.q: queue.Queue[Tuple[str, Any]] = queue.Queue()
        self.cancel_token = CancellationToken()

    def log(self, message: str, level: str = "INFO") -> None:
        self.q.put(("log", {"message": message, "level": level,
                             "ts": datetime.now().strftime("%H:%M:%S")}))

    def progress(self, current: int, total: int, label: str = "") -> None:
        self.q.put(("progress", {"current": current, "total": total, "label": label}))

    def stats(self, data: dict) -> None:
        self.q.put(("stats", data))

    def done(self, success: bool, summary: str = "") -> None:
        self.q.put(("done", {"success": success, "summary": summary}))

    def drain(self) -> List[Tuple[str, Any]]:
        events = []
        while True:
            try:
                events.append(self.q.get_nowait())
            except queue.Empty:
                break
        return events


# ─────────────────────────────────────────────────────────────────────────────
# LÓGICA GHOSTSCRIPT
# ─────────────────────────────────────────────────────────────────────────────

def _run_gs(gs_path: str, args: List[str], bridge: WorkerBridge) -> Tuple[int, str]:
    cmd = [gs_path] + args
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
            errors="replace", creationflags=SUBPROCESS_FLAGS,
        )
    except FileNotFoundError:
        raise RuntimeError(f"Ghostscript no encontrado: {gs_path}\nInstala Ghostscript o ajusta la ruta.")

    bridge.cancel_token.active_process = proc
    lines = []
    try:
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if line:
                lines.append(line)
            if bridge.cancel_token.is_cancelled():
                break
        proc.wait()
    finally:
        bridge.cancel_token.active_process = None

    return proc.returncode, "\n".join(lines)


def _get_page_count(gs_path: str, file_path: str, bridge: WorkerBridge) -> int:
    # Intentar pdfinfo primero (Poppler)
    try:
        result = subprocess.run(
            ["pdfinfo", file_path], capture_output=True, text=True,
            timeout=10, creationflags=SUBPROCESS_FLAGS,
        )
        for line in result.stdout.splitlines():
            if line.strip().startswith("Pages:"):
                return int(line.split(":")[1].strip())
    except Exception:
        pass

    # Ghostscript
    ps_path = file_path.replace("\\", "/").replace("(", r"\(").replace(")", r"\)")
    args = [
        "-dNODISPLAY", "-dNOSAFER", "-dNOPAUSE", "-dBATCH", "-dQUIET",
        "-c", f"({ps_path}) (r) file runpdfbegin pdfpagecount = quit"
    ]
    try:
        rc, out = _run_gs(gs_path, args, bridge)
        if rc == 0 and out.strip().isdigit():
            return int(out.strip())
    except Exception:
        pass

    # Validez sin conteo
    try:
        rc2, _ = _run_gs(gs_path, ["-sDEVICE=nullpage", "-dNOPAUSE", "-dBATCH",
                                    "-dQUIET", "-dNOSAFER", file_path], bridge)
        if rc2 == 0:
            return -1
    except Exception:
        pass

    return 0


def _build_compress_args(profile_id: str, profile: dict, output_file: str,
                          input_file: str, custom_res: int, custom_jq: float) -> List[str]:
    args = [
        "-dNOSAFER", "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4", "-dNOPAUSE", "-dQUIET", "-dBATCH",
    ]
    if profile_id in ("1", "2"):
        args += [
            f"-dPDFSETTINGS={profile['settings']}",
            f"-dColorImageResolution={profile['color_res']}",
            f"-dGrayImageResolution={profile['gray_res']}",
            f"-dMonoImageResolution={profile['mono_res']}",
        ]
    elif profile_id in ("3", "4"):
        args += [f"-dPDFSETTINGS={profile['settings']}"]
    elif profile_id == "5":
        args += [
            "-dPDFSETTINGS=/prepress",
            "-dDownsampleColorImages=false",
            "-dDownsampleGrayImages=false",
            "-dDownsampleMonoImages=false",
        ]
    elif profile_id == "6":
        args += [
            "-dPDFSETTINGS=/ebook",
            f"-dColorImageResolution={custom_res}",
            f"-dGrayImageResolution={custom_res}",
            f"-dJPEGQ={custom_jq}",
        ]
    args += [f"-sOutputFile={output_file}", input_file]
    return args


def _split_pdf(gs_path: str, input_file: str, output_dir: str,
               pages_per_file: int, total_pages: int,
               base_name: str, bridge: WorkerBridge) -> List[str]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    split_files: List[str] = []
    part = 1
    start_page = 1

    while start_page <= total_pages and part <= 100:
        bridge.cancel_token.check()
        end_page = min(start_page + pages_per_file - 1, total_pages)
        output_file = str(Path(output_dir) / f"{base_name}_part{part}_{timestamp}.pdf")

        args = [
            "-dNOSAFER", "-sDEVICE=pdfwrite", "-dNOPAUSE", "-dBATCH", "-dQUIET",
            f"-dFirstPage={start_page}", f"-dLastPage={end_page}",
            f"-sOutputFile={output_file}", input_file,
        ]
        rc, _ = _run_gs(gs_path, args, bridge)

        if rc == 0 and Path(output_file).exists() and Path(output_file).stat().st_size > 1000:
            split_files.append(output_file)
        else:
            try:
                Path(output_file).unlink(missing_ok=True)
            except Exception:
                pass
            break

        start_page = end_page + 1
        part += 1

    return split_files


def run_pdf_processing(cfg: PDFToolConfig, bridge: WorkerBridge) -> None:
    if not Path(cfg.input_dir).is_dir():
        raise FileNotFoundError(f"Carpeta de entrada no existe: {cfg.input_dir}")

    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)

    bridge.log("Verificando Ghostscript…", "INFO")
    rc, ver = _run_gs(cfg.gs_path, ["-v"], bridge)
    if rc != 0:
        raise RuntimeError(f"Ghostscript no responde en: {cfg.gs_path}")
    bridge.log(f"✓ {ver.splitlines()[0] if ver else 'Ghostscript detectado'}", "SUCCESS")

    all_pdfs = sorted(Path(cfg.input_dir).glob("*.pdf"))
    if not all_pdfs:
        raise FileNotFoundError(f"No se encontraron PDFs en: {cfg.input_dir}")

    pdfs = all_pdfs
    total = len(pdfs)
    bridge.log(f"✓ {total} archivo(s) PDF a procesar", "SUCCESS")
    bridge.log(f"  Entrada  : {cfg.input_dir}", "INFO")
    bridge.log(f"  Salida   : {cfg.output_dir}", "INFO")
    op_label = {"1": "Solo comprimir", "2": "Solo dividir", "3": "Comprimir y dividir"}.get(cfg.operation, "?")
    bridge.log(f"  Operación: {op_label}", "INFO")

    if cfg.operation in ("1", "3"):
        profile = PROFILES[cfg.profile_id]
        bridge.log(f"  Perfil   : {profile['icon']} {profile['name']}", "INFO")

    if cfg.operation in ("2", "3"):
        bridge.log(f"  Páginas/archivo: {cfg.pages_per_file}", "INFO")

    stats = {
        "ok": 0, "fail": 0, "skipped": 0, "generated": 0,
        "total_orig": 0.0, "total_proc": 0.0, "failed_files": [],
    }
    profile = PROFILES[cfg.profile_id]
    start_time = datetime.now()

    for idx, pdf_path in enumerate(pdfs, 1):
        bridge.cancel_token.check()
        bridge.progress(idx, total, pdf_path.name)
        bridge.log(f"[{idx}/{total}] {pdf_path.name}", "INFO")

        orig_mb = pdf_path.stat().st_size / (1024 * 1024)
        stats["total_orig"] += orig_mb
        bridge.log(f"  Tamaño original: {orig_mb:.2f} MB", "DIM")

        base_name = pdf_path.stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        proc_files: List[str] = []

        try:
            total_pages = 1
            if cfg.operation in ("2", "3"):
                bridge.log("  Analizando páginas…", "INFO")
                count = _get_page_count(cfg.gs_path, str(pdf_path), bridge)
                if count > 0:
                    total_pages = count
                    bridge.log(f"  ✓ {total_pages} páginas", "SUCCESS")
                elif count == -1:
                    bridge.log("  ⚠ No se pudo contar páginas — omitiendo", "WARNING")
                    stats["skipped"] += 1
                    continue
                else:
                    bridge.log("  ✗ PDF corrupto — omitiendo", "ERROR")
                    stats["skipped"] += 1
                    continue

            if cfg.operation == "1":
                out = str(Path(cfg.output_dir) / f"{base_name}_compressed_{timestamp}.pdf")
                bridge.log("  Comprimiendo…", "INFO")
                args = _build_compress_args(cfg.profile_id, profile, out, str(pdf_path),
                                            cfg.custom_resolution, cfg.custom_jpeg_quality)
                rc, gs_out = _run_gs(cfg.gs_path, args, bridge)
                if rc == 0 and Path(out).exists():
                    proc_files.append(out)
                    bridge.log("  ✓ Comprimido", "SUCCESS")
                else:
                    raise RuntimeError(gs_out or f"Ghostscript code {rc}")

            elif cfg.operation == "2":
                if total_pages <= 1:
                    bridge.log("  ⚠ Solo 1 página — omitiendo", "WARNING")
                    stats["skipped"] += 1
                    continue
                bridge.log(f"  Dividiendo en bloques de {cfg.pages_per_file} páginas…", "INFO")
                proc_files = _split_pdf(cfg.gs_path, str(pdf_path), cfg.output_dir,
                                        cfg.pages_per_file, total_pages, base_name, bridge)
                if not proc_files:
                    raise RuntimeError("No se generaron archivos")
                bridge.log(f"  ✓ {len(proc_files)} partes creadas", "SUCCESS")

            elif cfg.operation == "3":
                if total_pages > 1:
                    temp_out = str(Path(cfg.output_dir) / f"{base_name}_temp_{timestamp}.pdf")
                    bridge.log("  Comprimiendo…", "INFO")
                    args = _build_compress_args(cfg.profile_id, profile, temp_out, str(pdf_path),
                                                cfg.custom_resolution, cfg.custom_jpeg_quality)
                    rc, gs_out = _run_gs(cfg.gs_path, args, bridge)
                    if rc != 0 or not Path(temp_out).exists():
                        raise RuntimeError(gs_out or f"Ghostscript code {rc}")
                    bridge.log("  ✓ Comprimido", "SUCCESS")
                    bridge.log(f"  Dividiendo en bloques de {cfg.pages_per_file} páginas…", "INFO")
                    proc_files = _split_pdf(cfg.gs_path, temp_out, cfg.output_dir,
                                            cfg.pages_per_file, total_pages, base_name, bridge)
                    try:
                        Path(temp_out).unlink(missing_ok=True)
                    except Exception:
                        pass
                    if not proc_files:
                        raise RuntimeError("No se generaron archivos")
                    bridge.log(f"  ✓ {len(proc_files)} partes creadas", "SUCCESS")
                else:
                    bridge.log("  ⚠ Solo comprimiendo (1 página)", "WARNING")
                    out = str(Path(cfg.output_dir) / f"{base_name}_compressed_{timestamp}.pdf")
                    args = _build_compress_args(cfg.profile_id, profile, out, str(pdf_path),
                                                cfg.custom_resolution, cfg.custom_jpeg_quality)
                    rc, gs_out = _run_gs(cfg.gs_path, args, bridge)
                    if rc == 0 and Path(out).exists():
                        proc_files.append(out)
                    else:
                        raise RuntimeError(gs_out or f"Ghostscript code {rc}")

            if proc_files:
                proc_mb = sum(Path(f).stat().st_size for f in proc_files if Path(f).exists()) / (1024 * 1024)
                stats["total_proc"] += proc_mb
                stats["generated"] += len(proc_files)
                stats["ok"] += 1
                reduction = (1 - proc_mb / orig_mb) * 100 if orig_mb > 0 else 0
                bridge.log(f"  {proc_mb:.2f} MB · Reducción: {reduction:.1f}%", "SUCCESS")

        except OperationCancelled:
            raise
        except Exception as exc:
            bridge.log(f"  ✗ Error: {exc}", "ERROR")
            stats["fail"] += 1
            stats["failed_files"].append(pdf_path.name)

        bridge.stats({
            "ok": stats["ok"], "fail": stats["fail"],
            "skipped": stats["skipped"], "generated": stats["generated"],
            "total": total, "current": idx,
            "total_orig": round(stats["total_orig"], 2),
            "total_proc": round(stats["total_proc"], 2),
            "saved_mb": round(stats["total_orig"] - stats["total_proc"], 2),
            "reduction_pct": round((1 - stats["total_proc"] / stats["total_orig"]) * 100, 1)
                if stats["total_orig"] > 0 else 0,
        })

    elapsed = str(datetime.now() - start_time).split(".")[0]
    bridge.log(f"Completado en {elapsed} · {stats['ok']} ok · {stats['fail']} errores · {stats['skipped']} omitidos", "SUCCESS")

    if stats["failed_files"]:
        bridge.log("Archivos con errores:", "ERROR")
        for f in stats["failed_files"]:
            bridge.log(f"  • {f}", "ERROR")

    if cfg.open_output and Path(cfg.output_dir).exists():
        try:
            if sys.platform == "win32":
                os.startfile(cfg.output_dir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", cfg.output_dir])
            else:
                subprocess.Popen(["xdg-open", cfg.output_dir])
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# ESTADO GLOBAL
# ─────────────────────────────────────────────────────────────────────────────

_worker_bridge: Optional[WorkerBridge] = None
_worker_thread: Optional[threading.Thread] = None
CONFIG_PATH = Path(__file__).parent / CONFIG_FILE


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="PDF Tool API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/config")
def get_config():
    return _load_config()


@app.post("/api/config")
def save_config(req: ConfigSaveRequest):
    _save_config(req.config)
    return {"ok": True}


@app.get("/api/profiles")
def get_profiles():
    return PROFILES


@app.post("/api/start")
def start_processing(req: ProcessRequest):
    global _worker_bridge, _worker_thread

    if _worker_thread and _worker_thread.is_alive():
        return {"ok": False, "error": "Ya hay un proceso en curso"}

    cfg = PDFToolConfig(
        input_dir=req.input_dir,
        output_dir=req.output_dir,
        gs_path=req.gs_path or DEFAULT_GS,
        operation=req.operation,
        profile_id=req.profile_id,
        pages_per_file=max(1, req.pages_per_file),
        custom_resolution=max(72, min(600, req.custom_resolution)),
        custom_jpeg_quality=max(0.1, min(1.0, req.custom_jpeg_quality)),
        open_output=req.open_output,
    )

    _worker_bridge = WorkerBridge()
    bridge = _worker_bridge

    def worker():
        try:
            run_pdf_processing(cfg, bridge)
            bridge.done(True, "Procesamiento finalizado")
        except OperationCancelled:
            bridge.log("Operación cancelada por el usuario", "WARNING")
            bridge.done(False, "Cancelado")
        except Exception as exc:
            bridge.log(f"Error: {exc}", "ERROR")
            bridge.log(traceback.format_exc(), "DIM")
            bridge.done(False, str(exc))

    _worker_thread = threading.Thread(target=worker, daemon=True)
    _worker_thread.start()
    return {"ok": True}


@app.post("/api/stop")
def stop_processing():
    global _worker_bridge
    if _worker_bridge:
        _worker_bridge.cancel_token.cancel()
        return {"ok": True}
    return {"ok": False, "error": "No hay proceso activo"}


@app.get("/api/status")
def get_status():
    return {"running": bool(_worker_thread and _worker_thread.is_alive())}


@app.post("/api/shutdown")
def shutdown():
    os.kill(os.getpid(), signal.SIGTERM)
    return {"ok": True}


@app.get("/api/select-folder")
def select_folder():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory()
    root.destroy()
    return {"folder": folder}


@app.get("/api/events")
async def event_stream(request: Request):
    async def generator():
        while True:
            if await request.is_disconnected():
                break
            bridge = _worker_bridge
            if bridge:
                for event_type, payload in bridge.drain():
                    data = json.dumps({"type": event_type, "payload": payload})
                    yield f"data: {data}\n\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  PDF Tool — Backend local")
    print("  http://localhost:8001")
    print("  Abre frontend/index.html en tu navegador")
    print("=" * 55)
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
