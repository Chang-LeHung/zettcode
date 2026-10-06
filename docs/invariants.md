# Invariants

The rules this codebase depends on but does not enforce by types: the ones a
later change can violate silently and only show up as a stale cell, a leaked
frame loop, a session that will not restore, or a slow path that creeps back.
Each entry names what breaks when it is violated and the test that pins it.

A row marked **done** has a test that fails if the invariant is broken; change
the code and run `make test` to see it. A row marked **todo** is real but not
yet pinned — add the test before relying on it, and flip the mark.

Keep this list honest: a check mark means the cited test actually fails when the
invariant breaks, not merely that the code is exercised.

## Terminal and rendering

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| T1 | A differential frame equals a from-scratch paint of the same canvas: an unchanged cell is never rewritten, a changed one always is, or the screen shows stale glyphs. | done | `test_tui.py::test_differential_renderer_skips_unchanged_rows`, `test_render.py::test_changed_bounds_*` |
| T2 | A wide glyph owns its cell and its `continuation` marker, and is never split across a boundary (the grid would shear). | done | `test_render.py::test_canvas_tracks_wide_glyph_continuation_cells`, `test_rich_lines_clip_wide_characters_when_less_than_two_columns_remain` |
| T3 | Terminal control characters in text are neutralised before they reach the frame (a rendered `\x1b` would let content drive the terminal). | done | `test_tui.py::test_canvas_never_emits_untrusted_terminal_control_characters` |
| T4 | After a palette change the next frame repaints every cell (a diff against the old colours would leave the old theme on screen). | done | `test_app.py::test_switching_the_theme_repaints_the_whole_frame` |
| T5 | Every glyph the interface draws is exactly one cell wide (a two-cell glyph would shift everything after it). | done | `test_framework_core.py::test_every_glyph_the_interface_draws_is_one_cell_wide` |
| T6 | A partial escape, UTF-8 byte, or paste sequence is never emitted as keys; a lone `ESC` is held and then reported as Escape. | done | `test_tui.py::test_input_decoder_handles_fragmented_utf8_keys_mouse_and_paste`, `test_input_decoder_resolves_standalone_escape_explicitly` |
| T7 | The terminal layer imports where `termios`/`tty` are missing and reports a clear error instead of failing at import. | done | `test_tui.py::test_tui_imports_where_termios_is_unavailable`, `test_terminal_requires_an_interactive_descriptor` |
| T8 | The console seam keeps the platform split in one place: the Windows path turns virtual-terminal input and output on and restores the console's modes, and a platform without `SIGWINCH` publishes exactly one resize per size change. | done | `test_console.py` |

## Layout and widgets

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| L1 | A layout never hands a child more than the constraints allow; overflow shrinks proportionally rather than clipping silently. | done | `test_layout.py::test_resolve_tracks_*`, `test_framework_core.py::test_constraints_clamp_measurements_and_deflate` |
| L2 | `ScrollView.top` stays inside `[0, count - height]`, and follows the tail while `follow_tail` is set. | done | `test_layout.py::test_scroll_view_clamps_and_anchors_around_insertions` |
| L3 | Appending above the window does not move the visible content (`adjust_for_insertion`). | done | `test_layout.py::test_scroll_view_keeps_the_view_stable_when_content_is_appended` |
| L4 | A selection is always ordered, clamped to the frame, and the copied text is exactly the cells it covers. | done | `test_layout.py::test_scroll_view_drag_selects_text_and_copies_it`, `test_a_drag_that_leaves_the_view_still_extends_and_copies`, `test_framework_core.py::test_a_drag_over_text_no_widget_owns_copies_it_from_the_frame` |
| L5 | A view that does not select text leaves the drag to the frame selection; the two never both own it. | done | `test_layout.py::test_a_view_that_is_not_selectable_leaves_the_drag_to_the_frame` |
| L6 | After any edit the cursor stays inside `[0, len(text)]`, and motion clamps at both ends. | done | `test_editing.py::test_the_motion_keys_move_the_cursor_and_clamp_at_the_ends`, `test_vertical_motion_keeps_the_column_and_stops_at_the_edges` |
| L7 | Killing text stores exactly the removed range and yanking restores it (the kill buffer is not stale). | done | `test_editing.py::test_the_editing_keys_delete_insert_and_yank` |
| L8 | A click focuses the editor and a paste lands at the cursor, not at the end. | done | `test_editing.py::test_a_click_focuses_the_editor_and_a_paste_lands_at_the_cursor` |
| L9 | Every animation token registered is released; when nothing animates the scheduler reports idle (a leaked token keeps the frame loop awake). | done | `test_app.py::test_scheduler_frames_repaints_and_animation_budget`, `test_widgets.py::test_toast_expires_on_the_clock_and_dismisses_its_screen` |
| L10 | A non-interactive screen receives no input, a modal screen blocks the layers under it, and popping restores focus. | done | `test_app.py::test_a_non_interactive_screen_lets_input_reach_the_layer_below`, `test_modal_screen_traps_input_and_restores_focus_on_pop` |
| L11 | Input runs capture, then the target, then bubbles; the first consumer stops the rest. | done | `test_app.py::test_routing_runs_capture_target_then_bubble`, `test_a_consuming_target_stops_the_bubble_phase` |
| L12 | Hit testing skips covered screens and follows paint order. | done | `test_app.py::test_mouse_routing_uses_paint_order_and_resize_updates_geometry`, `test_popping_a_screen_clears_what_the_overlay_covered` |

## Transcript

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| R1 | `version` moves only when something actually changed; a tick inside the same animation step must not invalidate the view (the cost would grow with the frame rate). | done | `test_performance.py::test_ticks_within_one_animation_step_do_not_invalidate_the_transcript`, `test_an_animation_step_without_a_running_row_leaves_the_version_alone` |
| R2 | `take_dirty` names the earliest changed entry and the view re-measures only that suffix; a cached entry is never rebuilt (the cost would grow with history). | done | `test_performance.py::test_only_new_entries_are_rendered_when_the_transcript_grows`, `test_streaming_an_answer_never_re_renders_completed_entries` |
| R3 | An entry's cache key holds **everything** that changes how it looks; a field left out would render stale rows. | done | `test_agent_entries.py::test_a_text_row_rebuilds_*`, `test_a_processing_row_rebuilds_*`, `test_a_thinking_row_rebuilds_*`, `test_a_tool_row_rebuilds_*` |
| R4 | `_starts`/`_blocks` stay aligned with `entries` after any trim or rebuild, so hit testing and scrolling agree with the screen. | done | `test_performance.py::test_a_trim_rebuilds_the_view_aligned_with_the_remaining_entries` |
| R5 | The displayed entries stay at or below `max_entries + slack`, and an overflow drops the oldest. | done | `test_agent_entries.py::test_the_transcript_drops_the_oldest_entries_at_the_display_cap` |
| R6 | Running rows live at the tail; one animation step repaints only them. | done | `test_performance.py::test_crossing_an_animation_step_repaints_only_the_running_row` |
| R7 | A finished or restored transcript never keeps a running row open. | done | `test_zettcode_app.py::test_restoring_an_interrupted_tool_does_not_show_it_as_running` |
| R8 | Replaying a stored session and running it live build the same entries through the same render chain. | done | `test_replay.py::test_replay_builds_the_rows_the_live_events_built` |

## Session storage

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| S1 | Every `parent` names a message already in the file, checked when writing and when reading. | done | `test_session.py::test_an_unknown_parent_is_rejected_at_write_time` |
| S2 | The head is the last message written; `branch()` walks from it and returns oldest first; a fork drops the abandoned branch out of context. | done | `test_session.py::test_a_fork_leaves_the_abandoned_branch_out_of_context`, `test_each_message_links_to_the_one_before_it` |
| S3 | A checkpoint applies only when its boundary is on the active branch, and its version advances monotonically. | done | `test_session.py::test_a_fork_ignores_a_checkpoint_on_the_abandoned_branch`, `test_checkpoints_must_advance_and_match_the_expected_version` |
| S4 | A half-written final line is tolerated, a corrupt middle line is an error. | done | `test_session.py::test_a_torn_final_line_is_ignored_and_a_corrupt_middle_line_is_not` |
| S5 | The parse cache is keyed on the file, so an external write is never served from memory (a stale cache would hide new messages). | done | `test_session.py::test_an_external_write_is_not_hidden_by_the_parse_cache` |
| S6 | A session id can never leave the store root. | done | `test_session.py::test_session_ids_cannot_leave_the_store` |
| S7 | Metadata, tags, timing, usage, and per-message `attributes` survive the encode/decode round trip (the `@` original prompt depends on it). | done | `test_session.py::test_metadata_tags_timing_and_usage_round_trip`, `test_per_message_attributes_survive_the_round_trip` |
| S8 | Listing sessions reads the metadata log alone, never a conversation file. | done | `test_session.py::test_the_listing_answers_from_the_metadata_log_alone` |

## Mentions, registry, and commands

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| M1 | `plain_text(parts)` reproduces exactly what the reader typed, chips and tokens included, in order. | done | `test_mentions.py::test_the_model_text_keeps_the_draft_and_appends_each_reference` |
| M2 | When a hint is added, `attributes["prompt"]` is the typed text, and a restored session shows that text. | done | `test_mentions.py::test_request_appends_the_hint_and_keeps_the_typed_text`, `test_replay_shows_the_typed_text_instead_of_the_expanded_one` |
| M3 | A turn with an image keeps its part order; the hint is one more text part at the end. | done | `test_mentions.py::test_an_image_turn_appends_the_hint_as_one_more_text_part` |
| M4 | An unknown token, or no provider at all, leaves the message exactly as typed. | done | `test_mentions.py::test_a_draft_with_no_provider_is_sent_as_written`, `test_an_image_turn_with_an_unknown_reference_is_sent_as_written` |
| M5 | In a registry the first provider to claim a name wins, `items()` keeps provider order, `find` answers nothing for an unknown name. | done | `test_registry.py::test_a_registry_keeps_the_first_provider_to_claim_a_name` |
| M6 | A mention provider owns one kind; a second one for the same kind is rejected, so a token resolves unambiguously. | done | `test_mentions.py::test_a_plugin_registers_one_mention_provider_per_kind` |

## Shell, steering, and notices

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| U1 | While a turn runs, a plain prompt steers instead of being refused; at most `MAX_STEERING` queue up; the queue empties when the run ends. | done | `test_zettcode_app.py::test_app_steers_a_second_prompt_and_ctrl_c_stops_the_first`, `test_steering_stops_at_the_limit` |
| U2 | A steering message leaves the queue before it is echoed, so it is shown exactly once. | done | `test_zettcode_app.py::test_a_steering_message_is_echoed_when_the_agent_adopts_it` |
| U3 | A toast is a paint-only layer: it never takes input, and it expires and releases its animation token. | done | `test_zettcode_app.py::test_a_toast_does_not_block_scrolling_the_transcript`, `test_widgets.py::test_toast_expires_on_the_clock_and_dismisses_its_screen` |
| U4 | A command result is applied in order — transcript message, toast, page, relayout — so a page never covers the toast it was announced with. | done | `test_zettcode_app.py::test_a_command_result_is_applied_in_order` |
| U5 | The status line shows the one-off note when there is one, else the state word. | done | `test_plugins.py::test_the_activity_label_prefers_its_note_over_the_state_word` |
| U6 | Sending a mention keeps the rest of the draft, whatever the cursor position. | done | `test_zettcode_app.py::test_accepting_a_mention_keeps_the_rest_of_the_draft` |
| U7 | A command's `context.ui` writes reach the screen during the run; they are not deferred to the result, or a long command could not report progress. | done | `test_zettcode_app.py::test_a_command_reports_through_its_context_while_it_runs` |

## Plugins and configuration

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| P1 | One broken plugin is reported and never stops the others or the builtin rows. | done | `test_plugins.py::test_a_broken_plugin_is_reported_and_never_stops_the_others` |
| P2 | A repeated segment name replaces in place, a new name appends after the builtin, and `override` empties its side. | done | `test_plugins.py::test_overriding_a_builder_fills_that_named_slot`, `test_a_new_segment_appends_after_the_builtin_one`, `test_override_clears_the_side_it_names` |
| P3 | A command name is unique across plugins and cannot shadow a builtin. | done | `test_plugins.py::test_two_plugins_cannot_claim_the_same_command`, `test_zettcode_app.py::test_app_and_agent_commands_are_routed_to_their_owners` |
| P4 | A segment builder that raises is dropped for that frame only; the other segments on the side still paint. | done | `test_zettcode_app.py::test_a_segment_that_raises_is_dropped_for_that_frame_only` |
| P5 | A plugin hook fan-out keeps priority order, and every plugin sees an external event even after one accepts it. | done | `test_plugins.py::test_hooks_fan_out_in_priority_order_and_the_host_rises_with_them`, `test_every_plugin_sees_an_external_event_even_after_one_accepts` |
| C1 | The config rejects unknown keys and wrong types, resolves paths, and falls back to `OPENAI_API_KEY`. | done | `test_config.py::test_load_config_*` |
| C2 | A theme file overrides only the roles it names; everything else keeps the palette default. | done | `test_theme_config.py` |

## Subagents

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| A1 | A subagent profile is a tool boundary: exploration is read-only, coding may edit but gets no shell, and no child gets a `task` tool of its own. | done | `test_subagents.py::test_subagent_profiles_split_the_tools_by_what_a_child_may_touch`, `test_no_subagent_profile_can_delegate_to_another` |
| A2 | A child session lands in the store with `parent_session_id` set to the calling session. | done | `test_subagents.py::test_the_task_tool_runs_an_explore_child_and_links_its_session` |

## Adding a row

Every row above is marked **done**, so the list is only worth keeping if new
rows keep arriving. A rule belongs here when a change can violate it without a
type error and the failure would be silent — a stale cell, a leaked frame loop,
a message that will not restore, a slow path that creeps back.

When you add one:

1. Write the statement so it says **what breaks**, not just what is true.
2. Add the test first, then check it fails when you break the invariant by hand;
   a test that passes either way is not pinning anything.
3. Mark the row **done** with the test's file and name, or **todo** with what is
   missing, and keep that mark honest.
