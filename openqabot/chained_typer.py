# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Custom TyperGroup supporting sequential command chaining."""

from __future__ import annotations

from typing import Any

import typer
from typer.core import TyperGroup


class _ChainedTyperGroup(TyperGroup):
    """Support command chaining under newer Click/Typer versions."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401 - dictated by Click's interface
        kwargs.pop("chain", True)
        super().__init__(*args, **kwargs)
        self.chain = True

    def parse_args(self, ctx: typer._click.core.Context, args: list[str]) -> list[str]:
        if not args and self.no_args_is_help and not ctx.resilient_parsing:
            raise typer._click.exceptions.NoArgsIsHelpError(ctx)  # noqa: SLF001 - private Click/Typer APIs

        rest = typer._click.core.Command.parse_args(self, ctx, args)  # noqa: SLF001 - private Click/Typer APIs

        ctx._protected_args = rest  # noqa: SLF001 - private Click/Typer APIs
        ctx.args = []

        return ctx.args

    def collect_usage_pieces(self, ctx: typer._click.core.Context) -> list[str]:
        rest = typer._click.core.Command.collect_usage_pieces(self, ctx)  # noqa: SLF001 - private Click/Typer APIs
        rest.append("COMMAND1 [ARGS]... [COMMAND2 [ARGS]...]...")
        return rest

    def invoke(self, ctx: typer._click.core.Context) -> Any:  # noqa: ANN401 - dictated by Click's interface
        if not ctx._protected_args:  # noqa: SLF001 - private Click/Typer APIs
            ctx.fail("Missing command.")

        args = [*ctx._protected_args, *ctx.args]  # noqa: SLF001 - private Click/Typer APIs
        ctx.args = []
        ctx._protected_args = []  # noqa: SLF001 - private Click/Typer APIs

        with ctx:
            ctx.invoked_subcommand = "*" if args else None
            typer._click.core.Command.invoke(self, ctx)  # noqa: SLF001 - private Click/Typer APIs

            contexts = []
            while args:
                cmd_name, cmd, args = self.resolve_command(ctx, args)
                assert cmd is not None  # noqa: S101 - type narrowing
                if isinstance(cmd, TyperGroup):
                    sub_ctx = cmd.make_context(cmd_name, args, parent=ctx)
                    contexts.append(sub_ctx)
                    args = []
                else:
                    sub_ctx = cmd.make_context(
                        cmd_name,
                        args,
                        parent=ctx,
                        allow_extra_args=True,
                        allow_interspersed_args=False,
                    )
                    contexts.append(sub_ctx)
                    args, sub_ctx.args = sub_ctx.args, []

            rv = []
            for sub_ctx in contexts:
                with sub_ctx:
                    rv.append(sub_ctx.command.invoke(sub_ctx))
            return rv
