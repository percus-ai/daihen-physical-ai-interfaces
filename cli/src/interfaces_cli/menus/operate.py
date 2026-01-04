"""Operate menu - Teleop and Inference."""

from typing import TYPE_CHECKING, Any, List

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from interfaces_cli.banner import show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


class OperateMenu(BaseMenu):
    """Operate menu - Teleop and Inference operations."""

    title = "テレオペ / 推論"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="teleop", name="🎮 [TELEOP] テレオペレーション"),
            Choice(value="inference", name="🤖 [INFERENCE] AI推論実行"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "teleop":
            return self.submenu(TeleopMenu)
        if choice == "inference":
            return self.submenu(InferenceMenu)
        return MenuResult.CONTINUE


class TeleopMenu(BaseMenu):
    """Teleoperation mode selection."""

    title = "テレオペレーション"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="local", name="🎮 [LOCAL] ローカルテレオペ"),
            Choice(value="remote_leader", name="📡 [LEADER] リモートリーダー"),
            Choice(value="remote_follower", name="📥 [FOLLOWER] リモートフォロワー"),
            Choice(value="sessions", name="📋 [SESSIONS] セッション一覧"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "local":
            return self._start_local_teleop()
        if choice == "remote_leader":
            return self._start_remote_leader()
        if choice == "remote_follower":
            return self._start_remote_follower()
        if choice == "sessions":
            return self._show_sessions()
        return MenuResult.CONTINUE

    def _start_local_teleop(self) -> MenuResult:
        """Start local teleoperation."""
        show_section_header("Local Teleoperation")

        try:
            # Select teleop mode
            mode = inquirer.select(
                message="Teleop mode:",
                choices=[
                    Choice(value="simple", name="Simple (leader-follower)"),
                    Choice(value="visual", name="Visual (with camera)"),
                    Choice(value="bimanual", name="Bimanual (two arms)"),
                    Choice(value="__back__", name="« Cancel"),
                ],
                style=hacker_style,
            ).execute()

            if mode == "__back__":
                return MenuResult.CONTINUE

            # Get robot preset
            robot_preset = inquirer.select(
                message="Robot type:",
                choices=[
                    Choice(value="so101", name="SO-101"),
                    Choice(value="so100", name="SO-100"),
                ],
                style=hacker_style,
            ).execute()

            # Get ports
            leader_port = inquirer.text(
                message="Leader arm port:",
                default="/dev/ttyUSB0",
                style=hacker_style,
            ).execute()

            follower_port = inquirer.text(
                message="Follower arm port:",
                default="/dev/ttyUSB1",
                style=hacker_style,
            ).execute()

            fps = inquirer.text(
                message="FPS:",
                default="60",
                style=hacker_style,
            ).execute()

            # Start teleop session
            result = self.api.start_teleop({
                "mode": mode,
                "robot_preset": robot_preset,
                "leader_port": leader_port,
                "follower_port": follower_port,
                "fps": int(fps),
            })

            session = result.get("session", {})
            session_id = session.get("session_id", "unknown")

            print(f"\n{Colors.success('Teleop session created')}")
            print(f"  Session: {session_id}")
            print(f"  Mode: {mode}")
            print(f"  Robot: {robot_preset}")
            print(f"  Leader: {leader_port}")
            print(f"  Follower: {follower_port}")

            # Ask to run
            run = inquirer.confirm(
                message="Start teleop now?",
                default=True,
                style=hacker_style,
            ).execute()

            if run:
                self.api.run_teleop(session_id)
                print(f"\n{Colors.success('Teleop running!')}")
                print(f"{Colors.muted('Press Enter to stop teleoperation...')}")

                try:
                    input()
                except KeyboardInterrupt:
                    pass

                self.api.stop_teleop(session_id)
                print(f"\n{Colors.success('Teleoperation stopped.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _start_remote_leader(self) -> MenuResult:
        """Start as remote leader."""
        show_section_header("Remote Leader")

        try:
            # Get host/port
            host = inquirer.text(
                message="Host (0.0.0.0 for all interfaces):",
                default="0.0.0.0",
                style=hacker_style,
            ).execute()

            port = inquirer.text(
                message="Port:",
                default="8765",
                style=hacker_style,
            ).execute()

            leader_port = inquirer.text(
                message="Leader arm port:",
                default="/dev/ttyUSB0",
                style=hacker_style,
            ).execute()

            # Optional camera
            use_camera = inquirer.confirm(
                message="Enable camera streaming?",
                default=False,
                style=hacker_style,
            ).execute()

            camera_id = None
            if use_camera:
                camera_id = inquirer.text(
                    message="Camera ID:",
                    default="0",
                    style=hacker_style,
                ).execute()

            result = self.api.start_teleop_leader({
                "host": host,
                "port": int(port),
                "leader_port": leader_port,
                "camera_id": int(camera_id) if camera_id else None,
            })

            session = result.get("session", {})
            session_id = session.get("session_id", "unknown")
            url = session.get("url", f"http://{host}:{port}")

            print(f"\n{Colors.success('Leader session created')}")
            print(f"  Session: {session_id}")
            print(f"  URL: {url}")
            print(f"  Leader Port: {leader_port}")
            print(f"\n{Colors.muted('Share this URL with followers.')}")
            print(f"{Colors.muted('Press Enter to stop...')}")

            try:
                input()
            except KeyboardInterrupt:
                pass

            self.api.stop_teleop_leader(session_id)
            print(f"\n{Colors.success('Leader session stopped.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _start_remote_follower(self) -> MenuResult:
        """Start as remote follower."""
        show_section_header("Remote Follower")

        try:
            leader_url = inquirer.text(
                message="Leader URL (e.g., http://192.168.1.100:8765):",
                style=hacker_style,
            ).execute()

            if not leader_url:
                return MenuResult.CONTINUE

            follower_port = inquirer.text(
                message="Follower arm port:",
                default="/dev/ttyUSB0",
                style=hacker_style,
            ).execute()

            result = self.api.start_teleop_follower({
                "leader_url": leader_url,
                "follower_port": follower_port,
            })

            session = result.get("session", {})
            session_id = session.get("session_id", "unknown")

            print(f"\n{Colors.success('Follower session created')}")
            print(f"  Session: {session_id}")
            print(f"  Leader: {leader_url}")
            print(f"  Follower Port: {follower_port}")
            print(f"\n{Colors.muted('Waiting for leader connection...')}")
            print(f"{Colors.muted('Press Enter to stop...')}")

            try:
                input()
            except KeyboardInterrupt:
                pass

            self.api.stop_teleop_follower(session_id)
            print(f"\n{Colors.success('Follower session stopped.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_sessions(self) -> MenuResult:
        """Show teleop sessions."""
        show_section_header("Teleop Sessions")

        try:
            # Local sessions
            local = self.api.list_teleop_sessions()
            local_sessions = local.get("sessions", [])
            print(f"{Colors.CYAN}Local Sessions:{Colors.RESET}")
            if local_sessions:
                for s in local_sessions:
                    session_id = s.get("session_id", "unknown")
                    mode = s.get("mode", "?")
                    running = s.get("is_running", False)
                    status = Colors.success("running") if running else Colors.muted("stopped")
                    print(f"  - {session_id}: {mode} ({status})")
            else:
                print(f"  {Colors.muted('No local sessions')}")

            # Remote sessions
            remote = self.api.list_remote_teleop_sessions()
            leaders = remote.get("leaders", [])
            followers = remote.get("followers", [])

            print(f"\n{Colors.CYAN}Remote Leaders:{Colors.RESET}")
            if leaders:
                for s in leaders:
                    session_id = s.get("session_id", "unknown")
                    url = s.get("url", "?")
                    running = s.get("is_running", False)
                    clients = s.get("clients_connected", 0)
                    status = Colors.success("running") if running else Colors.muted("stopped")
                    print(f"  - {session_id}: {url} ({status}, {clients} clients)")
            else:
                print(f"  {Colors.muted('No leader sessions')}")

            print(f"\n{Colors.CYAN}Remote Followers:{Colors.RESET}")
            if followers:
                for s in followers:
                    session_id = s.get("session_id", "unknown")
                    leader_url = s.get("leader_url", "?")
                    connected = s.get("is_connected", False)
                    running = s.get("is_running", False)
                    latency = s.get("latency_ms", 0)
                    status = Colors.success("connected") if connected else Colors.muted("disconnected")
                    print(f"  - {session_id}: -> {leader_url} ({status}, {latency:.1f}ms)")
            else:
                print(f"  {Colors.muted('No follower sessions')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class InferenceMenu(BaseMenu):
    """Inference - Run models on robot."""

    title = "AI推論"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="run", name="🚀 [RUN] モデル実行"),
            Choice(value="models", name="📦 [MODELS] 利用可能モデル一覧"),
            Choice(value="compat", name="🔍 [COMPAT] デバイス互換性チェック"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "run":
            return self._run_model()
        if choice == "models":
            return self._list_models()
        if choice == "compat":
            return self._check_compatibility()
        return MenuResult.CONTINUE

    def _run_model(self) -> MenuResult:
        """Run a model on robot."""
        show_section_header("Run Model")

        try:
            # Get available models
            result = self.api.list_inference_models()
            models = result.get("models", [])

            if not models:
                print(f"{Colors.warning('No models available.')}")
                print(f"{Colors.muted('Download a model from R2 or train one first.')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Select model
            model_choices = []
            for m in models:
                if isinstance(m, dict):
                    model_id = m.get("model_id", m.get("name", "unknown"))
                    policy = m.get("policy_type", "?")
                    source = m.get("source", "local")
                    size_mb = m.get("size_mb", 0)
                    model_choices.append(Choice(
                        value=model_id,
                        name=f"{model_id} [{policy}] ({source}, {size_mb:.0f}MB)"
                    ))
                else:
                    model_choices.append(Choice(value=m, name=m))
            model_choices.append(Choice(value="__back__", name="« Cancel"))

            selected_model = inquirer.select(
                message="Select model:",
                choices=model_choices,
                style=hacker_style,
            ).execute()

            if selected_model == "__back__":
                return MenuResult.CONTINUE

            # Get available projects from storage (./data/projects/)
            try:
                projects_result = self.api.list_storage_projects()
                projects = projects_result.get("projects", [])
            except Exception:
                projects = []

            if not projects:
                print(f"{Colors.warning('プロジェクトが見つかりません')}")
                print(f"{Colors.muted('R2 Sync > プロジェクトをダウンロード でプロジェクトを取得してください')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Show projects with robot_type info
            project_choices = []
            for p in projects:
                project_id = p.get("id", "unknown")
                display_name = p.get("display_name", project_id)
                robot_type_hint = p.get("robot_type", "?")
                project_choices.append(Choice(
                    value=project_id,
                    name=f"{display_name} [{robot_type_hint}]"
                ))
            project_choices.append(Choice(value="__back__", name="« Cancel"))

            selected_project = inquirer.select(
                message="Select project:",
                choices=project_choices,
                style=hacker_style,
            ).execute()

            if selected_project == "__back__":
                return MenuResult.CONTINUE

            # Get project details to extract robot_type
            project_info = None
            robot_type = "so101"  # default
            try:
                project_info = self.api.get_storage_project(selected_project)
                robot_type = project_info.get("robot_type", "so101")
            except Exception:
                pass

            # Episodes
            episodes = inquirer.text(
                message="Number of episodes:",
                default="1",
                style=hacker_style,
            ).execute()

            # Device
            device = inquirer.select(
                message="Device:",
                choices=[
                    Choice(value=None, name="Auto (recommended)"),
                    Choice(value="cuda", name="CUDA (GPU)"),
                    Choice(value="mps", name="MPS (Apple Silicon)"),
                    Choice(value="cpu", name="CPU"),
                ],
                style=hacker_style,
            ).execute()

            # Confirm
            project_display = project_info.get("display_name", selected_project) if project_info else selected_project
            print(f"\n{Colors.CYAN}Configuration:{Colors.RESET}")
            print(f"  Model: {selected_model}")
            print(f"  Project: {project_display}")
            print(f"  Episodes: {episodes}")
            print(f"  Robot: {robot_type}")
            print(f"  Device: {device or 'auto'}")

            confirm = inquirer.confirm(
                message="Start inference?",
                default=True,
                style=hacker_style,
            ).execute()

            if not confirm:
                return MenuResult.CONTINUE

            # Run inference with WebSocket progress
            print(f"\n{Colors.CYAN}Starting inference...{Colors.RESET}\n")

            console = Console()
            output_lines = []
            max_display_lines = 20
            status_info = {"env": "", "policy": "", "started": False}

            def make_output_panel():
                """Create output display panel."""
                text = Text()

                if status_info["started"]:
                    text.append(f"Environment: {status_info['env']}  ", style="cyan")
                    text.append(f"Policy: {status_info['policy']}\n\n", style="cyan")

                # Show last N lines
                display_lines = output_lines[-max_display_lines:]
                for line in display_lines:
                    text.append(line + "\n")

                return Panel(text, title="🤖 推論実行中", border_style="cyan")

            def progress_callback(data):
                """Handle progress updates from WebSocket."""
                msg_type = data.get("type", "")

                if msg_type == "start":
                    status_info["env"] = data.get("env", "")
                    status_info["policy"] = data.get("policy", "")
                    status_info["started"] = True
                    output_lines.append(f"[開始] Model: {data.get('model_id', '')}")
                    output_lines.append(f"       Project: {data.get('project', '')}")
                elif msg_type == "output":
                    line = data.get("line", "")
                    if line:
                        output_lines.append(line)
                elif msg_type == "error_output":
                    line = data.get("line", "")
                    if line:
                        output_lines.append(f"[stderr] {line}")

            try:
                with Live(make_output_panel(), console=console, refresh_per_second=4) as live:
                    def update_display(data):
                        progress_callback(data)
                        live.update(make_output_panel())

                    result = self.api.run_inference_with_progress(
                        data={
                            "model_id": selected_model,
                            "project": selected_project,
                            "episodes": int(episodes),
                            "robot_type": robot_type,
                            "device": device,
                        },
                        progress_callback=update_display,
                    )
            except Exception as e:
                result = {"type": "error", "error": str(e)}

            if result.get("type") == "complete" and result.get("success"):
                print(f"\n{Colors.success('Inference completed successfully!')}")
            else:
                print(f"\n{Colors.error('Inference failed')}")
                if result.get("return_code"):
                    print(f"  Return code: {result.get('return_code')}")
                if result.get("error"):
                    print(f"  Error: {result.get('error')}")

            if result.get("message"):
                print(f"  Message: {result.get('message')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _list_models(self) -> MenuResult:
        """List available models."""
        show_section_header("Available Models")

        try:
            result = self.api.list_inference_models()
            models = result.get("models", [])
            total = result.get("total", len(models))

            if models:
                print(f"{Colors.CYAN}Models ({total}):{Colors.RESET}\n")
                for m in models:
                    if isinstance(m, dict):
                        model_id = m.get("model_id", m.get("name", "unknown"))
                        policy = m.get("policy_type", "?")
                        source = m.get("source", "local")
                        size_mb = m.get("size_mb", 0)
                        print(f"  - {model_id} [{policy}] ({source})")
                        if m.get("local_path"):
                            print(f"      Path: {m.get('local_path')}")
                        if size_mb:
                            print(f"      Size: {size_mb:.1f} MB")
                    else:
                        print(f"  - {m}")
            else:
                print(f"{Colors.muted('No models available.')}")
                print(f"{Colors.muted('Download models from R2 Storage menu.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _check_compatibility(self) -> MenuResult:
        """Check device compatibility."""
        show_section_header("Device Compatibility")

        try:
            result = self.api.get_device_compatibility()

            print(f"{Colors.CYAN}Compute Devices:{Colors.RESET}")
            devices = result.get("devices", [])
            for d in devices:
                device = d.get("device", "unknown")
                available = d.get("available", False)
                icon = Colors.success("✓") if available else Colors.error("✗")
                print(f"  {icon} {device}")
                if d.get("memory_total_mb"):
                    print(f"      Memory: {d.get('memory_total_mb'):.0f} MB total, {d.get('memory_free_mb', 0):.0f} MB free")

            recommended = result.get("recommended", "cpu")
            print(f"\n{Colors.CYAN}Recommended:{Colors.RESET}")
            print(f"  {recommended}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE
