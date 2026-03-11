# Phase 1 Chat UX Redesign

## Scope

This document defines the Phase 1 frontend redesign for the current ResearchAgent UI.

Phase 1 goals:

- analyze the existing component structure
- redesign the run experience into a ChatGPT-style chat workspace
- separate chat from configuration
- keep the Phase 1 surface compatible with the current backend contract where possible

Phase 1 does not remove backend fields yet. That lands in Phase 2 and Phase 3.

## Current Frontend Structure

### App shell

- `frontend/src/App.tsx`
  - single-page shell
  - left sidebar switches between nine tabs
  - main content renders one tab at a time

### Global state

- `frontend/src/store.tsx`
  - stores `projectConfig`
  - stores `runOverrides`
  - stores `runLogs`
  - stores provider model catalogs
  - persists config directly on each field edit through `/api/config`
  - starts runs through `/api/run`

### Current run experience

- `frontend/src/components/tabs/RunTab.tsx`
  - mixes prompt entry, run controls, runtime overrides, model selection, resume flow, output path, and raw terminal output
  - exposes `runOverrides.model`, `runOverrides.language`, `runOverrides.max_iter`, `runOverrides.papers_per_query`
  - still depends on global `projectConfig.llm.provider`

### Current configuration experience

- `frontend/src/components/tabs/CredentialsTab.tsx`
  - mixes credentials with global provider/model selection
  - also includes role-level model configuration

### Current model configuration fragmentation

The UI currently exposes three different model decision points:

1. `projectConfig.llm.provider` + `projectConfig.llm.model`
2. `projectConfig.llm.role_models[*]`
3. `runOverrides.model`

This is the main UX conflict:

- users cannot tell which model is truly effective
- the chat entry screen looks like a configuration form
- model and provider decisions are split between run time and settings time

## Current Backend Constraints

### Config API

- `GET /api/config` returns persisted config plus `runtime_mode`
- `POST /api/config` saves the config payload as YAML

### Run API

- `POST /api/run` still accepts the old `runOverrides` shape
- `_build_run_command()` maps runtime fields to CLI flags
- `runOverrides.model` is still forwarded to `--model`

### Config normalization

- `src/agent/core/config.py`
  - `normalize_and_validate_config()` normalizes global provider/model settings
  - `apply_role_llm_overrides()` applies role-specific model overrides at execution time

Implication for Phase 1:

- the frontend can change layout and interaction model first
- the frontend should avoid inventing a second temporary config model
- removal of `runOverrides.model` and `projectConfig.llm.provider/model` should be deferred until backend changes are ready

## Phase 1 UX Direction

### Product-level change

The app should stop presenting itself as a tabbed config console.

The new top-level IA should be:

1. Chat
2. Settings

This is the critical shift. Users should land in a conversation workspace first, not in a form.

### Phase 1 layout principle

Chat should be optimized for one primary action:

- enter a question
- choose an agent
- start the conversation

Configuration becomes secondary and moves behind Settings.

## Target Information Architecture

### Top-level app shell

- `chat`
- `settings`

### Settings sections

Settings can still internally reuse the existing tab content during the migration, but the navigation language should change from many primary tabs to one settings area with grouped sections:

- Models and Roles
- Credentials
- Data Sources
- Retrieval
- Strategy
- Multimodal
- Paths
- Safety
- Advanced

Phase 1 should treat these as settings subsections, not first-class pages in the main shell.

## Target Chat Experience

### Primary layout

The chat page should look like a conversation app, not a dashboard.

Recommended desktop layout:

- top bar
  - product title
  - active agent badge
  - settings entry
- conversation area
  - empty state before first message
  - message list after start
- composer area
  - multi-line input
  - agent selector
  - send button
- optional side panel
  - current run status
  - resume history later

### Empty state

Before the first run, the chat page should show:

- a short product statement
- a large prompt input
- agent cards or a compact agent selector
- 3 to 4 suggestion chips

This makes the experience feel closer to ChatGPT and removes the "form wall" problem.

### In-conversation state

After submit:

- user question appears as a user bubble
- assistant output streams into an assistant bubble
- run status appears above or beside the message stream
- low-level logs should be hidden by default behind a "details" expander

The current raw terminal block should not remain the primary visual output.

## Proposed Agent Selection Model

### UX model

The chat composer should expose one agent selector.

Recommended Phase 1 options:

- `Research OS`
- `Researcher`
- `Analyst`
- `Critic`

### Compatibility note

The current backend does not yet expose a first-class `agent_id` contract through `/api/run`.

So Phase 1 should separate:

- user-facing agent selection state
- backend execution mapping

Recommended transition behavior:

- keep a frontend `selectedAgent`
- map unsupported agents to the closest current runtime path
- default all agents to current `mode: "os"` until Phase 3 adds explicit server support

This avoids blocking the new UI on backend work, while keeping the intended UX visible.

## Proposed Component Tree

### App shell

- `AppShell`
- `PrimarySidebar`
- `ChatPage`
- `SettingsPage`

### Chat page

- `ChatPage`
- `ChatHeader`
- `ChatEmptyState`
- `ChatMessageList`
- `ChatMessageBubble`
- `ChatRunStatus`
- `ChatComposer`
- `AgentPicker`
- `RunDetailsDrawer`

### Settings page

- `SettingsPage`
- `SettingsNav`
- `SettingsSectionLayout`
- existing settings sections adapted from current tab components

## Proposed State Refactor

### Keep in app state

- `projectConfig`
- `credentials`
- provider model catalogs

### Replace or reshape

Current `runOverrides` is too form-centric. Phase 1 should begin splitting it into chat-oriented state.

Recommended additions:

- `selectedView: "chat" | "settings"`
- `selectedAgent: string`
- `chatInput: string`
- `chatMessages: ChatMessage[]`
- `runStatus: "idle" | "starting" | "streaming" | "done" | "error"`
- `runDetails: string[]`

Recommended transitional rule:

- keep `runOverrides` for backend submission
- derive `runOverrides` from chat UI state at send time
- stop binding most chat controls directly to persistent config fields

This reduces accidental config mutation from the run page.

## Proposed Message Model

Add a frontend-only message structure:

```ts
type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  status?: "streaming" | "done" | "error";
  agentId?: string;
  createdAt: string;
};
```

This lets the UI render a real conversation even before the backend supports structured multi-turn sessions.

## Phase 1 Interaction Mapping

### On first send

Composer inputs:

- prompt
- selected agent

Derived payload:

- `runOverrides.topic = prompt`
- `runOverrides.mode = "os"` for now
- `runOverrides.resume_run_id = ""`
- model comes from saved settings, not the chat page

### Stream handling

Current backend returns plain text stream lines.

Phase 1 should adapt that by:

- creating one assistant message in `streaming` state
- appending incoming chunks to that message content
- mirroring the same chunks into `runDetails`

This keeps compatibility with the existing API while changing the presentation layer.

### Resume flow

Resume should move out of the primary composer.

Recommended Phase 1 placement:

- small "Resume run" action in the chat header
- opens a lightweight modal or inline panel

Reason:

- resume is an advanced flow
- it should not compete with the main "ask and run" action

## Settings Consolidation Direction

Phase 1 should prepare the later settings consolidation now.

### Chat page should remove

- global model selector
- run-time model selector
- output directory form block
- verbose and scrape toggles from the main surface
- resume input from the main surface

### Settings page should own

- role model configuration
- provider catalogs and credentials
- strategy and retrieval knobs
- output and path settings
- advanced runtime toggles

Quick settings may exist in chat later, but they should be lightweight and non-authoritative.

## Visual Direction

The current UI uses a standard card-based admin layout. The new chat page should intentionally break from that.

Recommended visual changes:

- full-height conversation canvas
- less card stacking, more whitespace
- sticky composer at bottom
- message bubbles with stronger hierarchy
- details panel with subdued styling
- agent selector as segmented chips or compact menu, not a full form row

The chat page should feel like a tool for asking, not a tool for filling in controls.

## Phase 1 File Plan

Recommended implementation path:

1. keep `store.tsx` as the state boundary for now
2. replace current `Sidebar` with a smaller primary nav
3. replace `RunTab` with a new `ChatPage`
4. create chat-specific components under `frontend/src/components/chat/`
5. create a `SettingsPage` that nests existing settings sections

Suggested new files:

- `frontend/src/components/chat/ChatPage.tsx`
- `frontend/src/components/chat/ChatHeader.tsx`
- `frontend/src/components/chat/ChatComposer.tsx`
- `frontend/src/components/chat/ChatMessageList.tsx`
- `frontend/src/components/chat/ChatRunStatus.tsx`
- `frontend/src/components/settings/SettingsPage.tsx`

## Phase 1 Acceptance Criteria

Phase 1 is complete when:

- the default landing page is a chat workspace
- users can type a question and pick an agent from the chat page
- the chat page no longer exposes model configuration
- configuration is visually separated into Settings
- streamed run output is rendered as assistant conversation output, not only terminal text
- existing `/api/run` still works without backend schema changes

## Risks and Follow-on Work

### Risk 1

The backend still uses one-shot run execution, not true multi-turn chat sessions.

Impact:

- the UI will look conversational before the backend is fully conversational

Mitigation:

- keep message history frontend-only in Phase 1
- document that real session semantics land in later phases

### Risk 2

The current config save model writes immediately on field change.

Impact:

- settings may still feel fragile until settings-page save behavior is revisited

Mitigation:

- keep this behavior in Phase 1 to reduce scope
- revisit settings save strategy in a later pass

### Risk 3

Agent selection is not yet represented in the backend contract.

Impact:

- some agent choices will be UX placeholders during Phase 1

Mitigation:

- keep the selector visible
- explicitly map all selections through a compatibility layer
- finalize server-side agent dispatch in Phase 3

## Recommended Next Step

After this design is accepted, implement the following in order:

1. app shell split into `Chat` and `Settings`
2. new `ChatPage` with empty state, message list, and composer
3. streaming adapter from `runLogs` into `chatMessages`
4. migration of existing settings tabs under a single settings page
