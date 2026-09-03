from __future__ import annotations

from typing import Any

import typer
from typer import rich_utils
from typer.core import TyperCommand, TyperGroup


def _localize_rich_help() -> None:
    rich_utils.ARGUMENTS_PANEL_TITLE = "参数"
    rich_utils.OPTIONS_PANEL_TITLE = "选项"
    rich_utils.COMMANDS_PANEL_TITLE = "命令"
    rich_utils.ERRORS_PANEL_TITLE = "错误"
    rich_utils.ABORTED_TEXT = "已取消。"
    rich_utils.RICH_HELP = "可运行 [blue]'{command_path} {help_option}'[/] 查看帮助。"


class _ChineseHelpMixin:
    def format_usage(self, ctx, formatter) -> None:
        pieces = self.collect_usage_pieces(ctx)
        formatter.write_usage(ctx.command_path, " ".join(pieces), prefix="用法：")

    def get_help_option(self, ctx):
        option = super().get_help_option(ctx)
        if option is not None:
            option.help = "显示帮助信息并退出。"
        return option


class ChineseTyperCommand(_ChineseHelpMixin, TyperCommand):
    pass


class ChineseTyperGroup(_ChineseHelpMixin, TyperGroup):
    pass


class ChineseTyper(typer.Typer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _localize_rich_help()
        kwargs.setdefault("cls", ChineseTyperGroup)
        kwargs.setdefault("add_completion", False)
        kwargs.setdefault("context_settings", {"help_option_names": ["-h", "--help"]})
        kwargs.setdefault("options_metavar", "[选项]")
        kwargs.setdefault("subcommand_metavar", "命令 [参数]...")
        super().__init__(*args, **kwargs)

    def command(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("cls", ChineseTyperCommand)
        kwargs.setdefault("options_metavar", "[选项]")
        return super().command(*args, **kwargs)
