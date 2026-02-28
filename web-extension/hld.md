# High-Level Design: AI-Powered Browser Automation Agent

> A vision-enhanced, agent-orchestrated browser automation system (Skyvern-style)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [System Architecture Diagram](#2-system-architecture-diagram)
3. [Component Design](#3-component-design)
   * [Chrome Extension Layer](#31-chrome-extension-layer)
   * [Backend Local Layer](#32-backend-local-layer)
4. [End-to-End Request Flow](#4-end-to-end-request-flow)
5. [Agent Orchestration Loop](#5-agent-orchestration-loop)
6. [DOM vs Vision Strategy](#6-dom-vs-vision-strategy)
7. [Memory System Design](#7-memory-system-design)
8. [Session Lifecycle](#8-session-lifecycle)
9. [Communication Strategy](#9-communication-strategy)
10. [Action Abstraction Layer](#10-action-abstraction-layer)
11. [Observability and Error Handling](#11-observability-and-error-handling)
12. [Key Design Decisions](#12-key-design-decisions)

---

## 1. System Overview

This system enables AI-driven browser automation by combining a **Chrome Extension** (the browser-side agent) with a **Local FastAPI Backend** (the reasoning and orchestration engine). Rather than relying on brittle CSS selectors or hardcoded scripts, the system uses LLM reasoning to understand *intent*, making it resilient to layout changes across websites.

The agent stack is built on **Google Agent Development Kit (ADK)** — Google's official framework for building multi-step, tool-using agents. ADK provides the Planner→Executor→Evaluator loop, built-in `InMemorySessionService` for session state, and a clean tool-calling interface that maps directly onto browser actions.

**Core Design Philosophy:**

* Layout-agnostic automation via structured DOM abstraction + vision fallback
* Agent orchestration powered by **Google ADK** (Planner, Executor, Evaluator, Tool Router)
* Session memory managed by **ADK `InMemorySessionService`** — zero external dependencies for local setup
* Persistent agent loop: Plan → Execute → Evaluate → Replan
* Decoupled LLM reasoning from browser implementation via abstract ADK tool calls

---

## 2. System Architecture Diagram

```mermaid
graph TB
    subgraph BROWSER["User Browser"]
        subgraph EXT["Chrome Extension"]
            CS["Content Script"]
            BSW["Background Service Worker"]
        end
        CS -->|"chrome.runtime"| BSW
        BSW -->|"chrome.runtime"| CS
    end

    subgraph BACKEND["Local FastAPI Backend"]
        GW["WebSocket Endpoint"]

        subgraph ORCH["Agent Orchestrator"]
            PL["Planner"]
            EX["Executor"]
            EV["Evaluator"]
            TR["Tool Router"]
        end

        subgraph LLM_SUB["LLM Orchestration"]
            PB["Prompt Builder"]
            TC["Tool Call Adapter"]
            SM["Streaming Manager"]
        end

        subgraph MEM_SUB["Memory"]
            STM["Session Dict"]
        end

        VIS["Vision LLM Fallback"]
    end

    BSW -->|"WebSocket"| GW
    GW -->|"WebSocket"| BSW
    GW --> PL
    PL --> PB
    PB --> PL
    EV --> PB
    PB --> EV
    EX --> STM
    STM --> EX
    EX --> TR
    EX -.->|"fallback"| VIS
```

---

## 3. Component Design

### 3.1 Chrome Extension Layer

```mermaid
graph LR
    subgraph PAGE["Webpage DOM"]
        DOM["Live DOM"]
    end

    subgraph CS["Content Script"]
        DR["DOM Reader"]
        PO["Page Observer"]
        AE["Action Executor"]
    end

    subgraph BSW_SUB["Background Service Worker"]
        WS["WebSocket Client"]
        SE["Session Manager"]
        MR["Message Router"]
    end

    DOM --> DR
    DOM --> PO
    AE --> DOM
    DR --> MR
    PO --> MR
    MR --> WS
    WS --> MR
    WS --> SE
    SE --> WS
    MR --> AE
```

**Content Script** runs injected inside the webpage. It has direct access to the live DOM and is responsible for:

* Extracting a structured snapshot of visible elements: `{ text, role, bounding_box, clickable, selector }`
* Observing mutations so the backend always has an up-to-date view of the page
* Executing atomic browser actions dispatched from the backend

**Background Service Worker** runs persistently in the extension. It bridges the content script and the backend by:

* Maintaining the WebSocket connection and handling reconnection
* Routing messages to the correct tab when orchestrating multi-tab workflows

---

### 3.2 Backend Local Layer

```mermaid
graph TB
    subgraph GW["FastAPI Gateway"]
        WS_EP["WebSocket /ws"]
        CONN["Connection Manager"]
        ROUTE["Request Router"]
    end

    subgraph ORCH_SUB["Agent Orchestrator"]
        PLAN["Planner"]
        EXEC["Executor"]
        EVAL["Evaluator"]
        PLAN -->|"action"| EXEC
        EXEC -->|"result"| EVAL
        EVAL -->|"replan"| PLAN
    end

    subgraph LLM_LAYER["LLM Orchestration"]
        PB2["Prompt Builder"]
        TCA["Tool Call Adapter"]
        STR["Streaming Manager"]
        PB2 --> TCA --> STR
    end

    subgraph MEM2["Memory"]
        INMEM["Session State"]
        INMEM2["DOM Snapshots"]
        INMEM3["Execution History"]
    end

    ROUTE --> PLAN
    PLAN --> PB2
    PB2 --> PLAN
    EVAL --> PB2
    PB2 --> EVAL
    EXEC --> INMEM
    INMEM --> EXEC
    EXEC --> INMEM2
    EXEC --> INMEM3
```

---

## 4. End-to-End Request Flow

```mermaid
sequenceDiagram
    participant U as User
    participant Ext as Extension
    participant Api as FastAPI
    participant Orch as Orchestrator
    participant Llm as LLM Layer
    participant Mem as Memory

    U->>Ext: Enter goal
    Ext->>Api: WebSocket connect
    Api-->>Ext: Connected
    Ext->>Api: DOM snapshot and goal
    Api->>Orch: Dispatch task
    Orch->>Mem: Load context
    Mem-->>Orch: Context ready

    loop Agent Loop
        Orch->>Llm: Build prompt
        Llm-->>Orch: Action command
        Orch->>Ext: Execute action
        Ext-->>Orch: Result and DOM update
        Orch->>Llm: Evaluate
        Llm-->>Orch: Continue or replan
        Orch->>Mem: Save step
    end

    Orch-->>Ext: Done or Failed
    Ext-->>U: Show result
```

---

## 5. Agent Orchestration Loop

```mermaid
flowchart TD
    START(["User Goal Received"]) --> INIT["Initialize Session\nLoad Memory Context"]
    INIT --> SNAP["Request DOM Snapshot\nfrom Extension"]
    SNAP --> PLAN

    subgraph AGENT_LOOP["Agent Loop"]
        PLAN["PLANNER\nInput: Goal + DOM + Memory\nLLM reasons over context\nOutputs structured action JSON"]
        EXEC["EXECUTOR\nSend action to extension\nWait for execution result\nCapture DOM delta"]
        EVAL["EVALUATOR\nDid expected outcome occur?\nIs goal progress confirmed?\nDecide next move"]

        PLAN --> EXEC --> EVAL
    end

    EVAL -->|"Success: continue"| PLAN
    EVAL -->|"Goal complete"| DONE(["Task Complete"])
    EVAL -->|"Failure: retry"| RETRY
    EVAL -->|"Hard failure"| ESCALATE

    subgraph RETRY_LOGIC["Retry Logic"]
        RETRY["Retry with\nModified Selector"] --> DOM_CHECK{"DOM\nMode Works?"}
        DOM_CHECK -->|"Yes"| PLAN
        DOM_CHECK -->|"No"| CV["Switch to\nVision LLM Mode\nScreenshot"]
        CV --> PLAN
    end

    ESCALATE --> HUMAN["Escalate to\nHuman or Halt"]

    PLAN --> MEM_READ["Read Memory\nIn-process dict"]
    MEM_READ --> PLAN
    EXEC --> MEM_WRITE["Write Step to\nShort-Term Memory"]
```

---

## 6. DOM vs Vision Strategy

```mermaid
flowchart TD
    PAGE["Web Page"] --> DETECT{"Page Type Detection"}

    DETECT -->|"Standard HTML"| EXTRACT
    DETECT -->|"Canvas / Shadow DOM / Obfuscated"| SCREENSHOT

    subgraph DOM_PATH["DOM Mode - Primary"]
        EXTRACT["Extract Visible Elements"]
        STRUCT["Build Structured JSON Snapshot"]
        TEXT_REASON["LLM Reasons over DOM"]
        EXTRACT --> STRUCT --> TEXT_REASON
    end

    subgraph CV_PATH["Vision Mode - Fallback"]
        SCREENSHOT["Capture Screenshot"]
        VISION_LLM["Send to Vision LLM"]
        COORD["Identify Elements by Visual Position"]
        SCREENSHOT --> VISION_LLM --> COORD
    end

    TEXT_REASON -->|"Action determined"| ACTION["Execute Action"]
    COORD -->|"Coordinates identified"| ACTION
    TEXT_REASON -.->|"Selector fails"| SCREENSHOT
```

| Factor | DOM Mode | Vision Mode |
| --- | --- | --- |
| **Speed** | Fast | Slow - screenshot + inference |
| **Cost** | Low | Higher - vision model |
| **Robustness** | Moderate | High |
| **Use case** | Standard pages | Canvas, iframes, shadow DOM |

---

## 7. Memory System Design

> **Agent Stack:** Google ADK (`google-adk`) manages all session memory via its built-in `InMemorySessionService`. No external database or Redis is needed for local setup.

```mermaid
graph TB
    ADK["Google ADK Agent Runner"]

    subgraph SVC["ADK InMemorySessionService"]
        SS["Session Store"]
        SH["Session History"]
        SG["Subgoal State"]
    end

    subgraph CTX["ADK Session Context"]
        SC["Current Goal and URL"]
        SD["Recent DOM Snapshots"]
        SE["Execution Step Log"]
    end

    ADK -->|"get session"| SS
    ADK -->|"read history"| SH
    ADK -->|"read subgoal"| SG
    SS --> SC
    SS --> SD
    SS --> SE
    SE -->|"append step"| ADK
    SH -->|"context injection"| ADK
```

**Google ADK Memory primitives used:**

| ADK Class | Role |
| --- | --- |
| `InMemorySessionService` | Default session store — holds all active session state in-process |
| `Session` | Per-conversation context object passed to every agent turn |
| `Content` / `Part` | Structured message units stored in session history |
| `ToolContext` | Carries session reference into every tool call (browser action) |

> **Note:** For future cloud deployment, swap `InMemorySessionService` with ADK's `DatabaseSessionService` (PostgreSQL) or `VertexAISessionService` — zero code change to agent logic required.

---

## 8. Session Lifecycle

```mermaid
stateDiagram-v2
    [*] --> CREATED : User submits goal

    CREATED --> ACTIVE : Extension connects\nWebSocket established

    ACTIVE --> ACTIVE : Agent loop running\nPlanner to Executor to Evaluator

    ACTIVE --> PAUSED : User requests pause\nOR human approval needed

    PAUSED --> ACTIVE : User resumes\nOR approval granted

    ACTIVE --> COMPLETED : Goal achieved\nAll steps verified

    ACTIVE --> FAILED : Max retries exceeded\nOR unrecoverable error

    PAUSED --> FAILED : Timeout exceeded

    COMPLETED --> [*] : Clear session dict\nRelease memory

    FAILED --> [*] : Log error\nNotify user\nStore debug snapshot
```

---

## 9. Communication Strategy

```mermaid
graph LR
    EXT["Chrome Extension\nBackground Worker"]

    subgraph PROTOCOLS["Communication Protocols"]
        WS["WebSocket\n- Active agent sessions\n- Streaming LLM tokens\n- Real-time DOM updates\n- Action-by-action execution\n- Interruptible plans"]
        REST["REST API\n- Session configuration\n- History and logs\n- Metadata queries"]
    end

    EXT <-->|"persistent bi-directional"| WS
    EXT <-->|"stateless request-response"| REST

    WS --> BACKEND["Agent Orchestrator"]
    REST --> BACKEND
```

**Why WebSocket for active sessions?** The agent loop is inherently interactive — it streams LLM tokens, sends actions one-by-one, and must be interruptible if the user pauses or corrects the agent mid-task.

---

## 10. Action Abstraction Layer

```mermaid
graph TD
    LLM_OUT["LLM Tool Call Output"]

    subgraph TOOLS["Abstract Action Tools"]
        T1["CLICK"]
        T2["TYPE"]
        T3["SCROLL"]
        T4["NAVIGATE"]
        T5["EXTRACT"]
        T6["WAIT_FOR"]
    end

    subgraph EXECUTOR["Executor and Tool Router"]
        MAP["Tool to Command Mapper"]
        VALID["Command Validator"]
    end

    CS2["Content Script - Browser APIs"]
    RESULT["Execution Result"]

    LLM_OUT --> T1
    LLM_OUT --> T2
    LLM_OUT --> T3
    LLM_OUT --> T4
    LLM_OUT --> T5
    LLM_OUT --> T6
    T1 --> MAP
    T2 --> MAP
    T3 --> MAP
    T4 --> MAP
    T5 --> MAP
    T6 --> MAP
    MAP --> VALID
    VALID --> CS2
    CS2 --> RESULT
    RESULT --> MAP
```

The action abstraction layer **decouples LLM reasoning from browser implementation**. The Planner outputs generic tool calls — the Executor translates them to browser-specific commands.

---

## 11. Observability and Error Handling

```mermaid
graph TB
    AGENT["Running Agent"]
    DASHBOARD["Python Logger and Console Output"]

    subgraph SIGNALS["Telemetry Signals"]
        LOGS["Step-by-step Trace Logs"]
        CONSOLE["Agent Loop Status Output"]
    end

    subgraph ERROR_HANDLING["Error and Retry Strategy"]
        ERR1["Selector Not Found"]
        ERR2["Action Failed"]
        ERR3["LLM Timeout"]
        ERR4["WebSocket Disconnect"]
        ERR5["Unrecoverable Error"]
    end

    AGENT --> LOGS
    AGENT --> CONSOLE
    AGENT --> ERR1
    AGENT --> ERR2
    AGENT --> ERR3
    AGENT --> ERR4
    AGENT --> ERR5
    LOGS --> DASHBOARD
    CONSOLE --> DASHBOARD
    ERR1 -->|"retry"| AGENT
    ERR2 -->|"replan"| AGENT
    ERR3 -->|"retry"| AGENT
    ERR4 -->|"reconnect"| AGENT
    ERR5 -->|"halt"| DASHBOARD
```

---

## 12. Key Design Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| **Agent framework** | **Google ADK** (`google-adk`) | Official Google agent SDK — built-in Planner/Executor/Evaluator loop, tool calling, session service |
| **Extension to Backend protocol** | WebSocket | Bi-directional streaming, interruptible, low-latency for agent loops |
| **Primary page understanding** | Structured DOM abstraction | Fast, cheap, sufficient for 80%+ of standard web pages |
| **Vision fallback** | Screenshot + Vision LLM | Handles canvas, shadow DOM, obfuscated elements robustly |
| **Agent architecture** | ADK Planner - Executor - Evaluator loop | ADK enforces step verification before continuing; prevents runaway loops |
| **Action schema** | ADK Tool definitions (`@tool`) | ADK tool decorator maps LLM function calls directly to browser actions |
| **Short-term memory** | ADK `InMemorySessionService` | Zero-dependency in-process session store; drop-in swap to DB for production |
| **Long-term memory** | Not in local setup | Swap to ADK `DatabaseSessionService` or `VertexAISessionService` for cloud |
| **Backend** | Local FastAPI + uvicorn | Zero infra cost, simple to run, hosts ADK runner and WebSocket endpoint |
| **Async tasks** | asyncio + ADK async runner | ADK natively supports async agent execution via `Runner.run_async()` |
| **Observability** | ADK event stream + Python logging | ADK emits structured events per step; captures tool calls, LLM responses, errors |

---

## Appendix: Skyvern Extensions to Base Architecture

```mermaid
graph LR
    subgraph BASE["Base Architecture"]
        B1["DOM-first understanding"]
        B2["Single agent loop"]
        B3["Extension-based browser control"]
        B4["Task = single goal"]
    end

    subgraph SKYVERN["Skyvern Enhancements"]
        S1["Vision-primary understanding\nlayout-agnostic by default"]
        S2["Specialized sub-agents\nNav, Auth, Extract, Detect"]
        S3["Playwright SDK integration\npage.act, page.extract,\npage.validate"]
        S4["Workflow chaining\nmulti-task orchestration"]
        S5["Live viewport streaming\nreal-time human oversight"]
        S6["CAPTCHA and 2FA handling\ndedicated sub-agent"]
    end

    B1 -->|"evolved to"| S1
    B2 -->|"evolved to"| S2
    B3 -->|"evolved to"| S3
    B4 -->|"evolved to"| S4
```

---

*Document version 3.0 — Local FastAPI + Google ADK setup. Covers system architecture, component design, ADK-powered agent orchestration, ADK InMemorySessionService, session lifecycle, and observability for an AI-powered browser automation platform.*
