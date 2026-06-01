# AI Server Manager

**AI Server Manager** is a simple desktop control panel for running a local AI stack on a Windows + WSL system.

It is designed to make local AI tools easier to start, stop, monitor, and manage without needing to type lots of terminal commands every time.

Created by **Jason Michael Allison**.

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

1. Install the required AI services and dependencies.
2. Open `ai_server_manager.py`.
3. Use **Settings** to configure options such as theme, GPU assignment, and sudo access.
4. Use **Services** to enable or disable installed services.
5. Press **START ALL** to launch your selected services.
6. Press **STOP ALL** to stop them and release resources.

The manager is intended to be portable inside the `AI_SERVER` folder, so the project can be moved between drives or computers more easily.

## Project status

This project is still under active development. Some services, paths, and shutdown behavior may still need testing on different machines.

Community feedback, bug reports, ideas, and improvements are welcome.

## AI-assisted development note

This project was built by one person, and AI tools were used to help with coding, debugging, planning, and documentation.

Please do not take that as a bad thing. This is a one-man project, and I used the tools available to help make something useful for the community. The goal is not to hide that AI helped, but to be honest about it and hopefully invite others to improve the project with me.

A big thank you to ChatGPT for helping during development.

## Contributing

If you test this project, please feel free to leave feedback, report issues, suggest improvements, or contribute code.

This started as a personal project, but I am sharing it in the hope that the community can help make it better.
