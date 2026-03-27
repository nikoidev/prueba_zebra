#!/usr/bin/env python3
"""
Entry point del sistema multi-agente Zebra.

Uso:
    python run.py "Quiero lanzar una plataforma SaaS de gestion de turnos"
    python run.py --verbose "Disenar una arquitectura de microservicios"
    python run.py --history          # Ver historial de ejecuciones

Flags:
    --verbose   Muestra trazas de agentes en tiempo real
    --output    Formato de salida: "json" (default) o "markdown"
    --history   Muestra el historial de las ultimas ejecuciones
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sistema Multi-Agente Zebra - Analisis y diseno de soluciones complejas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "request",
        nargs="*",
        help="Solicitud del usuario (se puede pasar como argumentos o de forma interactiva)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Mostrar trazas de agentes en tiempo real",
    )
    parser.add_argument(
        "--output", "-o",
        choices=["json", "markdown"],
        default="json",
        help="Formato de salida (default: json)",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Mostrar historial de ejecuciones recientes",
    )
    return parser


async def select_provider() -> tuple[str, str]:
    """
    Detecta los providers disponibles y pide al usuario que elija
    si hay mas de uno. Devuelve (provider, model) elegidos.
    """
    from src.config import get_settings

    settings = get_settings()
    available = settings.available_providers

    if not available:
        console.print(
            "[red]Error:[/red] No se encontro ninguna API key valida en el .env.\n"
            "Configura al menos una de: OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY"
        )
        raise SystemExit(1)

    # Modelos estaticos por proveedor (fallback si la API no responde)
    static_models = {
        "openai":    [],
        "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
        "gemini":    [],
    }

    async def get_models(provider: str) -> list[str]:
        """Devuelve modelos disponibles consultando la API del proveedor."""
        if provider == "gemini":
            try:
                from src.llm import list_gemini_models
                with console.status("[cyan]Consultando modelos Gemini disponibles...[/cyan]"):
                    models = await list_gemini_models()
                if models:
                    return models
            except Exception as e:
                console.print(f"[yellow]No se pudieron obtener modelos Gemini: {e}[/yellow]")
        elif provider == "openai":
            try:
                from src.llm import list_openai_models
                with console.status("[cyan]Consultando modelos OpenAI disponibles...[/cyan]"):
                    models = await list_openai_models()
                if models:
                    return models
            except Exception as e:
                console.print(f"[yellow]No se pudieron obtener modelos OpenAI: {e}[/yellow]")
        return static_models.get(provider, ["gpt-4o", "gpt-4o-mini"])

    # Solo un provider disponible: auto-seleccionar proveedor, mostrar menu de modelos
    if len(available) == 1:
        provider = available[0]
        models = await get_models(provider)
        if not models:
            model = settings.active_model
        elif len(models) == 1:
            model = models[0]
        else:
            console.print(f"\nModelos disponibles para [bold]{provider}[/bold]:")
            model_options = {str(i + 1): m for i, m in enumerate(models)}
            for num, mod in model_options.items():
                console.print(f"  [cyan]{num}[/cyan]. {mod}")
            model_choice = Prompt.ask(
                "Elige el modelo (o escribe uno personalizado)",
                default="1",
            )
            model = model_options.get(model_choice, model_choice)
        console.print(
            Panel(
                f"[green]Proveedor detectado:[/green] [bold]{provider}[/bold]\n"
                f"[green]Modelo:[/green] [bold]{model}[/bold]",
                title="[cyan]Configuracion LLM[/cyan]",
                border_style="cyan",
            )
        )
        return provider, model

    # Multiples providers: mostrar menu
    console.print(
        Panel(
            "Se detectaron multiples API keys. Elige el proveedor y modelo a usar.",
            title="[cyan]Seleccion de Proveedor[/cyan]",
            border_style="cyan",
        )
    )

    # Menu de proveedor (con preview de modelos estaticos)
    provider_options = {str(i + 1): p for i, p in enumerate(available)}
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", width=4)
    table.add_column("Proveedor", width=12)
    table.add_column("Modelos sugeridos")
    for num, prov in provider_options.items():
        preview = static_models.get(prov, [])
        table.add_row(num, prov, ", ".join(preview) if preview else "(se consultara la API)")
    console.print(table)

    choice = Prompt.ask(
        "Elige el proveedor",
        choices=list(provider_options.keys()),
        default="1",
    )
    provider = provider_options[choice]

    # Obtener modelos reales para el proveedor elegido
    models = await get_models(provider)

    console.print(f"\nModelos disponibles para [bold]{provider}[/bold]:")
    model_options = {str(i + 1): m for i, m in enumerate(models)}
    for num, mod in model_options.items():
        console.print(f"  [cyan]{num}[/cyan]. {mod}")

    model_choice = Prompt.ask(
        "Elige el modelo (o escribe uno personalizado)",
        default="1",
    )
    # Si el usuario escribe un numero del menu, usar ese modelo; si no, usar como nombre directo
    model = model_options.get(model_choice, model_choice)

    console.print(
        Panel(
            f"[green]Proveedor:[/green] [bold]{provider}[/bold]\n"
            f"[green]Modelo:[/green] [bold]{model}[/bold]",
            title="[cyan]Configuracion seleccionada[/cyan]",
            border_style="green",
        )
    )
    return provider, model


async def show_history() -> None:
    """Muestra el historial de ejecuciones desde la DB."""
    from src.db.connection import get_session
    from src.db.repository import get_execution_history

    async with get_session() as session:
        executions = await get_execution_history(session, limit=10)

    if not executions:
        console.print("[yellow]No hay ejecuciones registradas.[/yellow]")
        return

    table = Table(title="Historial de Ejecuciones", show_lines=True)
    table.add_column("ID", style="dim", width=12)
    table.add_column("Estado", width=12)
    table.add_column("Confianza", justify="center", width=10)
    table.add_column("Tokens", justify="right", width=8)
    table.add_column("Duracion", justify="right", width=10)
    table.add_column("Fecha", width=20)
    table.add_column("Request", width=40)

    for ex in executions:
        state_color = "green" if ex.final_state == "DONE" else "red"
        confidence = f"{ex.overall_confidence:.0%}" if ex.overall_confidence else "N/A"
        duration = f"{ex.duration_ms:.0f}ms" if ex.duration_ms else "N/A"
        table.add_row(
            ex.id[:8] + "...",
            f"[{state_color}]{ex.final_state}[/{state_color}]",
            confidence,
            str(ex.total_tokens),
            duration,
            ex.created_at.strftime("%Y-%m-%d %H:%M") if ex.created_at else "N/A",
            ex.original_request[:40] + "...",
        )

    console.print(table)


async def main_async(args: argparse.Namespace) -> int:
    # Importaciones dentro del async para que el logging este configurado
    from src.observability import configure_logging
    configure_logging()

    # 1. Verificar conexion a la DB (lo primero que ve el usuario)
    db_session = None
    db_ctx = None
    try:
        from src.db.connection import get_session, init_db
        await init_db()
        db_ctx = get_session()
        db_session = await db_ctx.__aenter__()
        console.print(
            Panel(
                "[green]Conexion establecida con la base de datos[/green]",
                title="[green]Base de datos[/green]",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(
            Panel(
                f"[red]No se pudo conectar a la base de datos:[/red] {e}\n\n"
                "[dim]Ejecuta:[/dim] [bold]docker-compose up -d[/bold]",
                title="[red]Error de conexion[/red]",
                border_style="red",
            )
        )
        return 1

    # 2. Modo historial
    if args.history:
        await show_history()
        return 0

    # 3. Seleccionar proveedor y modelo
    from src.config import set_provider_override
    provider, model = await select_provider()
    set_provider_override(provider, model)

    # Obtener el request
    if args.request:
        request = " ".join(args.request)
    else:
        console.print(
            Panel(
                "[bold cyan]Sistema Multi-Agente Zebra[/bold cyan]\n"
                "Analisis y diseno de soluciones complejas\n\n"
                "[dim]Introduce tu solicitud y presiona Enter (Ctrl+C para salir)[/dim]",
                border_style="cyan",
            )
        )
        try:
            request = console.input("[bold]Solicitud:[/bold] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelado.[/yellow]")
            return 0

    if not request:
        console.print("[red]Error: La solicitud no puede estar vacia.[/red]")
        return 1

    # Ejecutar pipeline
    console.print(
        Panel(
            f"[bold]Request:[/bold] {request[:120]}{'...' if len(request) > 120 else ''}\n"
            f"[dim]Proveedor: {provider} | Modelo: {model}[/dim]",
            title="[cyan]Iniciando Pipeline[/cyan]",
            border_style="cyan",
        )
    )

    try:
        from src.orchestrator import run

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=not args.verbose,
        ) as progress:
            task = progress.add_task("Ejecutando pipeline multi-agente...", total=None)
            result = await run(request, db_session=db_session, verbose=args.verbose)
            progress.update(task, description="[green]Pipeline completado[/green]")

    except Exception as e:
        console.print(f"[red]Error en el pipeline: {e}[/red]")
        return 1
    finally:
        if db_ctx is not None and db_session is not None:
            try:
                await db_ctx.__aexit__(None, None, None)
            except Exception:
                pass

    # Mostrar resultado
    if args.output == "markdown":
        console.print(Panel(result.to_markdown(), title="Resultado", border_style="green"))
    else:
        output_json = result.model_dump(mode="json")
        syntax = Syntax(
            json.dumps(output_json, indent=2, ensure_ascii=False),
            "json",
            theme="monokai",
            line_numbers=False,
        )
        console.print(Panel(syntax, title="[green]Resultado JSON[/green]", border_style="green"))

    # Resumen de ejecucion
    meta = result.metadata
    console.print(
        Panel(
            f"[green]Confianza global:[/green] {result.overall_confidence:.0%}\n"
            f"[cyan]Agentes invocados:[/cyan] {', '.join(meta.agents_invoked)}\n"
            f"[cyan]Revisiones:[/cyan] {meta.revisions_performed}\n"
            f"[cyan]Tokens totales:[/cyan] {meta.total_tokens} "
            f"({meta.cached_calls} desde cache)\n"
            f"[cyan]Duracion:[/cyan] {meta.total_duration_ms:.0f}ms\n"
            f"[dim]Request ID: {result.request_id}[/dim]",
            title="[cyan]Resumen de Ejecucion[/cyan]",
            border_style="cyan",
        )
    )

    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        exit_code = asyncio.run(main_async(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido por el usuario.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
