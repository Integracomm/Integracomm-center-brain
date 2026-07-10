@echo off
rem Sobe atualizacoes de codigo para o servidor AWS (deploy\deploy.ps1).
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 %*
