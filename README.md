# Sistema Multi-Agente — Prueba Técnica Zebra

Sistema multi-agente en Python que recibe una solicitud compleja, la descompone en subtareas, coordina agentes especializados y produce una respuesta final estructurada, validada y trazable.

---

## Arquitectura del sistema

```
                           ┌─────────────────────────────────────────────────┐
                           │              ORCHESTRATOR                        │
                           │         (Máquina de estados)                    │
                           └──────────────┬──────────────────────────────────┘
                                          │ SharedContext (estado compartido)
           ┌──────────────────────────────▼──────────────────────────────────┐
           │                    PIPELINE DE ESTADOS                          │
           │                                                                 │
           │  RECEIVED ──► DECOMPOSING ──► ANALYZING ──► ARCHITECTING        │
           │                                                    │            │
           │                              ◄── REVISING ◄── REVIEWING         │
           │                                    (max 2)    │                 │
           │                                               ▼                 │
           │                                          FINALIZING ──► DONE   │
           └─────────────────────────────────────────────────────────────────┘
                │              │               │              │
           ┌────▼────┐   ┌─────▼──────┐  ┌────▼─────┐  ┌────▼──────┐
           │Decomposer│  │Domain Expert│  │Architect │  │ Reviewer  │
           │ Agent   │  │   Agent     │  │  Agent   │  │  Agent    │
           └─────────┘  └────┬────────┘  └──────────┘  └───────────┘
                             │ asyncio.gather()
                    ┌────────┼────────┐
               ┌────▼──┐ ┌──▼───┐ ┌──▼───┐        ┌─────────────┐
               │Domain1│ │Dom. 2│ │Dom. N│         │ Risk Analyst│
               └───────┘ └──────┘ └──────┘         │   Agent     │
                                                    └─────────────┘
```

### Agentes

| Agente | Responsabilidad | Input | Output | Critico |
|--------|----------------|-------|--------|---------|
| **Decomposer** | Descompone el request en subtareas con dominio y prioridad | `original_request` | `subtasks[]` | Sí |
| **Domain Expert** | Analiza cada subtarea en paralelo desde la perspectiva de su dominio | `subtasks[]` | `domain_analyses{}` | Parcial* |
| **Architect** | Sintetiza los análisis en una arquitectura/solución coherente | `domain_analyses{}` | `architecture` | Sí |
| **Reviewer** | Evalúa la solución, puntúa confianza y detecta debilidades | `architecture` + `domain_analyses` | `review` | Sí |
| **Risk Analyst** | Identifica riesgos legales, técnicos y operacionales | `architecture` | `risk_assessment` | No |

> *Si una subtarea falla, se genera un análisis degradado (confidence=0.0) y el pipeline continúa.

### Orquestación

El orchestrator implementa una **máquina de estados explícita** con transiciones deterministas. La única lógica dinámica ocurre tras `REVIEWING`: si `confidence < threshold` Y `revisiones < max`, transiciona a `REVISING` (que vuelve a `ARCHITECTING` con las sugerencias del Reviewer inyectadas en el prompt).

### Persistencia

| Tabla | Contenido |
|-------|-----------|
| `executions` | Una fila por ejecución completa |
| `agent_traces` | Una fila por invocación de agente |
| `llm_cache` | Cache de respuestas LLM (hash SHA-256 del prompt) |
| `review_history` | Historial de revisiones del Reviewer |
| `errors` | Errores registrados durante ejecuciones |

---

## Requisitos

- Python 3.11+
- Docker y Docker Compose (para PostgreSQL + pgAdmin)
- API key de OpenAI, Anthropic o Google Gemini (al menos una)

---

## Instalación y configuración

### 1. Clonar el repositorio

```bash
git clone <url-del-repo>
cd prueba_zebra
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
```

Editar `.env` y añadir al menos una API key:

```env
OPENAI_API_KEY=sk-...          # recomendado
ANTHROPIC_API_KEY=sk-ant-...   # alternativa
```

### 4. Levantar la base de datos

```bash
docker-compose up -d
```

Esto levanta:
- **PostgreSQL 16** en `localhost:5432`
- **pgAdmin 4** en `http://localhost:5050` (credenciales: `admin@zebra.com` / `admin_secret`)

Para verificar que la DB está lista:

```bash
docker-compose ps
```

---

## Ejecución

### Ejecución básica

```bash
python run.py "Quiero lanzar una plataforma SaaS de gestión de turnos para clínicas pequeñas en España"
```

### Con trazas en tiempo real

```bash
python run.py --verbose "Diseñar una arquitectura de microservicios para un e-commerce"
```

### Output en Markdown

```bash
python run.py --output markdown "Crear un sistema de análisis de datos en tiempo real"
```

### Sin base de datos (modo rápido para pruebas)

```bash
python run.py --no-db "Propuesta de MVP para una app de delivery"
```

### Ver historial de ejecuciones

```bash
python run.py --history
```

### Modo interactivo

```bash
python run.py
# Introduce tu solicitud cuando se pida
```

---

## Tests

Los tests no requieren conexión a PostgreSQL ni al LLM (usan mocks).

```bash
# Todos los tests
pytest

# Con verbose
pytest -v

# Un módulo específico
pytest tests/test_orchestrator.py -v
```

---

## Estructura del proyecto

```
prueba_zebra/
├── run.py                        # Entry point CLI
├── pyproject.toml                # Dependencias y configuración
├── docker-compose.yml            # PostgreSQL + pgAdmin
├── .env.example                  # Plantilla de variables de entorno
│
├── src/
│   ├── config.py                 # Settings via pydantic-settings
│   ├── models.py                 # Contratos Pydantic (SharedContext, FinalOutput, etc.)
│   ├── llm.py                    # Wrapper LLM: cache, reintentos, fallback
│   ├── orchestrator.py           # Máquina de estados + loop principal
│   ├── observability.py          # Logging estructurado (structlog)
│   ├── agents/
│   │   ├── base.py               # BaseAgent abstracto
│   │   ├── decomposer.py
│   │   ├── domain_expert.py      # Fan-out paralelo con asyncio.gather
│   │   ├── architect.py
│   │   ├── reviewer.py
│   │   └── risk_analyst.py
│   └── db/
│       ├── models.py             # Modelos SQLAlchemy (5 tablas)
│       ├── connection.py         # Engine async, session factory
│       ├── repository.py         # CRUD
│       └── cache.py              # Cache LLM con hash SHA-256
│
├── tests/
│   ├── test_models.py
│   ├── test_agents.py
│   ├── test_orchestrator.py
│   └── test_llm.py
│
└── examples/
    └── example_output.json       # Ejemplo de output completo
```

---

## Decisiones técnicas y trade-offs

### Sin framework de orquestación (LangChain/LangGraph)

**Decisión:** Implementación directa con Python/asyncio.

**Justificación:** Muestra comprensión real del problema. El flujo es lineal con un único ciclo de revisión, lo que no justifica la complejidad de un grafo. Una máquina de estados explícita es más fácil de depurar, testear y explicar.

**Trade-off:** Más código boilerplate vs. transparencia total del flujo.

### Estado compartido vs. paso de mensajes

**Decisión:** `SharedContext` como objeto Pydantic pasado por referencia entre agentes.

**Justificación:** En un pipeline con dependencias claras (cada agente necesita resultados anteriores), el estado compartido es más legible que un bus de eventos. Pydantic garantiza validación en cada escritura.

**Trade-off:** Acoplamiento implícito entre agentes vs. simplicidad de acceso.

### Fan-out paralelo en Domain Expert

**Decisión:** `asyncio.gather()` para procesar todas las subtareas simultáneamente.

**Justificación:** Las subtareas son independientes entre sí. El paralelismo reduce la latencia total significativamente (N llamadas secuenciales → 1 ronda de llamadas paralelas).

**Trade-off:** Mayor complejidad en manejo de errores parciales (gestionado con `return_exceptions=True`).

### Docker solo para infraestructura

**Decisión:** Docker Compose para PostgreSQL + pgAdmin. La app Python corre nativa.

**Justificación:** La app no tiene dependencias de sistema que requieran containerización. Docker aporta valor real para la DB (sin instalación local, volumen persistente, pgAdmin incluido).

### Cache LLM en PostgreSQL

**Decisión:** Cache de respuestas LLM persistido en la misma base de datos, usando hash SHA-256 del prompt+modelo como key.

**Justificación:** Reduce costes en ejecuciones repetidas (demos, pruebas). El contador de hits permite monitorizar el uso del cache.

**Trade-off:** Las revisiones y las llamadas al Reviewer nunca se cachean (su resultado depende del contexto mutable).

---

## Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | API key de OpenAI | — |
| `ANTHROPIC_API_KEY` | API key de Anthropic | — |
| `GEMINI_API_KEY` | API key de Google Gemini | — |
| `DEFAULT_PROVIDER` | Proveedor por defecto: `openai`, `anthropic` o `gemini` | `openai` |
| `DEFAULT_MODEL` | Modelo principal (depende del proveedor) | `gpt-4o` |
| `FALLBACK_MODEL` | Modelo de fallback | `gpt-4o-mini` |
| `DATABASE_URL` | URL de conexión a PostgreSQL | `postgresql+asyncpg://zebra:zebra_secret@localhost:5432/zebra_agents` |
| `REVIEW_CONFIDENCE_THRESHOLD` | Umbral de confianza para aprobar | `0.7` |
| `MAX_REVISIONS` | Máximo de ciclos de revisión | `2` |
| `MAX_RETRIES` | Reintentos por llamada al LLM | `3` |
| `LOG_LEVEL` | Nivel de logging | `INFO` |

---

## pgAdmin — Acceso a la base de datos

Una vez levantado Docker:

1. Abrir `http://localhost:5050`
2. Login: `admin@zebra.com` / `admin_secret`
3. Añadir servidor:
   - **Host:** `postgres` (o `localhost` si se conecta desde fuera del contenedor)
   - **Port:** `5432`
   - **Database:** `zebra_agents`
   - **Username:** `zebra`
   - **Password:** `zebra_secret`
