"""Storage menu - Data management operations."""

from typing import TYPE_CHECKING, Any, List

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from interfaces_cli.banner import format_size, show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


class StorageMenu(BaseMenu):
    """Storage menu - Data management operations."""

    title = "データ管理"

    def get_choices(self) -> List[Choice]:
        return [
            Separator("─── データ ───"),
            Choice(value="datasets", name="📁 データセット管理"),
            Choice(value="models", name="🤖 モデル管理"),
            Separator("─── 同期 ───"),
            Choice(value="sync", name="🔄 R2クラウド同期"),
            Choice(value="hub", name="🌐 HuggingFace連携"),
            Choice(value="migration", name="📤 旧バージョンから移管"),
            Separator("─── 情報 ───"),
            Choice(value="archive", name="📦 アーカイブ一覧"),
            Choice(value="usage", name="📊 ストレージ使用量"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "datasets":
            return self.submenu(DatasetsMenu)
        if choice == "models":
            return self.submenu(ModelsMenu)
        if choice == "sync":
            return self.submenu(R2SyncMenu)
        if choice == "hub":
            return self.submenu(HuggingFaceMenu)
        if choice == "migration":
            return self.submenu(MigrationMenu)
        if choice == "archive":
            return self._show_archive()
        if choice == "usage":
            return self._show_usage()
        return MenuResult.CONTINUE

    def _show_usage(self) -> MenuResult:
        """Show storage usage statistics."""
        show_section_header("Storage Usage")

        try:
            usage = self.api.get_storage_usage()

            # Local storage (downloaded to disk)
            print(f"{Colors.CYAN}📁 ローカルストレージ:{Colors.RESET}")
            print(f"  データセット: {format_size(usage.get('datasets_size_bytes', 0))} ({usage.get('datasets_count', 0)}個)")
            print(f"  モデル: {format_size(usage.get('models_size_bytes', 0))} ({usage.get('models_count', 0)}個)")
            print(f"  合計: {format_size(usage.get('total_size_bytes', 0))}")

            # Remote storage (on R2, not downloaded)
            remote_total = usage.get("remote_total_size_bytes", 0)
            remote_datasets = usage.get("remote_datasets_count", 0)
            remote_models = usage.get("remote_models_count", 0)

            if remote_total > 0 or remote_datasets > 0 or remote_models > 0:
                print(f"\n{Colors.CYAN}☁️  R2リモートストレージ (未ダウンロード):{Colors.RESET}")
                print(f"  データセット: {format_size(usage.get('remote_datasets_size_bytes', 0))} ({remote_datasets}個)")
                print(f"  モデル: {format_size(usage.get('remote_models_size_bytes', 0))} ({remote_models}個)")
                print(f"  合計: {format_size(remote_total)}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_archive(self) -> MenuResult:
        """Show archived items."""
        show_section_header("Archived Items")

        try:
            result = self.api.list_archive()
            datasets = result.get("datasets", [])
            models = result.get("models", [])

            print(f"{Colors.CYAN}Archived Datasets:{Colors.RESET}")
            if datasets:
                for d in datasets[:10]:
                    name = d.get("id", "unknown")
                    size = format_size(d.get("size_bytes", 0))
                    print(f"  - {name} ({size})")
            else:
                print(f"  {Colors.muted('No archived datasets')}")

            print(f"\n{Colors.CYAN}Archived Models:{Colors.RESET}")
            if models:
                for m in models[:10]:
                    name = m.get("id", "unknown")
                    size = format_size(m.get("size_bytes", 0))
                    print(f"  - {name} ({size})")
            else:
                print(f"  {Colors.muted('No archived models')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class DatasetsMenu(BaseMenu):
    """Datasets management."""

    title = "データセット"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_datasets()
            datasets = result.get("datasets", [])
            for d in datasets[:15]:
                if isinstance(d, dict):
                    name = d.get("id", d.get("name", "unknown"))
                    size = format_size(d.get("size_bytes", 0))
                    source = d.get("source", "local")
                    choices.append(Choice(value=name, name=f"{name} ({size}) [{source}]"))
                else:
                    choices.append(Choice(value=d, name=d))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(No datasets)"))

        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK

        return self._show_dataset_actions(choice)

    def _show_dataset_actions(self, dataset_id: str) -> MenuResult:
        """Show actions for a specific dataset."""
        show_section_header(f"Dataset: {dataset_id}")

        try:
            dataset = self.api.get_dataset(dataset_id)
            print(f"  ID: {dataset.get('id', 'N/A')}")
            print(f"  Source: {dataset.get('source', 'N/A')}")
            print(f"  Size: {format_size(dataset.get('size_bytes', 0))}")
            print(f"  Episodes: {dataset.get('episode_count', 'N/A')}")
            print(f"  Created: {dataset.get('created_at', 'N/A')}")

            # Check sync status
            try:
                sync = self.api.get_dataset_sync_status(dataset_id)
                synced = sync.get("is_synced", False)
                sync_icon = Colors.success("synced") if synced else Colors.warning("not synced")
                print(f"  R2: {sync_icon}")
            except Exception:
                pass

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="upload", name="Upload to R2"),
                Choice(value="download", name="Download from R2"),
                Choice(value="publish", name="Publish to HuggingFace"),
                Choice(value="delete", name="Delete (archive)"),
                Choice(value="back", name="« Back"),
            ],
            style=hacker_style,
        ).execute()

        if action == "upload":
            try:
                self.api.upload_dataset(dataset_id)
                print(f"{Colors.success('Uploaded to R2')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "download":
            try:
                self.api.download_dataset(dataset_id)
                print(f"{Colors.success('Downloaded from R2')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "publish":
            try:
                repo_id = inquirer.text(
                    message="HuggingFace repo ID (e.g., username/dataset-name):",
                    style=hacker_style,
                ).execute()
                if repo_id:
                    private = inquirer.confirm(
                        message="Make private?",
                        default=False,
                        style=hacker_style,
                    ).execute()
                    self.api.publish_dataset(dataset_id, repo_id=repo_id, private=private)
                    print(f"{Colors.success('Published to HuggingFace')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "delete":
            confirm = inquirer.confirm(
                message=f"Archive dataset {dataset_id}?",
                default=False,
                style=hacker_style,
            ).execute()
            if confirm:
                try:
                    self.api.delete_dataset(dataset_id)
                    print(f"{Colors.success('Dataset archived')}")
                except Exception as e:
                    print(f"{Colors.error('Error:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE


class ModelsMenu(BaseMenu):
    """Models management."""

    title = "モデル"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_models()
            models = result.get("models", [])
            for m in models[:15]:
                if isinstance(m, dict):
                    name = m.get("id", m.get("name", "unknown"))
                    size = format_size(m.get("size_bytes", 0))
                    policy = m.get("policy_type", "?")
                    choices.append(Choice(value=name, name=f"{name} [{policy}] ({size})"))
                else:
                    choices.append(Choice(value=m, name=m))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(No models)"))

        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK

        return self._show_model_actions(choice)

    def _show_model_actions(self, model_id: str) -> MenuResult:
        """Show actions for a specific model."""
        show_section_header(f"Model: {model_id}")

        try:
            model = self.api.get_model(model_id)
            print(f"  ID: {model.get('id', 'N/A')}")
            print(f"  Policy: {model.get('policy_type', 'N/A')}")
            print(f"  Source: {model.get('source', 'N/A')}")
            print(f"  Size: {format_size(model.get('size_bytes', 0))}")
            print(f"  Created: {model.get('created_at', 'N/A')}")

            # Check sync status
            try:
                sync = self.api.get_model_sync_status(model_id)
                synced = sync.get("is_synced", False)
                sync_icon = Colors.success("synced") if synced else Colors.warning("not synced")
                print(f"  R2: {sync_icon}")
            except Exception:
                pass

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="upload", name="Upload to R2"),
                Choice(value="download", name="Download from R2"),
                Choice(value="publish", name="Publish to HuggingFace"),
                Choice(value="delete", name="Delete (archive)"),
                Choice(value="back", name="« Back"),
            ],
            style=hacker_style,
        ).execute()

        if action == "upload":
            try:
                self.api.upload_model(model_id)
                print(f"{Colors.success('Uploaded to R2')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "download":
            try:
                self.api.download_model(model_id)
                print(f"{Colors.success('Downloaded from R2')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "publish":
            try:
                repo_id = inquirer.text(
                    message="HuggingFace repo ID (e.g., username/model-name):",
                    style=hacker_style,
                ).execute()
                if repo_id:
                    private = inquirer.confirm(
                        message="Make private?",
                        default=False,
                        style=hacker_style,
                    ).execute()
                    self.api.publish_model(model_id, repo_id=repo_id, private=private)
                    print(f"{Colors.success('Published to HuggingFace')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "delete":
            confirm = inquirer.confirm(
                message=f"Archive model {model_id}?",
                default=False,
                style=hacker_style,
            ).execute()
            if confirm:
                try:
                    self.api.delete_model(model_id)
                    print(f"{Colors.success('Model archived')}")
                except Exception as e:
                    print(f"{Colors.error('Error:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE


class R2SyncMenu(BaseMenu):
    """R2 synchronization."""

    title = "R2クラウド同期"

    def get_choices(self) -> List[Choice]:
        return [
            Separator("─── ダウンロード ───"),
            Choice(value="download_models", name="📥 モデルをダウンロード"),
            Choice(value="download_datasets", name="📥 データセットをダウンロード"),
            Separator("─── アップロード ───"),
            Choice(value="upload_models", name="📤 モデルをアップロード"),
            Choice(value="upload_datasets", name="📤 データセットをアップロード"),
            Separator("─── プロジェクト ───"),
            Choice(value="download_projects", name="📥 プロジェクトをダウンロード"),
            Choice(value="upload_projects", name="📤 プロジェクトをアップロード"),
            Separator("─── マニフェスト管理 ───"),
            Choice(value="regenerate", name="🔄 マニフェストを再生成"),
            Choice(value="push", name="📤 マニフェストをR2にPush"),
            Choice(value="pull", name="📥 R2からマニフェストをPull"),
            Separator("─── 情報 ───"),
            Choice(value="usage", name="📊 R2ストレージ使用量"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "download_models":
            return self._download_models()
        if choice == "download_datasets":
            return self._download_datasets()
        if choice == "upload_models":
            return self._upload_models()
        if choice == "upload_datasets":
            return self._upload_datasets()
        if choice == "download_projects":
            return self._download_projects()
        if choice == "upload_projects":
            return self._upload_projects()

        show_section_header(f"R2 Sync: {choice}")

        if choice == "push":
            try:
                confirm = inquirer.confirm(
                    message="Push local manifest to R2?",
                    default=True,
                    style=hacker_style,
                ).execute()
                if confirm:
                    result = self.api.push_manifest()
                    print(f"{Colors.success('Manifest pushed to R2')}")
                    print(f"  Datasets: {result.get('datasets_count', 0)}")
                    print(f"  Models: {result.get('models_count', 0)}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif choice == "pull":
            try:
                confirm = inquirer.confirm(
                    message="Pull manifest from R2? (This will update local manifest)",
                    default=True,
                    style=hacker_style,
                ).execute()
                if confirm:
                    result = self.api.pull_manifest()
                    print(f"{Colors.success('Manifest pulled from R2')}")
                    print(f"  Datasets: {result.get('datasets_count', 0)}")
                    print(f"  Models: {result.get('models_count', 0)}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif choice == "regenerate":
            try:
                confirm = inquirer.confirm(
                    message="R2とローカルをスキャンしてマニフェストを再生成しますか？",
                    default=True,
                    style=hacker_style,
                ).execute()
                if confirm:
                    print(f"\n{Colors.CYAN}スキャン中...{Colors.RESET}")
                    result = self.api.regenerate_manifest()
                    print(f"\n{Colors.success('マニフェストを再生成しました')}")
                    print(f"\n{Colors.CYAN}R2リモート:{Colors.RESET}")
                    print(f"  モデル: {result.get('remote_models', 0)}個")
                    print(f"  データセット: {result.get('remote_datasets', 0)}個")
                    print(f"\n{Colors.CYAN}ローカル:{Colors.RESET}")
                    print(f"  モデル: {result.get('local_models', 0)}個")
                    print(f"  データセット: {result.get('local_datasets', 0)}個")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif choice == "usage":
            try:
                usage = self.api.get_storage_usage()
                print(f"{Colors.CYAN}☁️  R2リモートストレージ:{Colors.RESET}")
                print(f"  モデル: {format_size(usage.get('remote_models_size_bytes', 0))} ({usage.get('remote_models_count', 0)}個)")
                print(f"  データセット: {format_size(usage.get('remote_datasets_size_bytes', 0))} ({usage.get('remote_datasets_count', 0)}個)")
                print(f"  合計: {format_size(usage.get('remote_total_size_bytes', 0))}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _download_models(self) -> MenuResult:
        """Download models from R2."""
        show_section_header("モデルをR2からダウンロード")

        try:
            # Get models list and filter remote-only ones
            result = self.api.list_models()
            models = result.get("models", [])

            # Filter to show remote models (source=r2 and not downloaded)
            remote_models = []
            for m in models:
                if isinstance(m, dict):
                    source = m.get("source", "")
                    # Check if it's a remote model (source is r2)
                    if source == "r2":
                        remote_models.append(m)

            if not remote_models:
                print(f"{Colors.muted('R2にダウンロード可能なモデルがありません')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"ダウンロード可能なモデル: {len(remote_models)}個\n")

            choices = []
            for m in remote_models:
                model_id = m.get("id", "unknown")
                size = format_size(m.get("sync", {}).get("size_bytes", 0))
                policy = m.get("policy_type", "?")
                choices.append(Choice(
                    value=model_id,
                    name=f"{model_id} [{policy}] ({size})",
                ))

            selected = inquirer.checkbox(
                message="ダウンロードするモデルを選択:",
                choices=choices,
                style=hacker_style,
                instruction="(Spaceで選択/解除、Enterで確定)",
                keybindings={"toggle": [{"key": "space"}]},
            ).execute()

            if not selected:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Confirm
            print(f"\n{Colors.CYAN}選択されたモデル:{Colors.RESET}")
            for model_id in selected:
                print(f"  - {model_id}")

            confirm = inquirer.confirm(
                message=f"{len(selected)}個のモデルをダウンロードしますか?",
                default=True,
                style=hacker_style,
            ).execute()

            if not confirm:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Execute downloads with WebSocket progress
            print(f"\n{Colors.CYAN}ダウンロード中...{Colors.RESET}\n")

            console = Console()
            current_item = {"id": "", "file": "", "done": 0, "total": 0, "size": 0, "transferred": 0, "total_size": 0}
            completed_items = []

            def make_progress_table():
                """Create a progress display table."""
                table = Table(show_header=False, box=None, padding=(0, 1))
                table.add_column("Label", style="cyan")
                table.add_column("Value")

                if current_item["id"]:
                    table.add_row("モデル:", current_item["id"])
                    if current_item["file"]:
                        size_str = format_size(current_item["size"]) if current_item["size"] else ""
                        if current_item["size"] > 0:
                            pct = (current_item["transferred"] / current_item["size"]) * 100
                            transferred_str = format_size(current_item["transferred"])
                            progress_str = f"{transferred_str} / {size_str} ({pct:.1f}%)"
                        else:
                            progress_str = size_str
                        table.add_row("ファイル:", current_item["file"])
                        table.add_row("転送:", progress_str)
                    if current_item["total"] > 0:
                        table.add_row("ファイル数:", f"{current_item['done']}/{current_item['total']}")

                if completed_items:
                    table.add_row("完了:", f"{len(completed_items)}/{len(selected)} モデル")

                return Panel(table, title="📥 ダウンロード進捗", border_style="cyan")

            def progress_callback(data):
                """Handle progress updates from WebSocket."""
                msg_type = data.get("type", "")

                if msg_type == "start":
                    current_item["id"] = data.get("item_id", "")
                    current_item["total"] = data.get("total_files", 0)
                    current_item["total_size"] = data.get("total_size", 0)
                    current_item["done"] = 0
                    current_item["file"] = ""
                    current_item["transferred"] = 0
                elif msg_type == "downloading":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["done"] = data.get("files_done", 0)
                    current_item["transferred"] = 0
                elif msg_type == "progress":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["transferred"] = data.get("bytes_transferred", 0)
                elif msg_type == "downloaded":
                    current_item["done"] = data.get("files_done", 0)
                    current_item["transferred"] = current_item["size"]
                elif msg_type == "complete":
                    completed_items.append(data.get("item_id", ""))
                    current_item["id"] = ""
                    current_item["file"] = ""
                    current_item["transferred"] = 0
                elif msg_type == "error":
                    if data.get("item_id"):
                        pass  # Will be handled in results

            try:
                with Live(make_progress_table(), console=console, refresh_per_second=4) as live:
                    def update_display(data):
                        progress_callback(data)
                        live.update(make_progress_table())

                    result = self.api.sync_with_progress(
                        action="download",
                        entry_type="models",
                        item_ids=selected,
                        progress_callback=update_display,
                    )

                success_count = result.get("success_count", 0)
                failed_count = result.get("failed_count", 0)
                results = result.get("results", {})
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"\n{Colors.success('ダウンロード完了')}")
            print(f"  成功: {success_count}")
            print(f"  失敗: {failed_count}")

            if failed_count > 0:
                print(f"\n{Colors.error('失敗したモデル:')}")
                for item_id, info in results.items():
                    if isinstance(info, dict) and not info.get("success"):
                        error_msg = info.get("error", "Unknown error")
                        print(f"  - {item_id}: {error_msg}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _download_datasets(self) -> MenuResult:
        """Download datasets from R2."""
        show_section_header("データセットをR2からダウンロード")

        try:
            # Get datasets list and filter remote-only ones
            result = self.api.list_datasets()
            datasets = result.get("datasets", [])

            # Filter to show remote datasets (source=r2 and not downloaded)
            remote_datasets = []
            for d in datasets:
                if isinstance(d, dict):
                    source = d.get("source", "")
                    if source == "r2":
                        remote_datasets.append(d)

            if not remote_datasets:
                print(f"{Colors.muted('R2にダウンロード可能なデータセットがありません')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"ダウンロード可能なデータセット: {len(remote_datasets)}個\n")

            choices = []
            for d in remote_datasets:
                dataset_id = d.get("id", "unknown")
                size = format_size(d.get("sync", {}).get("size_bytes", 0))
                ds_type = d.get("dataset_type", "?")
                choices.append(Choice(
                    value=dataset_id,
                    name=f"{dataset_id} [{ds_type}] ({size})",
                ))

            selected = inquirer.checkbox(
                message="ダウンロードするデータセットを選択:",
                choices=choices,
                style=hacker_style,
                instruction="(Spaceで選択/解除、Enterで確定)",
                keybindings={"toggle": [{"key": "space"}]},
            ).execute()

            if not selected:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Confirm
            print(f"\n{Colors.CYAN}選択されたデータセット:{Colors.RESET}")
            for dataset_id in selected:
                print(f"  - {dataset_id}")

            confirm = inquirer.confirm(
                message=f"{len(selected)}個のデータセットをダウンロードしますか?",
                default=True,
                style=hacker_style,
            ).execute()

            if not confirm:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Execute downloads with WebSocket progress
            print(f"\n{Colors.CYAN}ダウンロード中...{Colors.RESET}\n")

            console = Console()
            current_item = {"id": "", "file": "", "done": 0, "total": 0, "size": 0, "transferred": 0}
            completed_items = []

            def make_progress_table():
                table = Table(show_header=False, box=None, padding=(0, 1))
                table.add_column("Label", style="cyan")
                table.add_column("Value")

                if current_item["id"]:
                    table.add_row("データセット:", current_item["id"])
                    if current_item["file"]:
                        size_str = format_size(current_item["size"]) if current_item["size"] else ""
                        if current_item["size"] > 0:
                            pct = (current_item["transferred"] / current_item["size"]) * 100
                            transferred_str = format_size(current_item["transferred"])
                            progress_str = f"{transferred_str} / {size_str} ({pct:.1f}%)"
                        else:
                            progress_str = size_str
                        table.add_row("ファイル:", current_item["file"])
                        table.add_row("転送:", progress_str)
                    if current_item["total"] > 0:
                        table.add_row("ファイル数:", f"{current_item['done']}/{current_item['total']}")

                if completed_items:
                    table.add_row("完了:", f"{len(completed_items)}/{len(selected)} データセット")

                return Panel(table, title="📥 ダウンロード進捗", border_style="cyan")

            def progress_callback(data):
                msg_type = data.get("type", "")
                if msg_type == "start":
                    current_item["id"] = data.get("item_id", "")
                    current_item["total"] = data.get("total_files", 0)
                    current_item["done"] = 0
                    current_item["file"] = ""
                    current_item["transferred"] = 0
                elif msg_type == "downloading":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["done"] = data.get("files_done", 0)
                    current_item["transferred"] = 0
                elif msg_type == "progress":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["transferred"] = data.get("bytes_transferred", 0)
                elif msg_type == "downloaded":
                    current_item["done"] = data.get("files_done", 0)
                    current_item["transferred"] = current_item["size"]
                elif msg_type == "complete":
                    completed_items.append(data.get("item_id", ""))
                    current_item["id"] = ""
                    current_item["file"] = ""
                    current_item["transferred"] = 0

            try:
                with Live(make_progress_table(), console=console, refresh_per_second=4) as live:
                    def update_display(data):
                        progress_callback(data)
                        live.update(make_progress_table())

                    result = self.api.sync_with_progress(
                        action="download",
                        entry_type="datasets",
                        item_ids=selected,
                        progress_callback=update_display,
                    )

                success_count = result.get("success_count", 0)
                failed_count = result.get("failed_count", 0)
                results = result.get("results", {})
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"\n{Colors.success('ダウンロード完了')}")
            print(f"  成功: {success_count}")
            print(f"  失敗: {failed_count}")

            if failed_count > 0:
                print(f"\n{Colors.error('失敗したデータセット:')}")
                for item_id, info in results.items():
                    if isinstance(info, dict) and not info.get("success"):
                        error_msg = info.get("error", "Unknown error")
                        print(f"  - {item_id}: {error_msg}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _upload_models(self) -> MenuResult:
        """Upload models to R2."""
        show_section_header("モデルをR2にアップロード")

        try:
            # Get models list and filter local ones
            result = self.api.list_models()
            models = result.get("models", [])

            # Filter to show local models that aren't synced
            local_models = []
            for m in models:
                if isinstance(m, dict):
                    source = m.get("source", "")
                    # Local models (not from r2)
                    if source != "r2":
                        local_models.append(m)

            if not local_models:
                print(f"{Colors.muted('アップロード可能なローカルモデルがありません')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"アップロード可能なモデル: {len(local_models)}個\n")

            choices = []
            for m in local_models:
                model_id = m.get("id", "unknown")
                size = format_size(m.get("sync", {}).get("size_bytes", 0))
                policy = m.get("policy_type", "?")
                choices.append(Choice(
                    value=model_id,
                    name=f"{model_id} [{policy}] ({size})",
                ))

            selected = inquirer.checkbox(
                message="アップロードするモデルを選択:",
                choices=choices,
                style=hacker_style,
                instruction="(Spaceで選択/解除、Enterで確定)",
                keybindings={"toggle": [{"key": "space"}]},
            ).execute()

            if not selected:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Confirm
            print(f"\n{Colors.CYAN}選択されたモデル:{Colors.RESET}")
            for model_id in selected:
                print(f"  - {model_id}")

            confirm = inquirer.confirm(
                message=f"{len(selected)}個のモデルをアップロードしますか?",
                default=True,
                style=hacker_style,
            ).execute()

            if not confirm:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Execute uploads with WebSocket progress
            print(f"\n{Colors.CYAN}アップロード中...{Colors.RESET}\n")

            console = Console()
            current_item = {"id": "", "file": "", "done": 0, "total": 0, "size": 0, "transferred": 0}
            completed_items = []

            def make_progress_table():
                table = Table(show_header=False, box=None, padding=(0, 1))
                table.add_column("Label", style="cyan")
                table.add_column("Value")

                if current_item["id"]:
                    table.add_row("モデル:", current_item["id"])
                    if current_item["file"]:
                        size_str = format_size(current_item["size"]) if current_item["size"] else ""
                        if current_item["size"] > 0:
                            pct = (current_item["transferred"] / current_item["size"]) * 100
                            transferred_str = format_size(current_item["transferred"])
                            progress_str = f"{transferred_str} / {size_str} ({pct:.1f}%)"
                        else:
                            progress_str = size_str
                        table.add_row("ファイル:", current_item["file"])
                        table.add_row("転送:", progress_str)
                    if current_item["total"] > 0:
                        table.add_row("ファイル数:", f"{current_item['done']}/{current_item['total']}")

                if completed_items:
                    table.add_row("完了:", f"{len(completed_items)}/{len(selected)} モデル")

                return Panel(table, title="📤 アップロード進捗", border_style="green")

            def progress_callback(data):
                msg_type = data.get("type", "")
                if msg_type == "start":
                    current_item["id"] = data.get("item_id", "")
                    current_item["total"] = data.get("total_files", 0)
                    current_item["done"] = 0
                    current_item["file"] = ""
                    current_item["transferred"] = 0
                elif msg_type == "uploading":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["done"] = data.get("files_done", 0)
                    current_item["transferred"] = 0
                elif msg_type == "progress":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["transferred"] = data.get("bytes_transferred", 0)
                elif msg_type == "uploaded":
                    current_item["done"] = data.get("files_done", 0)
                    current_item["transferred"] = current_item["size"]
                elif msg_type == "complete":
                    completed_items.append(data.get("item_id", ""))
                    current_item["id"] = ""
                    current_item["file"] = ""
                    current_item["transferred"] = 0

            try:
                with Live(make_progress_table(), console=console, refresh_per_second=4) as live:
                    def update_display(data):
                        progress_callback(data)
                        live.update(make_progress_table())

                    result = self.api.sync_with_progress(
                        action="upload",
                        entry_type="models",
                        item_ids=selected,
                        progress_callback=update_display,
                    )

                success_count = result.get("success_count", 0)
                failed_count = result.get("failed_count", 0)
                results = result.get("results", {})
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"\n{Colors.success('アップロード完了')}")
            print(f"  成功: {success_count}")
            print(f"  失敗: {failed_count}")

            if failed_count > 0:
                print(f"\n{Colors.error('失敗したモデル:')}")
                for item_id, info in results.items():
                    if isinstance(info, dict) and not info.get("success"):
                        error_msg = info.get("error", "Unknown error")
                        print(f"  - {item_id}: {error_msg}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _upload_datasets(self) -> MenuResult:
        """Upload datasets to R2."""
        show_section_header("データセットをR2にアップロード")

        try:
            # Get datasets list and filter local ones
            result = self.api.list_datasets()
            datasets = result.get("datasets", [])

            # Filter to show local datasets
            local_datasets = []
            for d in datasets:
                if isinstance(d, dict):
                    source = d.get("source", "")
                    if source != "r2":
                        local_datasets.append(d)

            if not local_datasets:
                print(f"{Colors.muted('アップロード可能なローカルデータセットがありません')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"アップロード可能なデータセット: {len(local_datasets)}個\n")

            choices = []
            for d in local_datasets:
                dataset_id = d.get("id", "unknown")
                size = format_size(d.get("sync", {}).get("size_bytes", 0))
                ds_type = d.get("dataset_type", "?")
                choices.append(Choice(
                    value=dataset_id,
                    name=f"{dataset_id} [{ds_type}] ({size})",
                ))

            selected = inquirer.checkbox(
                message="アップロードするデータセットを選択:",
                choices=choices,
                style=hacker_style,
                instruction="(Spaceで選択/解除、Enterで確定)",
                keybindings={"toggle": [{"key": "space"}]},
            ).execute()

            if not selected:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Confirm
            print(f"\n{Colors.CYAN}選択されたデータセット:{Colors.RESET}")
            for dataset_id in selected:
                print(f"  - {dataset_id}")

            confirm = inquirer.confirm(
                message=f"{len(selected)}個のデータセットをアップロードしますか?",
                default=True,
                style=hacker_style,
            ).execute()

            if not confirm:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Execute uploads with WebSocket progress
            print(f"\n{Colors.CYAN}アップロード中...{Colors.RESET}\n")

            console = Console()
            current_item = {"id": "", "file": "", "done": 0, "total": 0, "size": 0, "transferred": 0}
            completed_items = []

            def make_progress_table():
                table = Table(show_header=False, box=None, padding=(0, 1))
                table.add_column("Label", style="cyan")
                table.add_column("Value")

                if current_item["id"]:
                    table.add_row("データセット:", current_item["id"])
                    if current_item["file"]:
                        size_str = format_size(current_item["size"]) if current_item["size"] else ""
                        if current_item["size"] > 0:
                            pct = (current_item["transferred"] / current_item["size"]) * 100
                            transferred_str = format_size(current_item["transferred"])
                            progress_str = f"{transferred_str} / {size_str} ({pct:.1f}%)"
                        else:
                            progress_str = size_str
                        table.add_row("ファイル:", current_item["file"])
                        table.add_row("転送:", progress_str)
                    if current_item["total"] > 0:
                        table.add_row("ファイル数:", f"{current_item['done']}/{current_item['total']}")

                if completed_items:
                    table.add_row("完了:", f"{len(completed_items)}/{len(selected)} データセット")

                return Panel(table, title="📤 アップロード進捗", border_style="green")

            def progress_callback(data):
                msg_type = data.get("type", "")
                if msg_type == "start":
                    current_item["id"] = data.get("item_id", "")
                    current_item["total"] = data.get("total_files", 0)
                    current_item["done"] = 0
                    current_item["file"] = ""
                    current_item["transferred"] = 0
                elif msg_type == "uploading":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["done"] = data.get("files_done", 0)
                    current_item["transferred"] = 0
                elif msg_type == "progress":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["transferred"] = data.get("bytes_transferred", 0)
                elif msg_type == "uploaded":
                    current_item["done"] = data.get("files_done", 0)
                    current_item["transferred"] = current_item["size"]
                elif msg_type == "complete":
                    completed_items.append(data.get("item_id", ""))
                    current_item["id"] = ""
                    current_item["file"] = ""
                    current_item["transferred"] = 0

            try:
                with Live(make_progress_table(), console=console, refresh_per_second=4) as live:
                    def update_display(data):
                        progress_callback(data)
                        live.update(make_progress_table())

                    result = self.api.sync_with_progress(
                        action="upload",
                        entry_type="datasets",
                        item_ids=selected,
                        progress_callback=update_display,
                    )

                success_count = result.get("success_count", 0)
                failed_count = result.get("failed_count", 0)
                results = result.get("results", {})
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"\n{Colors.success('アップロード完了')}")
            print(f"  成功: {success_count}")
            print(f"  失敗: {failed_count}")

            if failed_count > 0:
                print(f"\n{Colors.error('失敗したデータセット:')}")
                for item_id, info in results.items():
                    if isinstance(info, dict) and not info.get("success"):
                        error_msg = info.get("error", "Unknown error")
                        print(f"  - {item_id}: {error_msg}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _download_projects(self) -> MenuResult:
        """Download projects from R2."""
        show_section_header("プロジェクトをR2からダウンロード")

        try:
            # List remote projects
            print(f"{Colors.CYAN}R2のプロジェクトを検索中...{Colors.RESET}\n")
            result = self.api.list_remote_projects()
            remote_projects = result.get("projects", [])

            if not remote_projects:
                print(f"{Colors.muted('R2にプロジェクトがありません')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Get local projects to filter out already downloaded ones
            local_result = self.api.list_storage_projects()
            local_projects = local_result.get("projects", [])
            local_ids = {p.get("id") for p in local_projects}

            # Filter to not-yet-downloaded projects
            choices = []
            for p in remote_projects:
                project_id = p.get("id", "unknown")
                size = format_size(p.get("size_bytes", 0))
                downloaded = "✓" if project_id in local_ids else ""
                choices.append(Choice(
                    value=project_id,
                    name=f"{project_id} ({size}) {downloaded}",
                ))

            if not choices:
                print(f"{Colors.muted('ダウンロード可能なプロジェクトがありません')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"見つかったプロジェクト: {len(remote_projects)}個\n")

            selected = inquirer.checkbox(
                message="ダウンロードするプロジェクトを選択:",
                choices=choices,
                style=hacker_style,
                instruction="(Spaceで選択/解除、Enterで確定)",
                keybindings={"toggle": [{"key": "space"}]},
            ).execute()

            if not selected:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Download each project
            print(f"\n{Colors.CYAN}ダウンロード中...{Colors.RESET}\n")

            success_count = 0
            failed_count = 0
            for project_id in selected:
                try:
                    self.api.download_storage_project(project_id)
                    print(f"  {Colors.success('✓')} {project_id}")
                    success_count += 1
                except Exception as e:
                    print(f"  {Colors.error('✗')} {project_id}: {e}")
                    failed_count += 1

            print(f"\n{Colors.success('ダウンロード完了')}")
            print(f"  成功: {success_count}")
            print(f"  失敗: {failed_count}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _upload_projects(self) -> MenuResult:
        """Upload projects to R2."""
        show_section_header("プロジェクトをR2にアップロード")

        try:
            # List local projects
            result = self.api.list_storage_projects()
            projects = result.get("projects", [])

            if not projects:
                print(f"{Colors.muted('ローカルにプロジェクトがありません')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"見つかったプロジェクト: {len(projects)}個\n")

            choices = []
            for p in projects:
                project_id = p.get("id", "unknown")
                display_name = p.get("display_name", project_id)
                robot_type = p.get("robot_type", "?")
                choices.append(Choice(
                    value=project_id,
                    name=f"{display_name} ({project_id}) [{robot_type}]",
                ))

            selected = inquirer.checkbox(
                message="アップロードするプロジェクトを選択:",
                choices=choices,
                style=hacker_style,
                instruction="(Spaceで選択/解除、Enterで確定)",
                keybindings={"toggle": [{"key": "space"}]},
            ).execute()

            if not selected:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Upload each project
            print(f"\n{Colors.CYAN}アップロード中...{Colors.RESET}\n")

            success_count = 0
            failed_count = 0
            for project_id in selected:
                try:
                    self.api.upload_storage_project(project_id)
                    print(f"  {Colors.success('✓')} {project_id}")
                    success_count += 1
                except Exception as e:
                    print(f"  {Colors.error('✗')} {project_id}: {e}")
                    failed_count += 1

            print(f"\n{Colors.success('アップロード完了')}")
            print(f"  成功: {success_count}")
            print(f"  失敗: {failed_count}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class HuggingFaceMenu(BaseMenu):
    """HuggingFace Hub integration."""

    title = "HuggingFace"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="import_dataset", name="📥 [IMPORT] データセットをダウンロード"),
            Choice(value="import_model", name="📥 [IMPORT] モデルをダウンロード"),
            Choice(value="search", name="🔍 [SEARCH] Hubを検索"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "import_dataset":
            return self._import_dataset()
        if choice == "import_model":
            return self._import_model()
        if choice == "search":
            return self._search_hub()
        return MenuResult.CONTINUE

    def _import_dataset(self) -> MenuResult:
        """Import dataset from HuggingFace Hub."""
        show_section_header("Import Dataset from HuggingFace")

        try:
            repo_id = inquirer.text(
                message="Repository ID (e.g., lerobot/pusht):",
                style=hacker_style,
            ).execute()

            if not repo_id:
                return MenuResult.CONTINUE

            print(f"{Colors.muted('Importing dataset...')}")
            result = self.api.import_dataset(repo_id)
            print(f"{Colors.success('Dataset imported!')}")
            print(f"  ID: {result.get('dataset_id', repo_id)}")
            print(f"  Size: {format_size(result.get('size_bytes', 0))}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _import_model(self) -> MenuResult:
        """Import model from HuggingFace Hub."""
        show_section_header("Import Model from HuggingFace")

        try:
            repo_id = inquirer.text(
                message="Repository ID (e.g., lerobot/act_pusht):",
                style=hacker_style,
            ).execute()

            if not repo_id:
                return MenuResult.CONTINUE

            print(f"{Colors.muted('Importing model...')}")
            result = self.api.import_model(repo_id)
            print(f"{Colors.success('Model imported!')}")
            print(f"  ID: {result.get('model_id', repo_id)}")
            print(f"  Policy: {result.get('policy_type', 'N/A')}")
            print(f"  Size: {format_size(result.get('size_bytes', 0))}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _search_hub(self) -> MenuResult:
        """Search HuggingFace Hub."""
        show_section_header("Search HuggingFace Hub")

        try:
            query = inquirer.text(
                message="Search query:",
                style=hacker_style,
            ).execute()

            if not query:
                return MenuResult.CONTINUE

            # Search datasets
            print(f"\n{Colors.CYAN}Searching datasets...{Colors.RESET}")
            datasets = self.api.search_datasets(query)
            ds_list = datasets.get("results", [])
            if ds_list:
                for d in ds_list[:5]:
                    print(f"  - {d.get('id', 'unknown')}")
            else:
                print(f"  {Colors.muted('No datasets found')}")

            # Search models
            print(f"\n{Colors.CYAN}Searching models...{Colors.RESET}")
            models = self.api.search_models(query)
            m_list = models.get("results", [])
            if m_list:
                for m in m_list[:5]:
                    print(f"  - {m.get('id', 'unknown')}")
            else:
                print(f"  {Colors.muted('No models found')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class MigrationMenu(BaseMenu):
    """Migration menu - Migrate data from legacy storage."""

    title = "データ移管"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="models", name="🤖 [MODELS] モデルを移管"),
            Choice(value="datasets", name="📁 [DATASETS] データセットを移管"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "models":
            return self._migrate_models()
        if choice == "datasets":
            return self._migrate_datasets()
        return MenuResult.CONTINUE

    def _migrate_models(self) -> MenuResult:
        """Migrate models from legacy storage."""
        show_section_header("モデル移管")

        try:
            print(f"{Colors.CYAN}旧バージョンのモデルを検索中...{Colors.RESET}\n")
            result = self.api.list_legacy_models()
            items = result.get("items", [])

            if not items:
                print(f"{Colors.muted('旧バージョンにモデルがありません')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Show list with multi-select
            print(f"見つかったモデル: {len(items)}個\n")

            choices = []
            for item in items:
                item_id = item.get("id", "unknown")
                size = format_size(item.get("size_bytes", 0))
                file_count = item.get("file_count", 0)
                choices.append(Choice(
                    value=item_id,
                    name=f"{item_id} ({size}, {file_count}ファイル)",
                ))

            selected = inquirer.checkbox(
                message="移管するモデルを選択:",
                choices=choices,
                style=hacker_style,
                instruction="(Spaceで選択/解除、Enterで確定)",
                keybindings={"toggle": [{"key": "space"}]},
            ).execute()

            if not selected:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Confirm
            print(f"\n{Colors.CYAN}選択されたモデル:{Colors.RESET}")
            for item_id in selected:
                print(f"  - {item_id}")

            delete_legacy = inquirer.confirm(
                message="移管後に旧バージョンのデータを削除しますか?",
                default=False,
                style=hacker_style,
            ).execute()

            confirm = inquirer.confirm(
                message=f"{len(selected)}個のモデルを移管しますか?",
                default=True,
                style=hacker_style,
            ).execute()

            if not confirm:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Execute migration with WebSocket progress
            print(f"\n{Colors.CYAN}移管中...{Colors.RESET}\n")

            console = Console()
            current_item = {"id": "", "file": "", "copied": 0, "total": 0, "size": 0, "transferred": 0}
            completed_items = []
            failed_items = []

            def make_progress_table():
                """Create a progress display table."""
                table = Table(show_header=False, box=None, padding=(0, 1))
                table.add_column("Label", style="cyan")
                table.add_column("Value")

                if current_item["id"]:
                    table.add_row("アイテム:", current_item["id"])
                    if current_item["file"]:
                        size_str = format_size(current_item["size"]) if current_item["size"] else ""
                        # Calculate percentage
                        if current_item["size"] > 0:
                            pct = (current_item["transferred"] / current_item["size"]) * 100
                            transferred_str = format_size(current_item["transferred"])
                            progress_str = f"{transferred_str} / {size_str} ({pct:.1f}%)"
                        else:
                            progress_str = size_str
                        table.add_row("ファイル:", current_item["file"])
                        table.add_row("転送:", progress_str)
                    if current_item["total"] > 0:
                        table.add_row("ファイル数:", f"{current_item['copied']}/{current_item['total']}")

                if completed_items:
                    table.add_row("完了:", f"{len(completed_items)}/{len(selected)} アイテム")

                return Panel(table, title="📤 移管進捗", border_style="cyan")

            def progress_callback(data):
                """Handle progress updates from WebSocket."""
                msg_type = data.get("type", "")

                if msg_type == "start":
                    current_item["id"] = data.get("item_id", "")
                    current_item["total"] = data.get("total_files", 0)
                    current_item["copied"] = 0
                    current_item["file"] = ""
                    current_item["transferred"] = 0
                elif msg_type == "copying":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["copied"] = data.get("copied_files", 0)
                    current_item["transferred"] = 0
                elif msg_type == "progress":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["transferred"] = data.get("bytes_transferred", 0)
                elif msg_type == "copied":
                    current_item["copied"] = data.get("copied_files", 0)
                    current_item["transferred"] = current_item["size"]
                elif msg_type == "complete":
                    completed_items.append(data.get("item_id", ""))
                    current_item["id"] = ""
                    current_item["file"] = ""
                    current_item["transferred"] = 0
                elif msg_type == "error":
                    if data.get("item_id"):
                        failed_items.append(data.get("item_id", ""))

            try:
                with Live(make_progress_table(), console=console, refresh_per_second=4) as live:
                    def update_display(data):
                        progress_callback(data)
                        live.update(make_progress_table())

                    result = self.api.migrate_with_progress(
                        entry_type="models",
                        item_ids=selected,
                        delete_legacy=delete_legacy,
                        progress_callback=update_display,
                    )

                success_count = result.get("success_count", 0)
                failed_count = result.get("failed_count", 0)
                results = result.get("results", {})
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"\n{Colors.success('移管完了')}")
            print(f"  成功: {success_count}")
            print(f"  失敗: {failed_count}")

            if failed_count > 0:
                print(f"\n{Colors.error('失敗したモデル:')}")
                for item_id, info in results.items():
                    if isinstance(info, dict) and not info.get("success"):
                        error_msg = info.get("error", "Unknown error")
                        print(f"  - {item_id}: {error_msg}")
                    elif not info:
                        print(f"  - {item_id}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _migrate_datasets(self) -> MenuResult:
        """Migrate datasets from legacy storage."""
        show_section_header("データセット移管")

        try:
            print(f"{Colors.CYAN}旧バージョンのデータセットを検索中...{Colors.RESET}\n")
            result = self.api.list_legacy_datasets()
            items = result.get("items", [])

            if not items:
                print(f"{Colors.muted('旧バージョンにデータセットがありません')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Show list with multi-select
            print(f"見つかったデータセット: {len(items)}個\n")

            choices = []
            for item in items:
                item_id = item.get("id", "unknown")
                size = format_size(item.get("size_bytes", 0))
                file_count = item.get("file_count", 0)
                choices.append(Choice(
                    value=item_id,
                    name=f"{item_id} ({size}, {file_count}ファイル)",
                ))

            selected = inquirer.checkbox(
                message="移管するデータセットを選択:",
                choices=choices,
                style=hacker_style,
                instruction="(Spaceで選択/解除、Enterで確定)",
                keybindings={"toggle": [{"key": "space"}]},
            ).execute()

            if not selected:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Confirm
            print(f"\n{Colors.CYAN}選択されたデータセット:{Colors.RESET}")
            for item_id in selected:
                print(f"  - {item_id}")

            delete_legacy = inquirer.confirm(
                message="移管後に旧バージョンのデータを削除しますか?",
                default=False,
                style=hacker_style,
            ).execute()

            confirm = inquirer.confirm(
                message=f"{len(selected)}個のデータセットを移管しますか?",
                default=True,
                style=hacker_style,
            ).execute()

            if not confirm:
                print(f"{Colors.muted('キャンセルされました')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Execute migration with WebSocket progress
            print(f"\n{Colors.CYAN}移管中...{Colors.RESET}\n")

            console = Console()
            current_item = {"id": "", "file": "", "copied": 0, "total": 0, "size": 0, "transferred": 0}
            completed_items = []
            failed_items = []

            def make_progress_table():
                """Create a progress display table."""
                table = Table(show_header=False, box=None, padding=(0, 1))
                table.add_column("Label", style="cyan")
                table.add_column("Value")

                if current_item["id"]:
                    table.add_row("アイテム:", current_item["id"])
                    if current_item["file"]:
                        size_str = format_size(current_item["size"]) if current_item["size"] else ""
                        # Calculate percentage
                        if current_item["size"] > 0:
                            pct = (current_item["transferred"] / current_item["size"]) * 100
                            transferred_str = format_size(current_item["transferred"])
                            progress_str = f"{transferred_str} / {size_str} ({pct:.1f}%)"
                        else:
                            progress_str = size_str
                        table.add_row("ファイル:", current_item["file"])
                        table.add_row("転送:", progress_str)
                    if current_item["total"] > 0:
                        table.add_row("ファイル数:", f"{current_item['copied']}/{current_item['total']}")

                if completed_items:
                    table.add_row("完了:", f"{len(completed_items)}/{len(selected)} アイテム")

                return Panel(table, title="📤 移管進捗", border_style="cyan")

            def progress_callback(data):
                """Handle progress updates from WebSocket."""
                msg_type = data.get("type", "")

                if msg_type == "start":
                    current_item["id"] = data.get("item_id", "")
                    current_item["total"] = data.get("total_files", 0)
                    current_item["copied"] = 0
                    current_item["file"] = ""
                    current_item["transferred"] = 0
                elif msg_type == "copying":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["copied"] = data.get("copied_files", 0)
                    current_item["transferred"] = 0
                elif msg_type == "progress":
                    current_item["file"] = data.get("current_file", "")
                    current_item["size"] = data.get("file_size", 0)
                    current_item["transferred"] = data.get("bytes_transferred", 0)
                elif msg_type == "copied":
                    current_item["copied"] = data.get("copied_files", 0)
                    current_item["transferred"] = current_item["size"]
                elif msg_type == "complete":
                    completed_items.append(data.get("item_id", ""))
                    current_item["id"] = ""
                    current_item["file"] = ""
                    current_item["transferred"] = 0
                elif msg_type == "error":
                    if data.get("item_id"):
                        failed_items.append(data.get("item_id", ""))

            try:
                with Live(make_progress_table(), console=console, refresh_per_second=4) as live:
                    def update_display(data):
                        progress_callback(data)
                        live.update(make_progress_table())

                    result = self.api.migrate_with_progress(
                        entry_type="datasets",
                        item_ids=selected,
                        delete_legacy=delete_legacy,
                        progress_callback=update_display,
                    )

                success_count = result.get("success_count", 0)
                failed_count = result.get("failed_count", 0)
                results = result.get("results", {})
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"\n{Colors.success('移管完了')}")
            print(f"  成功: {success_count}")
            print(f"  失敗: {failed_count}")

            if failed_count > 0:
                print(f"\n{Colors.error('失敗したデータセット:')}")
                for item_id, info in results.items():
                    if isinstance(info, dict) and not info.get("success"):
                        error_msg = info.get("error", "Unknown error")
                        print(f"  - {item_id}: {error_msg}")
                    elif not info:
                        print(f"  - {item_id}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE
