@echo off
title PBL4 - Painting Protection

echo ==========================================
echo       PBL4 PAINTING PROTECTION
echo ==========================================
echo.

echo [1/4] Starting API...
start "PBL4 - API" wsl -d Ubuntu-22.04 -- bash -lc "cd /mnt/c/Users/LEGION/Pbl4 && source /home/legion/miniconda3/etc/profile.d/conda.sh && conda activate contacthands && export CUDA_HOME=/usr/local/cuda-11.7 && export LD_LIBRARY_PATH=/usr/lib/wsl/lib:/usr/local/cuda-11.7/lib64 && export TORCH_CUDA_ARCH_LIST='8.6' && uvicorn src.app.api:app --host 0.0.0.0 --port 8000"

timeout /t 3 /nobreak >nul

echo [2/4] Starting ContactHands AI...
start "PBL4 - AI" wsl -d Ubuntu-22.04 -- bash -lc "cd /mnt/c/Users/LEGION/Pbl4 && source /home/legion/miniconda3/etc/profile.d/conda.sh && conda activate contacthands && export CUDA_HOME=/usr/local/cuda-11.7 && export LD_LIBRARY_PATH=/usr/lib/wsl/lib:/usr/local/cuda-11.7/lib64 && export TORCH_CUDA_ARCH_LIST='8.6' && python -m src.app.realtime"

echo [3/4] Starting Camera...
start "PBL4 - Camera" cmd /k "py -3.11 C:\Users\LEGION\PaintingProtection\webcam_contacthands.py"

echo [4/4] Starting Dashboard...
start "PBL4 - Dashboard" cmd /k "cd /d C:\Users\LEGION\Pbl4 && python -m http.server 8080"

timeout /t 5 /nobreak >nul

echo Opening Dashboard...
start http://localhost:8080

echo.
echo ==========================================
echo PBL4 STARTED
echo Dashboard: http://localhost:8080
echo API:       http://localhost:8000
echo ==========================================
