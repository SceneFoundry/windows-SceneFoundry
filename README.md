## Installation for Windows

### Unicode UTF-8 for worldwide language support
In this framework, some variables are named using unicode characters in source code. In order to compile such source code you must set this feature on the windows machine where you are going to setup this ca2 Software Development Environment.
Download and run [https://windows.ca2.store/utf8.reg](https://windows.ca2.store/utf8.reg) and restart machine.

### tool-windows
At Git Bash
```bash
cd
mkdir code
cd code
mkdir operating_system
cd operating_system
git clone https://github.com/ca2/tool-windows $HOME/code/operating_system/tool --recurse-submodules
```

### Add C:\Users\<username>\code\operating_system\bin and C:\Users\<username>\code\operating_system\tool\bin to the `PATH` environment variable
1. Press the windows key so you can search
2. Type environment variables and click on `Edit the system environment variables` to open `System Properties` dialog.
3. Click `Environment Variables...` button at bottom of screen to open `Environment Variables` dialog.
4. At the list at the top, select *Path* list item, then click `Edit...` to open `Edit environment variable` dialog.
5. On the right, click `New`
6. Enter the path `%USERPROFILE%\code\operating_system\bin` then press Enter.
7. Click `New` again.
8. Enter the path `%USERPROFILE%\code\operating_system\tool\bin` then press Enter.
9. Click Ok at `Edit environment variable` dialog.
10. Click Ok at `Environment Variables` dialog.
11. Click Ok at `System Properties` dialog.
12. Done!

### storage-windows
Unzip [https://windows.ca2.store/storage-windows-forGraphics3DLabs.zip](https://windows.ca2.store/storage-windows-forGraphics3DLabs.zip) to `C:\Users\<username>\SceneFoundry\operating_system\storage-windows`.

### Clone simple project
Suggested name of folder is SceneFoundry\main.
```bash
git clone https://github.com/SceneFoundry/windows-SceneFoundry $HOME/SceneFoundry/main --recurse-submodules
```

### Symbolic links will be broken, so...

### Enable Developer Mode for Windows at Developer Settings

### Install Tortoise Git

### delete folder C:\Users\<username>\SceneFoundry\main\port\include

### Revert C:\simple\port\include deletion using Tortoise Git by right clicking include folder inside the folder C:\Users\<username>\SceneFoundry\main\port and clicking Revert option in Context Menu Tortoise Git Sub Menu

### At Tortoise Git Revert Screen, select everything and then click Revert.

Open `C:\Users\<username>\SceneFoundry\main\solution-windows\SceneFoundry.sln` project you can now build and run SceneFoundry solution.


