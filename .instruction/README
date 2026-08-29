This Master Operational Registry establishes the foundational protocols for the Zero-G Admin Helper (ZAH) project.

🏗️ Technical Stack & Framework Constraints
        Framework: PyQt6 (Strict usage of scoped enum namespaces like Qt.AlignmentFlag and Qt.Orientation).
        Root Workspace Path: /mnt/Zero-G_Files/Zero-G_Admin_Helper
        Line Terminations: All outbound server commands must use \r\n line terminations paired with a 500ms input buffer delay to match GTX Gaming hardware calibrations.

🌌 Aesthetic Identity & UI Guidelines
        The interface moves completely away from traditional flat, corporate grey layouts to model an immersive starship cockpit HUD utilizing custom widget textures:

        Deep Space Backgrounds: Shadowy Marine Blue (#001A33 / RGB: 0, 26, 51).
        Neon Accent Tones: Bright Cerulean Blue (#1DACD6 / RGB: 29, 172, 214) and Vivid Cerulean (#007BA7 / RGB: 0, 123, 167).
        UI Integrity: Strict reliance on QSS (Qt Style Sheets) border-image properties. This is mandated to prevent high-detail vector asset corner-brackets and custom neon glow textures from warping or stretching across variable monitor resolutions.
        Fixed Dimensions: The application orchestrator expects an initial canvas resolution layout of 1000x750 pixels, while specific configuration components like the AccountOnboardingWizard enforce a fixed structural window size of 512x512 pixels.

🛠️ Technical Stack & Core Framework
        -Primary Language: Python.
            -GUI Framework: PyQt6.
            -Namespace Rigor: Strict usage of scoped enum namespaces within the GUI library (such as explicitly utilizing Qt.AlignmentFlag and Qt.Orientation).
            -Target Host & Integration environment: Dedicated Empyrion: Galactic Survival game server hosted via GTXGaming. IP: 66.23.236.138 Port: 30500
                -Port 30500 (ZeroGBridge Stream & Command Injection):** Used for the initial connection handshake, socket authentication, and validating credentials when ZAH boots up, once the handshake clears, all operational traffic—including continuous JSON telemetry streaming, live player data caches, and command injections (such as plys) are run over the ZGB dedicated mod bridge.
        -ZeroGBridge (ZGB) Language: C#.
            -ZeroGBridge (ZGB) is a custom, high-performance C# server-side mod deployed directly into the Empyrion Dedicated Server (Content/Mods/ZeroGBridge/). It serves as the dedicated backend communication and telemetry pipeline for the Zero-G Admin Helper (ZAH) desktop suite.
            Core Capabilities & Technical Specifications
                -Runtime Framework: C# (.NET Framework 4.8) integrating STRICTLY with Eleon Game Studios' IMod / ModApi lifecycle interfaces.
                -Dedicated Network Gateway: Binds to Port 30500 via an asynchronous TcpListener.
                -Challenge-Response Security: Enforces password-gated client authentication (auth:<password>\r\n) before exposing telemetry broadcasts or command execution.
                -Live Telemetry Stream: Samples and broadcasts 2-second line-delimited JSON METRIC packets over TCP, providing real-time metrics for:
                    -Server Tick/FPS, Dynamic Heap Memory, Process CPU%, Physical RAM usage (WorkingSet64), and Server Uptime.
                    -Real-time connected player caches (PlayerRecord: Steam ID, Entity ID, Ping).
                -Command Dispatch Engine: Routes administrative and querying directives received from ZAH directly to the dedicated engine, returning structured JSON responses:
                    -plys $\rightarrow$ Live player cache snapshot (PLAYER_CACHE).
                    -gents $\rightarrow$ Global structure and entity querying (ENTITY_LIST) via CmdId.-Request_GlobalStructure_List.
                    -save / backup $\rightarrow$ Immediate world state disk flush.
                    -restart $\rightarrow$ Graceful server restart notification and shutdown.-cmd:<command> $\rightarrow$ Dedicated engine console command execution proxy.

🏗️ Architectural & File System Constraints
        Feature-First Pattern: All application functional logic, controllers, and sub-views are isolated cleanly within the /features/ subdirectory. Cross-dependency between distinct features is strictly prohibited.
        Fixed Entry Points & Discovery: Root paths are locked. Discovery relies explicitly on the fixed entry points ZAH.py (Master Lifecycle Orchestrator) and startup.py (Discovery Initialization Script).
        State Separation Protocol: Dynamic runtime data, persistent cache databases, configurations, and application telemetry (/data, /logs, pycache) are strictly excluded from Git tracking via .gitignore.

📡 Networking & Server Calibration Constraints
        Asynchronous Thread Execution: Multi-threaded architecture is mandatory. Dedicated asynchronous background threads handle heavy workloads—such as parsing raw stdout server console logs and broadcasting secure live in-game chat—to eliminate UI-thread latency and freeze-ups.
        GTXGaming Hardware Calibration: All outbound network command strings pushed to the server must handle explicit formatting calibrations:
        Must utilize Windows-style \r\n line terminations.
        Must include a mandatory 500ms input buffer delay between commands.
        UI Integrity: Strict reliance on QSS (Qt Style Sheets) border-image properties. This is mandated to prevent high-detail vector asset corner-brackets and custom neon glow textures from warping or stretching across variable monitor resolutions.
        Fixed Dimensions: The application orchestrator expects an initial canvas resolution layout of 1000x750 pixels, while specific configuration components like the AccountOnboardingWizard enforce a fixed structural window size of 512x512 pixels.

ZeroGBridge Constraints


📦 System Architecture & Directory Patterns
        This repository enforces strict Feature-First Pattern boundaries and State Separation Protocols. All code tracking is restricted by these root namespaces:
    /mnt/Zero-G_Files/Zero-G_Forge/Zero-G_Admin_Helper/ : Root Directory

        ZAH.py: The main entry point for the application. It initiates the UI thread and orchestrates the startup sequence.
        .instructions/ : AI Instructions and Constraints

            AI_INSTRUCTIONS.md
            README

        .gitignore
        check_milestone_30.py
        check_milestone_60.py
        git_token.txt
        launch_zah.sh
        LICENSE
        Zero-G Admin Helper.code-workspace: VS Code workspace save file.

        assets/ (Contains UI and visual elements required for the application.)

            branding/: Contains logos, icons, and visual identity assets.
            backgrounds/   
            buttons/: Graphical components for the UI.

        additional_assets/: Misc media or supporting UI elements.

            ZAH.css: Stylesheet defining the visual theme, layout, and component aesthetics.

        data/ (Persistent storage and configuration files.)

            users.json / player_profiles.json: Core databases for user accounts and player statistics.
            server_config.json / mirror_config.json: Settings for server connections and mirroring behavior.
            telemetry_cache.json / player_registry_cache.json: Temporary storage for collected data.
            mirror_config.json: ftp login credentials
            player_registry.py: Python module to interact with and manage the player database.
            playfield_registry.py: Python module to interact with and manage playfields database.
            secret.key: Encryption key used to secure sensitive data.
            server_mirror.log: Specific logs regarding server mirroring processes.
            features/ (Modular business logic organized by domain.)

        auth/: Manages user identity/credentials.    

            inspect_users.py: Admin tools for auditing or viewing user account data.
            login.py / onboarding.py: Logic for existing logins and new user creation.
            persistence.py: Handles "Remember Me" functionality and session state.

        dashboard/: Logic for the main user interface.

            main_cockpit.py: The primary UI interface.
            resource_worker.py
            telemetry_parser.py
            telemetry_worker.py

        loading/: 
            loading_screen.py: Used for displaying the boot sequence UI.

        network/: Handles all external connectivity, including ping tests and connection wizards.

            connection.py

        security/: Centralized security logic, including encryption/decryption utilities.

            security_module.py: Used to create encryption for login credentials.

        tests/: Unit and integration tests (sFTP.py for file transfer validation, test_telemetry.py for data handling).
            
            migrate_users.py
            sFTP.py
            test_telemetry.py

        clear_pycache.py: Maintenance utility that clears all __pycache__ bytecode files from 
            folders nested in main root file.
        
        ZeroGBridge (Mod Program files)

            bin/: Contains compiled .dll file and .pdb files

            Core/:

                ModMain.cs (Mod lifecycle entry point (Init and Shutdown).)

            Handlers/:

                CommandDispatcher.cs (Ingests and routes incoming console commands (e.g., plys).)

            lib/: Contains all possible needed EGS library .dll files for modding

            logging/: Contains all active logging files

                LogParser.cs (Regex evaluation of raw log lines for player join/leave events.)

                LogDiscovery.cs (Scans directories to lock onto the active master)

            Network/:

                TelemetryServer.cs (Handles TCP client sockets and password authentication gating on Port 30500.)

                TelemetryBroadcaster.cs (Contains TelemetryLoop() where all metrics are calculated and structured into the METRIC JSON packet.)

            obj/: Contains compilation files

            Properties/:

                AssemblyInfo.cs


🔄 Automated Lifecycle & Sequential Flows
1. Boot Diagnostics & Key Milestone Logic Recap
At 30% Progress: The loader's timing loop pauses and checks if there are accounts with "keep me logged in", if there are login screen is bypassed if no then the Login Screen Overlay is activated, Progress bar is kept frozen until successful user login or account creation has been verified.

At 60% Progress: The progression bar halts a second time to check if a server configuration profile available, conditionally intercepting the initialization of the Network Connection Wizard. If there are available network configurations then network wizard is bypassed. If there are no configuration profiles available then the network wizard opens for network login data. Progress bar is kept frozen until successful configuration profile is found/created.

Ping is run to verify network configuration. If unable to verify then network wizard is re-initialized with ping error and request to re-enter network login info.

At 100% Progress: Upon successfully navigating both state gates, the orchestrator closes the loading phase and hands control off over to the main_window cockpit dashboard interface.

[ Boot: ZAH.py ] ──> UI Thread Draws 1000x750 Canvas │ ▼ [ Increment to 30% ] │ Gated Check: "Keep Me Logged In"? ├── Yes ──► Bypass Login └── No ──► [ HALT Progress ] ──► Open Login Screen │ Verified Account Login/Creation │ ┌───────────────────────────┘ ▼ [ Progress Resumes ] │ ▼ [ Increment to 60% ] │ Gated Check: Server Config Profiles? ├── Yes ──► Bypass Network Wizard ────────────────────────────────────────► [Network Ping] ◃───┒ └── No ──► [ HALT Progress ] ──► Open Network Connection Wizard | | │ | | Config Created | | │ | | | | | ▼ | | ┌───────────────────[Validated Ping]<──────────────────────────────────┘ | | | | ▼ ▼ | (Yes) (NO) | ▼ └────► Re-launch Network Connection Wizard ──────────────┘ [ Progress Resumes ] │ ▼ [ Milestone 100% ] ──► Hand off to Main Workspace

📡 Remote Server Connection Variables
Target Host: Dedicated Empyrion Server hosted via GTX Gaming

Active Destination IP: 66.23.236.138

ZeroGBridge Routing Port: 30500

    Authentication Token: ZeroGAdmin2026

sFTP Connection: Needed for .log file to be read and parsed.
