# Frontend Architecture – High-Level Design (HLD)

**GHMC AI-Enabled Digital Services Platform**
**Version:** 1.0 | **Date:** 2026-02-27 | **Status:** Draft / Reference

---

## 1. Overview

The frontend serves as the citizen/official-facing layer embedded within the **GHMC web portal**. It provides:

- **Chat Widget** – Multilingual, voice-enabled conversational interface
- **Form Assistance UI** – Guided form-filling with document upload, live preview, and step tracking
- **Analytics Dashboard** – Admin/official view for query trends and system metrics

The frontend must be **responsive**, **WCAG 2.1/2.2 compliant**, and **embeddable** within the existing GHMC website.

---

## 2. Design Principles

| Principle | Description |
|---|---|
| **Embeddable** | Chat widget and form UI can be injected into any GHMC page via `<script>` tag or iframe |
| **Responsive** | Desktop, tablet, and mobile (min 320px width) |
| **Accessible** | WCAG 2.1 AA minimum; screen reader support, keyboard navigation, high contrast |
| **Multilingual** | UI chrome + content in Telugu, Hindi, Urdu, English; RTL support for Urdu |
| **Progressive** | Core functionality works without JS-heavy features; graceful degradation |
| **Real-Time** | WebSocket-driven streaming for chat and form-fill progress |

---

## 3. Frontend Architecture Diagram

```mermaid
graph TB
    subgraph "GHMC Portal (Host Page)"
        EMBED[Embed Script / iframe]
    end

    subgraph "Frontend Application"
        direction TB
        APP[App Shell]

        subgraph "Core Modules"
            CW[Chat Widget Module]
            FFM[Form Assistance Module]
            AD[Analytics Dashboard Module]
        end

        subgraph "Shared Services"
            I18N[i18n Service<br/>Telugu, Hindi, Urdu, English]
            VOICE[Voice I/O Manager<br/>ASR + TTS]
            AUTH_UI[Auth Manager<br/>JWT handling]
            WS[WebSocket Manager]
            THEME[Theme & Accessibility<br/>Manager]
            STATE[State Manager]
        end

        subgraph "UI Component Library"
            BTN[Buttons & Controls]
            FORMS[Form Components]
            MODAL[Modals & Overlays]
            CHAT_UI[Chat Bubble & Messages]
            UPLOAD[File Upload & Preview]
            PROGRESS[Progress Indicators]
            A11Y[Accessibility Primitives<br/>ARIA, Focus Trap, Skip Links]
        end
    end

    subgraph "Backend APIs"
        REST[REST API]
        WSS[WebSocket API]
        VOICE_API[Voice Streaming API]
    end

    EMBED --> APP
    APP --> CW
    APP --> FFM
    APP --> AD
    CW --> I18N
    CW --> VOICE
    CW --> WS
    FFM --> I18N
    FFM --> VOICE
    FFM --> WS
    FFM --> UPLOAD
    AD --> REST
    CW --> REST
    CW --> WSS
    FFM --> REST
    FFM --> WSS
    VOICE --> VOICE_API
    AUTH_UI --> REST
```

---

## 4. Module Breakdown

### 4.1 Chat Widget Module

The primary citizen interaction point – a floating chat bubble that expands into a full conversational interface.

```mermaid
stateDiagram-v2
    [*] --> Collapsed : Page load
    Collapsed --> Expanded : Click chat bubble
    Expanded --> Collapsed : Minimize

    state Expanded {
        [*] --> LanguageSelect
        LanguageSelect --> TextChat
        TextChat --> VoiceChat : Mic button
        VoiceChat --> TextChat : Stop recording
        TextChat --> FormHandoff : Agent suggests form
        FormHandoff --> FormAssistance : User accepts
    }
```

**Key features:**

| Feature | Implementation |
|---|---|
| **Floating bubble** | Fixed-position widget, z-index above host page |
| **Message types** | Text, rich cards (links, buttons), image previews, form cards |
| **Voice input** | Web Speech API / MediaRecorder → send audio to ASR backend |
| **Voice output** | Backend TTS audio streamed and played via Web Audio API |
| **Typing indicator** | WebSocket-driven real-time streaming of LLM response |
| **Language switcher** | Dropdown in header; persists to localStorage |
| **Conversation history** | Scrollable message list; lazy-loaded from API |

### 4.2 Form Assistance Module

Guides citizens through document upload, data verification, and real-time form-fill preview.

```mermaid
flowchart TD
    A[Form Start] --> B[Select Form Type]
    B --> C[Upload Documents<br/>Aadhaar, PAN, etc.]
    C --> D[OCR Processing<br/>Show extracted data]
    D --> E{Data Complete?}
    E -->|No| F[Conversational Q&A<br/>Collect missing fields]
    F --> E
    E -->|Yes| G[Confirm Data]
    G --> H[Live Form Fill Preview<br/>Playwright screenshots streamed]
    H --> I[Step Progress Tracker]
    I --> J{All Steps Done?}
    J -->|No| H
    J -->|Yes| K[Final Review Screen]
    K --> L[Citizen Confirms]
    L --> M[Submit & Show Reference Number]
```

**Key features:**

| Feature | Implementation |
|---|---|
| **Form type selector** | Card-based grid of available GHMC forms |
| **Document upload** | Drag-and-drop zone; image preview; multi-file support |
| **OCR result display** | Editable table showing extracted fields; citizen can correct |
| **Data collection chat** | Inline mini-chat for collecting missing fields conversationally |
| **Live form preview** | Streamed screenshots from Playwright browser via WebSocket |
| **Step tracker** | Vertical stepper showing: Navigate → Fill Details → Upload Docs → Submit |
| **Final review** | Side-by-side: filled form screenshot + extracted data summary |
| **Confirmation** | Submit button + reference number display + download receipt |

### 4.3 Analytics Dashboard Module

For GHMC officials and admins only (role-gated).

| Widget | Data Shown |
|---|---|
| **Query Trends** | Time-series chart of chat queries per day/week |
| **Language Distribution** | Pie chart of queries by language |
| **Top Services** | Bar chart of most-requested services/forms |
| **Resolution Rate** | % of queries resolved without human handoff |
| **Form Completion Rate** | % of form sessions that reached submission |
| **Active Sessions** | Real-time count of active chat/form sessions |

---

## 5. Technology Choices

| Layer | Technology | Rationale |
|---|---|---|
| **Framework** | React 18+ / Next.js | Component-based, large ecosystem, SSR for SEO |
| **State Management** | Zustand / React Context | Lightweight, sufficient for widget-scoped state |
| **Styling** | CSS Modules + Design Tokens | Scoped styles that won't leak into GHMC host page |
| **i18n** | react-i18next | Mature, supports dynamic language switching, RTL |
| **WebSocket** | Native WebSocket + reconnect wrapper | Real-time chat and form-fill streaming |
| **Voice** | Web Speech API + MediaRecorder | Browser-native ASR fallback; MediaRecorder for backend ASR |
| **Accessibility** | Radix UI primitives + custom ARIA | WCAG 2.1 AA compliant components |
| **Charts** | Recharts / Chart.js | Analytics dashboard visualizations |
| **Build** | Vite | Fast builds; outputs single embeddable bundle |
| **Embed** | Web Component wrapper or iframe | Isolation from host page CSS/JS |

---

## 6. Embedding Strategy

The frontend must be embeddable into the existing GHMC website without conflicts:

```mermaid
graph LR
    subgraph "GHMC Website"
        HP[Host Page HTML/CSS/JS]
        SC["&lt;script src='ghmc-ai-widget.js'&gt;"]
    end

    subgraph "Option A: Shadow DOM Web Component"
        WC[ghmc-ai-chatbot<br/>Custom Element]
        SHADOW[Shadow Root<br/>Encapsulated CSS]
        REACT[React App]
    end

    subgraph "Option B: iframe"
        IF[iframe src='widget.ghmc.ai']
        CROSS[postMessage API<br/>for communication]
    end

    SC --> WC
    WC --> SHADOW --> REACT
    SC -.-> IF
    IF -.-> CROSS
```

| Option | Pros | Cons |
|---|---|---|
| **Shadow DOM** | No CSS leakage, single page load, direct DOM access | Slightly complex setup |
| **iframe** | Complete isolation, simpler | Cross-origin issues, separate load, harder auth sharing |

**Recommendation:** Shadow DOM Web Component for the chat widget; iframe only if strict isolation is required.

---

## 7. Voice I/O Flow

```mermaid
sequenceDiagram
    participant U as Citizen (Browser)
    participant MIC as Microphone API
    participant WS as WebSocket
    participant ASR as ASR Service
    participant AGENT as Backend Agent
    participant TTS as TTS Service
    participant SPK as Speaker (Audio API)

    U->>MIC: Press mic button
    MIC->>WS: Stream audio chunks
    WS->>ASR: Audio stream
    ASR->>AGENT: Transcribed text
    AGENT->>AGENT: Process (chat/form)
    AGENT->>TTS: Response text
    TTS->>WS: Audio stream
    WS->>SPK: Play audio
    SPK->>U: Hear response
```

---

## 8. Accessibility Requirements (WCAG 2.1 AA)

| Requirement | Implementation |
|---|---|
| **Keyboard Navigation** | All interactive elements focusable; tab order logical; Enter/Space to activate |
| **Screen Reader** | ARIA labels, live regions for chat messages, role attributes |
| **Color Contrast** | Minimum 4.5:1 for text; 3:1 for large text |
| **Focus Indicators** | Visible focus rings on all interactive elements |
| **Text Resize** | UI works at 200% zoom without horizontal scrolling |
| **RTL Support** | Urdu content rendered right-to-left; `dir="rtl"` attribute |
| **Skip Links** | "Skip to chat" / "Skip to form" links for keyboard users |
| **Motion** | Respect `prefers-reduced-motion` media query |

---

## 9. Responsive Breakpoints

| Breakpoint | Width | Layout |
|---|---|---|
| **Mobile** | < 640px | Chat: fullscreen overlay; Form: single-column stack |
| **Tablet** | 640px – 1024px | Chat: side panel (40% width); Form: two-column |
| **Desktop** | > 1024px | Chat: floating panel (400px); Form: three-column with sidebar |

---

## 10. Frontend ↔ Backend Integration

| Interaction | Protocol | Endpoint |
|---|---|---|
| Chat message | WebSocket | `WS /api/v1/chat/stream` |
| Form start | REST | `POST /api/v1/form/start` |
| Document upload | REST (multipart) | `POST /api/v1/form/{id}/upload-docs` |
| Form-fill progress | WebSocket | `WS /api/v1/form/{id}/progress` |
| Form submit | REST | `POST /api/v1/form/{id}/confirm` |
| Voice stream | WebSocket | `WS /api/v1/voice/stream` |
| Analytics data | REST | `GET /api/v1/analytics/...` |
| Auth | REST | `POST /api/v1/auth/login`, `/refresh` |
