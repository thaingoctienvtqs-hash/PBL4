@echo off
setlocal
title PBL4 - Painting Protection

set "PBL4_ROOT=C:\Users\LEGION\Pbl4"
set "PBL4_FRAME=%PBL4_ROOT%\data\camera_frame.jpg"
set "PBL4_WSL_FRAME=/mnt/c/Users/LEGION/Pbl4/data/camera_frame.jpg"

if not exist "%PBL4_ROOT%\src\realtime_worker.py" (
  echo PBL4 repository was not found at %PBL4_ROOT%.
  pause
  exit /b 1
)

if "%PBL4_CAMERA_URL%"=="" (
  echo Set PBL4_CAMERA_URL to the ESP32-CAM /capture URL before starting.
  echo Example for this Command Prompt: set PBL4_CAMERA_URL=http://192.168.1.50/capture
  echo Then run start_pbl4.bat again. The camera address is not stored in Git.
  pause
  exit /b 1
)

echo ==========================================
echo       PBL4 PAINTING PROTECTION
echo ==========================================
echo Dashboard: http://localhost:8000/
echo Camera file: %PBL4_FRAME%
echo ROI starts disabled. Configure it in the dashboard after the first frame.
echo.

start "PBL4 - API and Dashboard" wsl -d Ubuntu-22.04 -- bash -lc "cd /mnt/c/Users/LEGION/Pbl4 && source /home/legion/miniconda3/etc/profile.d/conda.sh && conda activate contacthands && export CUDA_HOME=/usr/local/cuda-11.7 && export LD_LIBRARY_PATH=/usr/lib/wsl/lib:/usr/local/cuda-11.7/lib64 && export TORCH_CUDA_ARCH_LIST='8.6' && python -m uvicorn src.app.api:app --host 127.0.0.1 --port 8000"
timeout /t 2 /nobreak >nul
start "PBL4 - ContactHands" wsl -d Ubuntu-22.04 -- bash -lc "cd /mnt/c/Users/LEGION/Pbl4 && source /home/legion/miniconda3/etc/profile.d/conda.sh && conda activate contacthands && export CUDA_HOME=/usr/local/cuda-11.7 && export LD_LIBRARY_PATH=/usr/lib/wsl/lib:/usr/local/cuda-11.7/lib64 && export TORCH_CUDA_ARCH_LIST='8.6' && python -m src.realtime_worker --mode file-watch --frame-file '%PBL4_WSL_FRAME%'"
start "PBL4 - ESP32-CAM Capture" cmd /k "cd /d %PBL4_ROOT% && py -3 esp32cam_capture.py --output %PBL4_FRAME%"
timeout /t 3 /nobreak >nul
start "" "http://localhost:8000/"
echo Started three processes. Close each terminal or press Ctrl+C in WSL workers to stop.
