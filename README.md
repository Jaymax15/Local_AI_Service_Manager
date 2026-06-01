# AI Server Manager

**AI Server Manager** is a simple desktop control panel for running a local AI stack on a Windows + WSL system.

It is designed to make local AI tools easier to start, stop, monitor, and manage without needing to type lots of terminal commands every time.

Created by **Jason Michael Allison**.

## First-time setup

AI Server Manager requires:

* Windows with WSL enabled
* Ubuntu for WSL
* Python
* Docker Desktop

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

**3. Install Docker Desktop**

```powershell
winget install --id Docker.DockerDesktop -e --accept-package-agreements --accept-source-agreements
```

After setup, restart Windows, open Docker Desktop once, and complete any first-run setup it asks for.

### Fast setup option

This option downloads and runs the project setup script from GitHub.

Some antivirus tools may warn about PowerShell setup scripts because they install developer tools and enable system features such as WSL, Python, and Docker Desktop. If your antivirus blocks this method, use the recommended setup above instead.

Run in **PowerShell as Administrator**:

```powershell
iwr -useb https://raw.githubusercontent.com/Jaymax15/Local_AI_Service_Manager/main/setup/install_prereqs.ps1 -OutFile "$env:TEMP\ai-sm-setup.ps1"; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\ai-sm-setup.ps1"
```

## What it does

AI Server Manager helps control services such as:

* **Ollama** for local LLM models
* **XTTS2**, **Kokoro**, and **Piper** for text-to-speech
* **SillyTavern** and **Open WebUI** for web/chat interfaces
* GPU and CPU monitoring
* Service start/stop controls
* Basic settings, service priority, and GPU assignment options

The goal is to give users one central place to manage a local AI server setup.

## Why this is useful

Running local AI can be confusing, especially when several tools need to start in the right order. This manager helps by:

* Starting selected services from one button
* Stopping services cleanly
* Showing whether services are running
* Showing GPU and CPU usage
* Helping manage installed AI services
* Making local AI setups more beginner-friendly

## Basic usage

1. Open `ai_server_manager.py`.
2. Use **Settings** to configure options such as theme, GPU assignment, and sudo access.
3. Use **Services** to enable or disable installed services.
4. Press **START ALL** to launch your selected services.
5. Press **STOP ALL** to stop them and release resources.

The manager is intended to be portable inside the project folder, so it can be moved between drives or computers more easily.

## Project status

This project is still under active development. Some services, paths, and shutdown behavior may still need testing on different machines.

Community feedback, bug reports, ideas, and improvements are welcome.

## AI-assisted development note

This project was built by one person, and AI tools were used to help with coding, debugging, planning, and documentation.

Please do not take that as a bad thing. This is a one-man project, and I used the tools available to help make something useful for the community. The goal is not to hide that AI helped, but to be honest about it and hopefully invite others to improve the project with me.

## Contributing

If you test this project, please feel free to leave feedback, report issues, suggest improvements, or contribute code.

This started as a personal project, but I am sharing it in the hope that the community can help make it better.
