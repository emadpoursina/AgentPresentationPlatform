# Tasks: Join with QR Code and Presence (F2)

**Input**: Design documents from `/specs/001-join-qr-presence/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Included — requested via spec acceptance scenarios (Independent Test per story), quickstart validation scenarios, and SC-005 100%-rejection gate.

**Organization**: Grouped by user story; each story independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify environment and declared dependencies before any F2 work

- [x] T001 Verify dev environment per plan.md in pyproject.toml (`uv sync --group dev`; confirm `qrcode[pil]==8.2` declared — no new dependencies)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared domain pieces every user story builds on (event types, participant model, roster)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T002 Extend event types with `participant_joined`/`participant_left` in backend/app/events/models.py (additive to `EXTENDED_EVENT_TYPES`; session scope `mission_id: "session"` per data-model.md)
- [x] T003 Create Participant models with Balanced-30 validation in backend/app/participants/models.py (trim; reject empty/whitespace-only; max 30 chars; allow only letters, numbers, spaces, `- _ ' . ,`; `display_name: null` = anonymous)
- [x] T004 Implement in-memory roster with join/heartbeat/leave/rejoin/timeout-sweep in backend/app/participants/controller.py (threading lock mirroring MissionController; id-keyed records; duplicate names stay distinct; rejoin preserves `id`/`joined_at` with no double count)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Join Presentation via QR Code (Priority: P1) 🎯 MVP

**Goal**: Scannable on-screen code opens the join page for the actual LAN address; manual URL works identically

**Independent Test**: Display presentation page, scan code with a phone on the same network, confirm the join page opens; type the shown URL manually and confirm the same page (spec US1 scenarios 1–3)

- [x] T005 [US1] Implement join-info and QR endpoints in backend/app/api/participants.py (`GET /api/join-info`, `GET /api/join-info/qr`; resolution precedence config/env override → `Host` header → socket LAN IP; loopback-only resolves to `ready: false` with no scannable code; QR regenerated per request)
- [x] T006 [P] [US1] Create join page markup in frontend/static/join.html (QR image element, typed join URL, name/anonymous form, confirmation area, setup-notes link; no `innerHTML` for server data)
- [x] T007 [P] [US1] Implement join page script in frontend/static/join.js (fetch join-info, render QR/URL via `textContent`/attributes, submit join, show joined confirmation)
- [x] T008 [US1] Add join-info/QR freshness tests in tests/test_participants.py (QR payload byte-identical to current `join_url`; regenerated — never stale; manual URL reaches same page)

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Join with Display Name or Anonymously (Priority: P1)

**Goal**: Frictionless joining, named or anonymous, with server-authoritative validation

**Independent Test**: Open join page, join with a name and anonymously (both succeed, counted); submit empty/whitespace/over-30/disallowed names (all rejected with clear message, count unchanged)

- [x] T009 [US2] Implement join/heartbeat/leave/rejoin endpoints in backend/app/api/participants.py (`POST /api/participants/join` 201/400 per contracts/participants-api.md; `POST /api/participants/{id}/heartbeat`; `POST /api/participants/{id}/leave` idempotent; `POST /api/participants/{id}/rejoin`; `GET /api/participants`; exactly one `participant_joined`/`participant_left` per real transition)
- [x] T010 [US2] Wire participants router in backend/app/main.py (include router alongside missions/events routers)
- [x] T011 [US2] Add join validation tests in tests/test_participants.py (named 201 + opaque id; anonymous 201 with `display_name: null`; empty/whitespace-only/31-char/disallowed-char → 400 with `detail` and zero roster change; SC-005 gate)

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - See Who Has Joined (Priority: P2)

**Goal**: Presenter sees the live connected count; each participant sees joined confirmation; leaves/timeouts decrement

**Independent Test**: Two devices join → count 2 within seconds; one leaves → count 1 within seconds; each device shows joined confirmation (spec US3 scenarios 1–4)

- [x] T012 [US3] Subscribe new event types and render live count in frontend/static/app.js and frontend/static/index.html (add `participant_joined`/`participant_left` to SSE subscription list; presence-count element updated from events/roster; all names via `textContent`)
- [x] T013 [US3] Add presence tests in tests/test_participants.py (join→count+1; leave→count−1 within window; double leave idempotent with single `participant_left`; rejoin restores same `id`/`joined_at` with no duplicate; timeout sweep demotes stale `connected` to `timed_out`; duplicate display names counted as distinct)

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: User Story 4 - Verify Local Network Reachability (Priority: P3)

**Goal**: Presenter can confirm LAN reachability and gets hotspot/firewall/bind guidance when it fails

**Independent Test**: Start app, confirm the displayed join address is LAN-reachable (not loopback); simulate unreachable setup and confirm guidance covers device-to-device permission, firewall, and port binding (spec US4 scenarios 1–2)

- [x] T014 [US4] Add setup guidance and not-ready state in frontend/static/index.html and frontend/static/join.html (hotspot device-to-device permission, firewall, port-binding checks; loopback resolution shows not-ready instead of QR)
- [x] T015 [US4] Add reachability tests in tests/test_participants.py (loopback-only resolution → `ready: false` and no scannable code; LAN resolution → `ready: true` with matching QR payload)

**Checkpoint**: All user stories should now be independently functional

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validation, hygiene, and security self-check across all stories

- [x] T016 Run quickstart.md validation scenarios 1–6 against a local server in specs/001-join-qr-presence/quickstart.md (phone rehearsal with 3+ devices where possible; record SC-001–SC-005 results)
- [x] T017 [P] Run full regression gates with zero new warnings in pyproject.toml scope (`uv run ruff check .` clean; `uv run pytest -q` all pass including tests/test_participants.py)
- [x] T018 [P] Audit participant data handling in frontend/static/app.js, frontend/static/join.js, backend/app/api/participants.py (`textContent`-only rendering; no email/phone/credential collection; no management/debug exposure; server-side validation authoritative)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phases 3–6)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel (if staffed)
  - Or sequentially in priority order (US1 → US2 → US3 → US4)
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P1)**: Can start after Foundational (Phase 2) - Uses join-info page from US1 for the full flow but endpoint + validation independently testable via HTTP
- **User Story 3 (P2)**: Can start after Foundational (Phase 2) - Consumes join/leave events from US2; count rendering independently testable with seeded roster
- **User Story 4 (P3)**: Can start after Foundational (Phase 2) - Builds on join-info readiness flag from US1; guidance content independently reviewable

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Models before services (Foundational: T003 before T004)
- Services before endpoints (T004 before T005/T009)
- Core implementation before integration (endpoints before frontend wiring)
- Story complete before moving to next priority

### Parallel Opportunities

- T006 + T007 (different files: join.html vs join.js) can run in parallel
- T017 + T018 (gates vs audit, different concerns/files) can run in parallel
- Once Foundational completes, US1/UI (T006/T007) and US2/endpoints (T009) can proceed in parallel by different workers (same-file T005/T009 both touch api/participants.py — sequence them, do not parallelize)
- T002 (events/models.py) vs T003/T004 (new participants module) touch different files — parallelizable, but T004's event emission depends on T002's type names, so sequence T002 first

---

## Parallel Example: User Story 1

```bash
# Launch the two US1 frontend tasks together (different files, no shared edits):
Task: "Create join page markup in frontend/static/join.html"
Task: "Implement join page script in frontend/static/join.js"
```

---

## Implementation Strategy

### MVP First (User Stories 1–2)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 2: Foundational (T002–T004)
3. Complete Phase 3: User Story 1 (T005–T008)
4. Complete Phase 4: User Story 2 (T009–T011)
5. **STOP and VALIDATE**: Scan QR with a real phone, join named + anonymously, confirm invalid names rejected — demo-ready join entry
6. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → QR join entry works (MVP part 1)
3. Add User Story 2 → Test independently → validated joining works (MVP complete)
4. Add User Story 3 → Test independently → live presence works
5. Add User Story 4 → Test independently → setup guidance works
6. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (T005–T008)
   - Developer B: User Story 2 (T009–T011)
   - Developer C: User Stories 3–4 (T012–T015)
3. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Verify tests fail before implementing
- No commits/pushes from workers — parent ships per project rules
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
