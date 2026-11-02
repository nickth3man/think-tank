# Organizing a small LangGraph + FastAPI repo — what the primary sources say

Research date: 2026-11-01. Subject repo: `/Users/nicolas/Documents/github/think-tank`
(`think_tank/` package, `think_tank/agents/`, `main.py` CLI, `app.py` FastAPI + ~2.9k-line
inline frontend string).

**How to read this.** Every claim below is traced to the document that owns it — official
LangGraph/LangChain, packaging.python.org (PyPA), setuptools, docs.python.org, FastAPI, uv.
Where the owning document does not address a question, that is stated explicitly under
"Where the docs are silent" rather than filled in by inference. Passages marked
**Derived** apply the sources to *this* repo; they are conclusions, not citations.

## Sources

| Claim area | Owning document |
|---|---|
| Graph = state + nodes + edges; nodes are plain functions; state schema is a `TypedDict` | <https://docs.langchain.com/oss/python/langgraph/graph-api> |
| Workflow decomposition into nodes; what belongs in state | <https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph> |
| Canonical Python app tree (`my_agent/agent.py`, `utils/{nodes,state,tools}.py`) | <https://docs.langchain.com/langsmith/application-structure> |
| Subgraphs as the multi-agent composition primitive | <https://docs.langchain.com/oss/python/langgraph/use-subgraphs> |
| Multi-agent pattern catalogue (subagents / handoffs / router / custom workflow) | <https://docs.langchain.com/oss/python/langchain/multi-agent> |
| src vs flat layout tradeoffs | <https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/> |
| `[project.scripts]`, `[project.gui-scripts]` | <https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#creating-executable-scripts> |
| Entry-point spec (object reference, one command per name) | <https://packaging.python.org/en/latest/specifications/entry-points/> |
| CLI packaging walkthrough (`src/`, `cli.py`, `__main__.py`) | <https://packaging.python.org/en/latest/guides/creating-command-line-tools/> |
| FastAPI `APIRouter`, multi-file layout, `entrypoint` | <https://fastapi.tiangolo.com/tutorial/bigger-applications/> |
| FastAPI `StaticFiles` / `app.frontend()` | <https://fastapi.tiangolo.com/tutorial/static-files/>, <https://fastapi.tiangolo.com/tutorial/frontend/> |
| FastAPI `HTMLResponse`; inline HTML framed as non-production | <https://fastapi.tiangolo.com/advanced/custom-response/#html-response>, <https://fastapi.tiangolo.com/advanced/websockets/> |
| Package resource reading | <https://docs.python.org/3/library/importlib.resources.html> |
| Package data inclusion (setuptools) | <https://setuptools.pypa.io/en/latest/userguide/datafiles.html> |
| uv project layout, `[project.scripts]`, module root, wheel data rules | <https://docs.astral.sh/uv/concepts/projects/init/>, <https://docs.astral.sh/uv/concepts/build-backend/> |
| uv workspaces | <https://docs.astral.sh/uv/concepts/projects/workspaces/> |
| LangGraph deploy/config (`langgraph.json`, `http.app`) | <https://docs.langchain.com/langsmith/cli>, <https://docs.langchain.com/langsmith/custom-routes> |

## 1. LangGraph: how the official docs structure a multi-agent project

**State is defined once, shared, and is a plain schema.** "The first thing you do when you
define a graph is define the `State` of the graph"; the schema "will be the input schema to
all `Nodes` and `Edges`", and the documented form is a `TypedDict` (a `dataclass` when defaults
are needed, Pydantic only when recursive validation is required)
([graph-api#state](https://docs.langchain.com/oss/python/langgraph/graph-api#state)).

**Nodes are functions.** "`Nodes` and `Edges` are nothing more than functions"; the overview
compresses it to "nodes do the work, edges tell what to do next"
([graph-api#graphs](https://docs.langchain.com/oss/python/langgraph/graph-api#graphs)).
Design guidance adds the placement rule for state content: "your state should store raw data,
not formatted text. Format prompts inside nodes when you need them"
([thinking-in-langgraph#step-3-design-your-state](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph#step-3-design-your-state)).

**File layout: graph construction lives in its own module, separate from nodes and state.**
The deployment docs give the canonical tree — the comments are the entirety of the official
placement guidance ([application-structure#file-structure](https://docs.langchain.com/langsmith/application-structure#file-structure)):

```
my_agent/
├── utils/
│   ├── tools.py      # tools for your graph
│   ├── nodes.py      # node functions for your graph
│   └── state.py      # state definition of your graph
├── __init__.py
└── agent.py          # code for constructing your graph
```

That is: node functions in `nodes.py`, the state schema in `state.py`, graph assembly in a
module named for the agent (`agent.py`). Nothing on that page prescribes one file per node, an
`agents/` subpackage, or where a router/arbiter node belongs.

**Construction is a function returning a compiled graph.** `StateGraph` is built, nodes and
edges added, then `.compile()`d — "You **MUST** compile your graph before you can use it"
([graph-api#compiling-your-graph](https://docs.langchain.com/oss/python/langgraph/graph-api#compiling-your-graph)).
`langgraph.json` accepts either a `CompiledStateGraph` variable or a factory returning one
(`./your_package/your_file.py:make_graph`)
([cli#configuration-file](https://docs.langchain.com/langsmith/cli#configuration-file)).

**Multi-agent composition = subgraphs, with an explicit state decision.** "A subgraph is a graph
that is used as a [node] in another graph", listed for "Building multi-agent systems", reuse, and
"Distributing development: … as long as the subgraph interface (the input and output schemas) is
respected". Two documented modes: shared state keys (pass the compiled subgraph directly to
`add_node`) and differing schemas (invoke inside a wrapper node that maps state in and out)
([use-subgraphs#define-subgraph-communication](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#define-subgraph-communication)).

**Derived for think-tank.** `think_tank/state.py`, `think_tank/graph.py` and
`think_tank/agents/*.py` already match the sanctioned shape. The arbiter was originally outside
`agents/`; it now lives at `think_tank/agents/arbiter.py` alongside the other four nodes. The docs
neither require nor forbid either placement — `utils/nodes.py` is an example, not a rule — so this
was a consistency choice, not a compliance one. Splitting per agent is consistent with the
docs' own rationale that multi-agent exists partly for "Distributed development"
([multi-agent#why-multi-agent](https://docs.langchain.com/oss/python/langchain/multi-agent#why-multi-agent)).

## 2. Python packaging: src vs flat layout, `main.py` vs `console_scripts`

**The two layouts differ in behaviour; PyPA declines to rank them.** The page is titled "src
layout vs flat layout" and lists behavioural differences only
([src-layout-vs-flat-layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)):

- "The src layout requires installation of the project to be able to run its code, and the flat
  layout does not."
- "The src layout helps prevent accidental usage of the in-development copy of the code" — because
  "the Python interpreter includes the current working directory as the first item on the import
  path", a same-named package in the CWD shadows the installed one, "which could result in files
  not being included in a distribution".
- "The src layout helps enforce that an editable installation is only able to import files that
  were meant to be importable" — the flat layout puts `README.md`, `setup.py`, `noxfile.py` on the
  import path under path-config editable installs.

PyPA has no sanctioned single answer: its own CLI guide carries an open editorial TODO —
"Advise on the optimal structure of a Python package in another guide or discussion and link to it
here" ([creating-command-line-tools#creating-the-package](https://packaging.python.org/en/latest/guides/creating-command-line-tools/#creating-the-package)).

**A top-level `main.py` is sanctioned only for unpackaged projects.** PyPA's CLI walkthrough uses
`src/greetings/{cli.py,greet.py,__init__.py,__main__.py}` and states that under src layout "a
command-line interface can not be run directly from the source tree, but requires installation of
the package" ([src-layout-vs-flat-layout#running-a-command-line-interface-from-source-with-src-layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/#running-a-command-line-interface-from-source-with-src-layout)).
uv emits a root `main.py` exactly when packaging is declined: `uv init --no-package` produces "a
`pyproject.toml`, a sample file (`main.py`), a readme, and a Python version pin file"
([uv init#creating-a-project-without-a-build-system](https://docs.astral.sh/uv/concepts/projects/init/#creating-a-project-without-a-build-system)).
Its packaged-application template instead writes `src/<name>/` plus
`[project.scripts] example-app = "example_app:main"`
([uv init#applications](https://docs.astral.sh/uv/concepts/projects/init/#applications)).

**`console_scripts` is the sanctioned way to expose a command.** Declaring
`[project.scripts] spam-cli = "spam:main_cli"` yields a command equivalent to "`import sys; from
spam import main_cli; sys.exit(main_cli())`"; the spec defines the object reference as
`importable.module[:object.attr]` and notes that for console scripts "the name of the entry point
is the command that will be used to launch it"
([writing-pyproject-toml#creating-executable-scripts](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/#creating-executable-scripts),
[entry-points#use-for-scripts](https://packaging.python.org/en/latest/specifications/entry-points/#use-for-scripts)).
`[project.gui-scripts]` differs "only … on Windows".

**Derived for think-tank.** `pyproject.toml` declares neither `[build-system]` nor
`[project.scripts]`, so the project is not installable as a package today; `python main.py` and
`python app.py` work only because the interpreter puts the repo root on `sys.path`. Adopting
src-layout therefore *forces* the entry-point work, since installation becomes mandatory; staying
flat keeps `python main.py` valid but retains the CWD-shadowing hazard PyPA names.

## 3. FastAPI: larger applications and frontends

**Split by router.** FastAPI's multi-file guide defines
`app/{__init__.py,main.py,dependencies.py,routers/{items.py,users.py},internal/admin.py}`, where
each router module owns an `APIRouter` and `app/main.py` only assembles: "This will be the main
file in your application that ties everything together. And as most of your logic will now live in
its own specific module, the main file will be quite simple" — via
`app.include_router(users.router)`
([bigger-applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/)). Shared
dependencies get their own module (`app/dependencies.py`); `prefix`, `tags`, `responses`,
`dependencies` attach at `APIRouter(...)` or `include_router(...)` level. Routers are not mounted:
"FastAPI keeps the original routers and path operations active, and combines the router prefixes,
dependencies, tags, responses, and other metadata when handling requests and generating OpenAPI" —
so they still appear in the docs, unlike `app.mount`.

**The app object gets a declared entry point.** "As your FastAPI `app` object lives in
`app/main.py`, you can configure the `entrypoint` in your `pyproject.toml`":
`[tool.fastapi] entrypoint = "app.main:app"`, "equivalent to importing … `from app.main import
app`", recommended over passing a path on the command line because other tools (the VS Code
extension, FastAPI Cloud) must find it
([bigger-applications#configure-the-entrypoint-in-pyproject-toml](https://fastapi.tiangolo.com/tutorial/bigger-applications/#configure-the-entrypoint-in-pyproject-toml)).

**A frontend is a directory, not a string.** `app.frontend("/", directory="dist")` serves a build
output directory and — unlike `app.mount` — gives path operations priority: "FastAPI checks *path
operations* first. The frontend files are checked only if no normal route matched, so your API
won't be affected." `fallback="index.html"` covers SPA client-side routing; `app.frontend()`
"serves files already generated by your frontend build" and "does not run server-side rendering"
([frontend](https://fastapi.tiangolo.com/tutorial/frontend/)). `StaticFiles` is the primitive it
wraps ([static-files](https://fastapi.tiangolo.com/tutorial/static-files/)).

**Inline HTML is documented but explicitly framed as throwaway.** `HTMLResponse` examples return
an HTML literal from a path operation
([custom-response#html-response](https://fastapi.tiangolo.com/advanced/custom-response/#html-response)),
but the WebSockets page says of exactly that technique: "we'll use a very simple HTML document
with some JavaScript, all inside a long string. This, of course, is not optimal and you wouldn't
use it for production" ([websockets](https://fastapi.tiangolo.com/advanced/websockets/)).

**Derived for think-tank.** This was the repo's largest deviation and has been corrected. `app.py`
originally inverted FastAPI's arrangement: `INDEX_HTML` occupied lines 37–2454 (about 2 418 of the
file's 2 916 lines) and preceded the Python, with `app = FastAPI(...)` at line 2733 and three
`@app.get` (`/`, `/healthz`, `/profile`) plus one `@app.websocket("/observe")` decorator. Now the
frontend is `web/index.html` and the Python is `think_tank/dashboard/server.py` (222 lines), with
`app.py` reduced to a 23-line alias exporting `app`. Note the caveat under "Where the docs are
silent": the frontend sits at the repo root, outside the package, because the project is not
packaged — if it ever ships as a distribution, `web/index.html` must move inside the module root
and be read via `importlib.resources`.

## 4. Shipping a frontend bundle inside a Python package

**Read at runtime through `importlib.resources`, not `__file__` paths.** `files(anchor)` returns a
`Traversable` for the package and its resources; `read_text(anchor, "x.html")` is "roughly
equivalent to `files(anchor).joinpath(*path_names).read_text(encoding=encoding)`"; and "Resources
and packages **do not** have to exist as physical files and directories on the file system: for
example, a package and its resources can be imported from a zip file". Reach for `as_file()` only
when a real filesystem path is required
([importlib.resources](https://docs.python.org/3/library/importlib.resources.html)).

**Getting the file into the wheel is a build-backend setting.**

- setuptools: `[tool.setuptools.package-data] mypkg = ["*.txt", "*.rst"]`; or `include-package-data`
  (default `true` under `pyproject.toml`), which takes non-`.py` files inside the package that
  satisfy MANIFEST.in / VCS-tracking conditions
  ([setuptools datafiles](https://setuptools.pypa.io/en/latest/userguide/datafiles.html)).
- `uv_build`: no include list for wheels — "There must only be one top level module, and all data
  files must either be under the module root or in the appropriate data directory. Most packages
  store small data in the module root alongside the source code." Non-`.py` files under the module
  root ship automatically; `tool.uv.build-backend.data` is for `sys.prefix`-relative placement
  ([uv build-backend#file-inclusion-and-exclusion](https://docs.astral.sh/uv/concepts/build-backend/#file-inclusion-and-exclusion)).

**Docs are silent on "the frontend as one giant Python string literal".** No official page
recommends it; the two available framings are `HTMLResponse` snippets ("not optimal … not for
production") and `app.frontend(directory=...)`. The only stated constraint on *location* is uv's
"store small data in the module root alongside the source code", which points at
`think_tank/web/index.html` rather than a file outside the package.

## 5. uv project layout

**src + build system + scripts is the default for anything packaged.** "uv prefers to define a
build system and place source files in a dedicated `src/<project_name>/` directory. Defining a
build system allows use of various Python packaging features, such as adding command-line entry
points, and avoids common points of confusion with the Python import system." Applications (web
servers, scripts, CLIs) are the default template and get `src/example_app/__init__.py`,
`[project.scripts] example-app = "example_app:main"`, and `build-backend = "uv_build"`
([uv init](https://docs.astral.sh/uv/concepts/projects/init/)).

**No build system ⇒ no installation ⇒ flat `main.py`.** The config page states the rule directly:
"If a build system is defined, uv will build and install the project into the project environment",
and lists "You probably need a package if you want to: Add commands to the project / Distribute the
project to others / Use a `src` and `test` layout / Write a library", versus "You probably *do not*
need a package if you are: Writing scripts / Building a simple application / Using a flat layout"
([uv config#project-packaging](https://docs.astral.sh/uv/concepts/projects/config/#project-packaging)).

**A package exposes exactly one root module.** `uv_build` expects "a single root module … at
`src/<package_name>/__init__.py`", normalised from the distribution name; `module-name` /
`module-root` adjust it. Multiple top-level modules are possible but "we do not recommend this
structure (i.e., you should use a workspace with multiple packages instead)"
([uv build-backend#modules](https://docs.astral.sh/uv/concepts/build-backend/#modules)). For truly
separate distributions workspaces exist — but "Workspaces are *not* suited for cases in which
members have conflicting requirements, or desire a separate virtual environment for each member"
([uv workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/)).

**Entry-point tables require a build system**: "Using the entry point tables requires a build
system to be defined"
([uv config#entry-points](https://docs.astral.sh/uv/concepts/projects/config/#entry-points)).

**Derived for think-tank.** The repo sits on uv's "you probably *do not* need a package …
Building a simple application" branch: `uv.lock` present, `.venv` managed, no `[build-system]`, no
scripts. Moving to src-layout is not cosmetic — it flips the project into uv's packaged branch and
obliges `[build-system]`, a normalised `think_tank` module under `src/`, and `[project.scripts]`.

## 6. CLI entry point vs web entry point

**No consulted document addresses "CLI and web server in one repo" as a design question.** PyPA's
layout/CLI guides, uv `init`/`config`, FastAPI bigger-applications, and LangGraph
application-structure contain no guidance on separating a CLI entry from a web entry. What the
sources do establish:

- Multiple commands are normal and free: `[project.scripts]` is a table, each name becoming an
  installed command, and "Within a distribution, entry point names should be unique"
  ([entry-points#data-model](https://packaging.python.org/en/latest/specifications/entry-points/#data-model)).
- Each command must resolve to a *callable*, so a server launcher has to be a function calling
  `uvicorn.run(...)`; the `FastAPI` app object itself is exposed through a different channel —
  `[tool.fastapi] entrypoint`, or `module:app` for ASGI servers and `langgraph.json`'s `http.app`
  ([bigger-applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/),
  [custom-routes](https://docs.langchain.com/langsmith/custom-routes)).
- PyPA's CLI example keeps the CLI in `src/greetings/cli.py` with a one-line `__main__.py`
  delegating to it — the command is a thin module inside the package, not a root script
  ([creating-command-line-tools](https://packaging.python.org/en/latest/guides/creating-command-line-tools/)).

**Derived for think-tank.** Run setup is now shared rather than duplicated: `think_tank/runner.py`
owns the convergence defaults, the credential check, and seeding (sync for the CLI, `async ...`
for the websocket handler, because seeding embeds every document and must not block the event
loop). Both `main.py` (155 lines) and `app.py` (23 lines) are adapters over it. The sources support
two `[project.scripts]` entries (e.g. `think-tank = "think_tank.cli:main"` and
`think-tank-dashboard = "think_tank.web:serve"`), or one console script plus the ASGI convention
`uvicorn think_tank.web:app`. They do not support keeping
both entry points as root-level `main.py` / `app.py` once the project is packaged: root modules
fall outside the single module root that `uv_build` packages, and flat root scripts are precisely
what src-layout exists to rule out.

## 7. Where the docs are silent

| Question | Status |
|---|---|
| Optimal package structure, in general | PyPA says it intends to write this guide; the TODO is still in the CLI guide ([link](https://packaging.python.org/en/latest/guides/creating-command-line-tools/#creating-the-package)) |
| One-file-per-node vs a flat `nodes.py` | LangGraph shows only the flat `utils/nodes.py` example; no rule stated |
| Where a router/arbiter node lives | Not addressed |
| Whether a root `main.py` may coexist with a package **in a packaged project** | Not addressed; uv's `main.py` template is the unpackaged branch only |
| Embedding HTML/JS as a Python string literal | Not addressed by any official page; the nearest framing calls the technique non-production |
| Serving a frontend from inside the package vs a repo-root `dist/` | FastAPI shows only `directory="dist"` beside the project; uv states only the general module-root data rule — so think-tank's repo-root `web/index.html` is the sanctioned shape only while the project stays unpackaged |
| CLI entry + web entry in one repository | Not addressed anywhere consulted |
| src vs flat for an application specifically (not a library) | PyPA lists tradeoffs only; uv's `--no-package` template implies flat for unpackaged apps without arguing for it |
