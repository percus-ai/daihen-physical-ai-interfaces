"""Record menu - Simplified data recording operations."""

from typing import Any, List, Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from interfaces_cli.banner import format_size, show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style


class RecordMenu(BaseMenu):
    """Record menu - Data recording operations."""

    title = "データ録画"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="start", name="🎬 [START] 録画開始"),
            Choice(value="stop", name="⏹️  [STOP] 録画停止"),
            Choice(value="pause", name="⏸️  [PAUSE] 一時停止"),
            Choice(value="resume", name="▶️  [RESUME] 再開"),
            Choice(value="cancel", name="🛑 [CANCEL] 録画キャンセル"),
            Choice(value="status", name="ℹ️  [STATUS] 状態確認"),
            Choice(value="list", name="📁 [LIST] 録画一覧"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "start":
            return self._start_recording()
        if choice == "stop":
            return self._stop_recording()
        if choice == "pause":
            return self._pause_recording()
        if choice == "resume":
            return self._resume_recording()
        if choice == "cancel":
            return self._cancel_recording()
        if choice == "status":
            return self._show_status()
        if choice == "list":
            return self.submenu(RecordingsListMenu)
        return MenuResult.CONTINUE

    def _select_profile_instance(self, allow_auto: bool = True) -> Optional[str]:
        """Select profile instance (or use active)."""
        active_instance = None
        try:
            active_result = self.api.get_active_profile_instance()
            active_instance = active_result.get("instance")
        except Exception:
            active_instance = None

        try:
            result = self.api.list_profile_instances()
            instances = result.get("instances", [])
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            return None

        if not instances and not active_instance:
            print(f"{Colors.warning('No profile instances found.')}")
            print(f"{Colors.muted('プロフィールを作成してから録画を開始してください。')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return None

        choices: List[Choice] = []
        if allow_auto:
            if active_instance:
                label = f"★ active: {active_instance.get('class_key', '?')}:{active_instance.get('name', 'active')}"
            else:
                label = "Use active profile (auto)"
            choices.append(Choice(value="__auto__", name=label))

        for inst in instances:
            inst_id = inst.get("id") or ""
            if not inst_id:
                continue
            label = f"{inst.get('class_key', '?')}:{inst.get('name', 'active')} ({inst_id[:8]})"
            if inst.get("is_active"):
                label = "★ " + label
            choices.append(Choice(value=inst_id, name=label))

        choices.append(Choice(value="__back__", name="« Cancel"))

        selection = inquirer.select(
            message="Select profile instance:",
            choices=choices,
            style=hacker_style,
        ).execute()

        if selection in ("__back__", None):
            return None
        if selection == "__auto__":
            return None
        return selection

    def _start_recording(self) -> MenuResult:
        show_section_header("Recording: Start")

        profile_instance_id = self._select_profile_instance()
        if profile_instance_id is None:
            # None means auto; proceed
            pass

        dataset_name = inquirer.text(
            message="Dataset name:",
            style=hacker_style,
        ).execute()
        if not dataset_name:
            return MenuResult.CONTINUE

        task = inquirer.text(
            message="Task description:",
            style=hacker_style,
        ).execute()
        if not task:
            return MenuResult.CONTINUE

        tags_raw = inquirer.text(
            message="Tags (comma separated, optional):",
            default="",
            style=hacker_style,
        ).execute()
        tags = [t.strip() for t in (tags_raw or "").split(",") if t.strip()]

        payload = {
            "profile_instance_id": profile_instance_id,
            "dataset_name": dataset_name,
            "task": task,
            "tags": tags,
        }

        try:
            result = self.api.start_recording_session(payload)
            dataset_id = result.get("dataset_id")
            print(f"\n{Colors.success('Recording started')}:")
            print(f"  Dataset ID: {dataset_id}")
            print(f"  Message: {result.get('message', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _stop_recording(self) -> MenuResult:
        show_section_header("Recording: Stop")
        dataset_id = None
        try:
            status = self.api.get_recording_status()
            dataset_id = status.get("dataset_id")
        except Exception:
            dataset_id = None

        dataset_id_input = inquirer.text(
            message="Dataset ID (blank to auto):",
            default=dataset_id or "",
            style=hacker_style,
        ).execute()
        dataset_id = dataset_id_input.strip() or None

        tags_raw = inquirer.text(
            message="Append tags (comma separated, optional):",
            default="",
            style=hacker_style,
        ).execute()
        tags_append = [t.strip() for t in (tags_raw or "").split(",") if t.strip()]

        payload = {
            "dataset_id": dataset_id,
            "tags_append": tags_append,
            "metadata_append": {},
        }

        try:
            result = self.api.stop_recording_session(payload)
            print(f"\n{Colors.success('Recording stopped')}:")
            print(f"  Dataset ID: {result.get('dataset_id')}")
            print(f"  Message: {result.get('message', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _pause_recording(self) -> MenuResult:
        show_section_header("Recording: Pause")
        try:
            result = self.api.pause_recording_session()
            print(f"\n{Colors.success('Recording paused')}:")
            print(f"  Message: {result.get('message', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _resume_recording(self) -> MenuResult:
        show_section_header("Recording: Resume")
        try:
            result = self.api.resume_recording_session()
            print(f"\n{Colors.success('Recording resumed')}:")
            print(f"  Message: {result.get('message', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _cancel_recording(self) -> MenuResult:
        show_section_header("Recording: Cancel")
        dataset_id = inquirer.text(
            message="Dataset ID to archive (optional):",
            default="",
            style=hacker_style,
        ).execute()
        dataset_id = dataset_id.strip() or None
        try:
            result = self.api.cancel_recording_session({"dataset_id": dataset_id} if dataset_id else {})
            print(f"\n{Colors.warning('Recording cancelled')}:")
            print(f"  Dataset ID: {result.get('dataset_id')}")
            print(f"  Message: {result.get('message', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_status(self) -> MenuResult:
        show_section_header("Recording: Status")
        try:
            result = self.api.get_recording_status()
            dataset_id = result.get("dataset_id")
            status = result.get("status", {})
            print(f"  Dataset ID: {dataset_id}")
            if status:
                for key, value in status.items():
                    print(f"  {key}: {value}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class RecordingsListMenu(BaseMenu):
    """List all recordings."""

    title = "録画一覧"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_recordings()
            recordings = result.get("recordings", [])
            for r in recordings[:30]:
                rec_id = r.get("recording_id", "unknown")
                name = r.get("dataset_name", rec_id)
                episodes = r.get("episode_count", 0)
                size = format_size(r.get("size_bytes", 0))
                profile_id = r.get("profile_instance_id")
                profile_short = profile_id[:8] if profile_id else "-"
                choices.append(Choice(
                    value=rec_id,
                    name=f"{name} ({episodes} eps, {size}) [profile:{profile_short}]",
                ))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(No recordings)"))

        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK

        return self._show_recording_detail(choice)

    def _show_recording_detail(self, recording_id: str) -> MenuResult:
        """Show recording details and actions."""
        show_section_header(f"Recording: {recording_id}")

        try:
            recording = self.api.get_recording(recording_id)
            print(f"  ID: {recording.get('recording_id', 'N/A')}")
            print(f"  Name: {recording.get('dataset_name', 'N/A')}")
            print(f"  Profile: {recording.get('profile_instance_id', 'N/A')}")
            print(f"  Episodes: {recording.get('episode_count', 0)}")
            print(f"  Size: {format_size(recording.get('size_bytes', 0))}")
            print(f"  Created: {recording.get('created_at', 'N/A')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        # Actions
        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="validate", name="Validate recording"),
                Choice(value="delete", name="Delete recording"),
                Choice(value="back", name="« Back"),
            ],
            style=hacker_style,
        ).execute()

        if action == "validate":
            try:
                result = self.api.validate_recording(recording_id)
                is_valid = result.get("is_valid", False)

                if is_valid:
                    print(f"\n{Colors.success('Recording is valid')}")
                else:
                    print(f"\n{Colors.warning('Recording has issues:')}")

                errors = result.get("errors", [])
                if errors:
                    print(f"\n{Colors.CYAN}Errors:{Colors.RESET}")
                    for err in errors:
                        print(f"  {Colors.error('!')} {err}")

                warnings = result.get("warnings", [])
                if warnings:
                    print(f"\n{Colors.CYAN}Warnings:{Colors.RESET}")
                    for warn in warnings:
                        print(f"  {Colors.warning('!')} {warn}")

            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "delete":
            confirm = inquirer.confirm(
                message=f"Delete recording {recording_id}?",
                default=False,
                style=hacker_style,
            ).execute()
            if confirm:
                try:
                    self.api.delete_recording(recording_id)
                    print(f"\n{Colors.success('Recording deleted')}")
                except Exception as e:
                    print(f"{Colors.error('Error:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE
