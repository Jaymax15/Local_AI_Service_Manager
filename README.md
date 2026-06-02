# AI Server Manager

**AI Server Manager** is a simple desktop control panel for running a local AI stack on a Windows + WSL system.

It is designed to make local AI tools easier to start, stop, monitor, and manage without needing to type lots of terminal commands every time.

Created by **Jason Michael Allison**.

## Preview

### Main manager

![AI Server Manager main window](components/images/main-manager.png)

### Services window

![Services window](components/images/services-window.png)

### Service manager

![Service manager window](components/images/service-manager.png)

### Model manager

![Model manager window](components/images/model-manager.png)

## First-time setup

AI Server Manager requires:

* Windows with WSL enabled
* Ubuntu for WSL
* Python
* Docker Headless

Open **PowerShell as Administrator** before running setup commands.

### Recommended setup

Run these commands one at a time in **PowerShell as Administrator**.

**1. Enable WSL and install Ubuntu**

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart; dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart; wsl.exe --update; wsl.exe --set-default-version 2; wsl.exe --install -d Ubuntu --no-launch
```

**2. Install Python**

```powershell
winget install --id Python.Python.3.14 -e --scope machine --accept-package-agreements --accept-source-agreements
```

**3. Install Docker Headless**

```powershell
$setup="$env:TEMP\ai-sm-headless-$PID.ps1"; iwr -useb "https://raw.githubusercontent.com/Jaymax15/Local_AI_Service_Manager/main/setup/install_headless_prereqs.ps1?cachebust=$PID" -OutFile $setup; powershell -NoProfile -ExecutionPolicy Bypass -File $setup
```

After setup, restart Windows, open Docker Desktop once, and complete any first-run setup it asks for.

### Fast setup option

This option downloads and runs the project setup script from GitHub.

Some antivirus tools may warn about PowerShell setup scripts because they install developer tools and enable system features such as WSL, Python, and Docker Desktop. If your antivirus blocks this method, use the recommended setup above instead.

Run in **PowerShell as Administrator**:

```powershell
iwr -useb https://raw.githubusercontent.com/Jaymax15/Local_AI_Service_Manager/main/setup/install_headless_prereqs.ps1 -OutFile "$env:TEMP\ai-sm-headless.ps1"; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\ai-sm-headless.ps1"
```

## What it does

AI Server Manager helps control and monitor a local AI stack from one Windows desktop app. Current capabilities include:

* **Ollama** management for local LLM models
* **XTTS2**, **Kokoro**, and **Piper** management for text-to-speech services
* **SillyTavern** and **Open WebUI** management for web/chat interfaces
* Install and uninstall tools for supported services
* One-click **START ALL** and **STOP ALL** controls
* Service priority ordering so core backends can start before UI services
* Live AI service status checks with local URLs and up/down state
* GPU and CPU monitoring inside the manager
* A **Service Manager** window for installing, uninstalling, and checking supported services
* A **Model Manager** window for installing and removing Ollama models
* A curated Ollama model list that can be updated from GitHub through the Settings update terminal
* Sudo setup support for the required WSL-side service and install commands
* Dark and light theme support
* Portable folder-based layout so the project can be moved more easily between drives or systems

The goal is to give users one central place to install, start, stop, monitor, and maintain a local AI server setup.

## Processor selection status

Processor selection is currently still in development. The controls are visible in the Services window, but the deeper assignment logic is not finished yet.

When complete, processor selection is intended to let users choose how supported services should run, such as **Auto**, **CPU**, or a specific available GPU. This should eventually make it easier to separate workloads, for example running LLM services on one GPU, TTS services on another GPU, or falling back to CPU-only mode on machines without a dedicated GPU.

This feature is planned to support more flexible local AI setups over time, including systems with NVIDIA, AMD, Intel, single-GPU, multi-GPU, and CPU-only configurations where possible.

## Why this is useful

Running local AI can be confusing, especially when several tools need to be installed, started, stopped, and checked in the right order. This manager helps by:

* Starting selected services from one button
* Stopping services cleanly
* Showing whether services are installed and running
* Showing GPU and CPU usage
* Helping install and remove supported AI services
* Helping install and remove Ollama models
* Reducing the need to repeatedly type terminal commands
* Making local AI setups more beginner-friendly

## Basic usage

1. Open `ai_server_manager.py`.
2. Use **Settings** to configure options such as theme, sudo access, and model-list updates.
3. Use **Services** to enable or disable installed services, adjust priority, and open service/model management tools.
4. Use **Manage Services** to install or uninstall supported services.
5. Use **Manage Models** to install or remove Ollama models.
6. Press **START ALL** to launch your selected services.
7. Press **STOP ALL** to stop them and release resources.

The manager is intended to be portable inside the project folder, so it can be moved between drives or computers more easily.

## Project status

This project is still under active development. Core service management, monitoring, and model management are working, but some features are still being improved and tested across different machines.

Processor selection is one of the larger features still in development. More services, models, hardware options, and installer improvements are planned over time.

Community feedback, bug reports, ideas, and improvements are welcome.

## AI-assisted development note

This project was built by one person, and AI tools were used to help with coding, debugging, planning, and documentation.

Please do not take that as a bad thing. This is a one-man project, and I used the tools available to help make something useful for the community. The goal is not to hide that AI helped, but to be honest about it and hopefully invite others to improve the project with me.

## Contributing

If you test this project, please feel free to leave feedback, report issues, suggest improvements, or contribute code.

This started as a personal project, but I am sharing it in the hope that the community can help make it better.
