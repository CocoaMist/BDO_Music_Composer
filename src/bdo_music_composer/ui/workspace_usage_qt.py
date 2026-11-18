"""Consent and first-run integration for anonymous usage reporting."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QStackedWidget, QWidget

from bdo_music_composer.app.application_config import load_config
from bdo_music_composer.core.project_paths import USER_DATA_DIR


_STARTUP_FAILURE_MARKER = "usage-startup-failed"


def _usage_consent_from_disk(path: Path) -> bool:
    values = load_config(path).get("usage_telemetry")
    return isinstance(values, dict) and values.get("enabled") is True


def mark_startup_usage_failure(config_path: Path) -> None:
    """Carry an opted-in startup failure category across a failed launch."""
    if os.environ.get("BDO_STARTUP_SELF_TEST"):
        return
    try:
        if _usage_consent_from_disk(config_path):
            config_path.with_name(_STARTUP_FAILURE_MARKER).touch()
    except OSError:
        pass


class WorkspaceUsageHostMixin:
    @property
    def usage_telemetry_preferences(self) -> dict[str, object] | None:
        values = self.config.get("usage_telemetry")
        if isinstance(values, dict) and isinstance(values.get("enabled"), bool):
            return dict(values)
        return None

    def _home_with_usage_welcome(self, home: QWidget) -> QWidget:
        self._usage_welcome = None
        if os.environ.get("BDO_STARTUP_SELF_TEST") or self.usage_telemetry_preferences is not None:
            return home

        from bdo_music_composer.ui.home_welcome_qt import HomeWelcomePage

        pages = QStackedWidget()
        pages.setObjectName("HomePageStack")
        pages.addWidget(home)
        self._usage_welcome = welcome = HomeWelcomePage()
        pages.addWidget(welcome)
        pages.setCurrentWidget(welcome)
        welcome.decision_requested.connect(self._finish_usage_welcome)
        return pages

    def _schedule_usage_reporting(self) -> None:
        if os.environ.get("BDO_STARTUP_SELF_TEST"):
            return
        QTimer.singleShot(0, self, self._init_usage_after_first_paint)

    def _init_usage_after_first_paint(self) -> None:
        if not self.isVisible() or self.workspace_close_pending:
            return
        values = self.usage_telemetry_preferences
        if values is not None:
            self._configure_usage_reporting(values)
        else:
            self._take_usage_startup_failure()

    def _finish_usage_welcome(self, enabled: bool) -> None:
        if self._usage_welcome is None:
            return
        values = {"enabled": enabled, "server": ""}
        self.config["usage_telemetry"] = values
        try:
            self.persist_ui_config()
        except OSError:
            from bdo_music_composer.ui.i18n import tr

            self.config.pop("usage_telemetry", None)
            self.show_toast(tr("无法保存隐私设置，请在设置中重试。"), kind="warning")
            return
        self._configure_usage_reporting(values)

    def _dismiss_usage_welcome(self) -> None:
        welcome, self._usage_welcome = getattr(self, "_usage_welcome", None), None
        if welcome is None:
            return
        pages = welcome.parentWidget()
        pages.setCurrentIndex(0)
        pages.removeWidget(welcome)
        welcome.deleteLater()
        if self.isVisible() and self.page_stack.currentWidget() is pages:
            self.toolbar_home_btn.setFocus()

    def _configure_usage_reporting(self, values: dict[str, object]) -> None:
        if os.environ.get("BDO_STARTUP_SELF_TEST"):
            return
        self._dismiss_usage_welcome()
        client = getattr(self, "_usage_telemetry", None)
        enabled = values.get("enabled") is True
        server = str(values.get("server", "")) if enabled else ""
        has_startup_failure = self._take_usage_startup_failure()
        if client is None:
            queue_path = USER_DATA_DIR / "usage-telemetry-v1.json"
            if not enabled and not queue_path.is_file():
                return
            from bdo_music_composer.ui.feedback_status_qt import FEEDBACK_ORIGIN
            from bdo_music_composer.ui.usage_telemetry_qt import UsageTelemetryQt

            if not FEEDBACK_ORIGIN:
                return
            config_path = self._usage_config_path
            client = self._usage_telemetry = UsageTelemetryQt(
                self,
                endpoint=f"{FEEDBACK_ORIGIN}/api/usage/v1",
                enabled=enabled,
                server=server,
                queue_path=queue_path,
                consent_check=lambda: _usage_consent_from_disk(config_path),
            )
            client.start()
        else:
            client.configure(enabled=enabled, server=server)
        if enabled and has_startup_failure:
            client.record_issue("startup_failed")

    def _take_usage_startup_failure(self) -> bool:
        try:
            self._usage_config_path.with_name(_STARTUP_FAILURE_MARKER).unlink()
        except OSError:
            return False
        return True

    def _record_usage_feature(self, event: str) -> None:
        client = getattr(self, "_usage_telemetry", None)
        if client is not None:
            client.record(event)

    def _record_usage_issue(self, event: str) -> None:
        client = getattr(self, "_usage_telemetry", None)
        if client is not None:
            client.record_issue(event)

    def _record_usage_export(self) -> None:
        client = getattr(self, "_usage_telemetry", None)
        if client is not None:
            client.record_export()

    def _record_usage_helpfulness(self, rating: str) -> None:
        client = getattr(self, "_usage_telemetry", None)
        if rating and client is not None:
            client.record_helpfulness(rating)

    def _shutdown_usage_reporting(self) -> None:
        client = getattr(self, "_usage_telemetry", None)
        if client is not None:
            client.shutdown()
