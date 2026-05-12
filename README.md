# PDF Tool: Compresor y Divisor

**PDF Tool** es una utilidad de escritorio local con una interfaz web moderna diseñada para el procesamiento por lotes de archivos PDF. Permite reducir documentos masivos para enviar por correo o dividir reportes extensos en partes manejables, ofreciendo una interfaz intuitiva impulsada por el motor estándar de la industria: **Ghostscript**.

![Versión](https://img.shields.io/badge/version-2.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![UI](https://img.shields.io/badge/UI-Vue.js%203%20/%20FastAPI-orange.svg)

---

## 🎨 Icono del Proyecto

<p align="center">
  <img src="frontend/icon.png" width="160" alt="PDF Tool Icon">
</p>

---

## ✨ Características Principales

*   **⚡ Inicio Rápido:** Incluye un script `start.bat` que arranca el servidor backend y abre la interfaz en tu navegador predeterminado con un solo clic.
*   **📂 Selector de Carpetas Nativo:** Integración con los diálogos del sistema operativo para seleccionar carpetas de entrada y salida de forma cómoda.
*   **📉 Compresión Inteligente:** 6 perfiles de calidad optimizados para equilibrar el tamaño del archivo y la fidelidad visual.
*   **✂️ División Dinámica:** Divide automáticamente tus PDFs por un número específico de páginas.
*   **🔄 Flujo de Trabajo Dual:** Comprime Y divide en un solo paso coordinado.
*   **📊 Analítica en Tiempo Real:** Seguimiento del progreso, espacio en disco ahorrado y porcentajes de compresión mediante Server-Sent Events (SSE).
*   **🌙 Interfaz Oscura Premium:** Estética moderna y cómoda para trabajar.
*   **🛑 Apagado Integrado:** Botón para cerrar la aplicación que apaga el servidor backend y cierra la pestaña del navegador.
*   **🔗 Soporte para Archivos con Espacios:** Se ha corregido la limitación y ahora se pueden procesar archivos con espacios en sus nombres.

---

## 🛠️ Requisitos del Sistema

### 1. Python 3.8+
Asegúrate de tener Python instalado.
[Descargar Python](https://www.python.org/downloads/)

### 2. Ghostscript
Esta herramienta requiere **Ghostscript** para realizar las operaciones de PDF.
*   **Windows:** 
    *   Instala la versión de 64 bits. Por defecto, el script busca en: `C:\Program Files\gs\gs10.06.0\bin\gswin64c.exe`.
    *   Si lo instalas en otra ruta, puedes configurarla directamente en la interfaz.

---

## 🚀 Guía de Inicio

### El modo fácil (Recomendado)
Simplemente haz doble clic en el archivo `iniciar.bat` en la raíz del proyecto. Esto:
1. Abrirá `frontend/index.html` en tu navegador.
2. Iniciará el backend de FastAPI en segundo plano.

### El modo manual
Si prefieres iniciarlo manualmente:
1. Abre una terminal en la carpeta `backend` e instala las dependencias si no las tienes:
   ```bash
   pip install fastapi uvicorn
   ```
2. Ejecuta el servidor:
   ```bash
   python main.py
   ```
3. Abre el archivo `frontend/index.html` en tu navegador.

---

## 📂 Estructura del Proyecto

```text
├── backend/
│   ├── main.py                # Servidor FastAPI (Puerto: 8003)
│   └── pdf_tool_config.json   # Configuración guardada
├── frontend/
│   ├── index.html             # Interfaz web en Vue 3
│   └── icon.png               # Icono para la interfaz
├── start.bat                  # Script de inicio automatizado
├── icon.png                   # Logo del proyecto
└── README.md                  # Esta documentación
```

---

## 🎯 Perfiles de Compresión

| Perfil | Nivel de Calidad | Reducción Est. | Ideal para... |
| :--- | :--- | :--- | :--- |
| **1** | 💥 Extrema | 80–95% | Visualización web rápida, calidad mínima |
| **2** | 🔥 Máxima | 70–85% | Adjuntos de correo y visualización móvil |
| **3** | 📱 Alto | 50–70% | eBooks, tablets y lectura general |
| **4** | 🖨️ Medio | 30–50% | Impresión de oficina estándar |
| **5** | 💎 Mínimo | 10–30% | Pre-prensa y archivado de alta resolución |
| **6** | ⚙️ Personalizado | Variable | Control manual de DPI y calidad JPEG |

---

## ⚠️ Notas
*   **🔒 Privacidad:** Todo el procesamiento se realiza de forma **local**. Ningún dato se sube a servidores externos.
*   **🔌 Puerto:** El backend corre en el puerto `8003` para no entrar en conflicto con otras herramientas locales.

---
*Desarrollado por **gwalls86***
