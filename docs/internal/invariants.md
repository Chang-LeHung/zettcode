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
| T9 | An HTML entity is decoded exactly once, and in every place that text is measured as well as every place it is painted, so a table column measures what it will draw; code spans and fenced blocks keep their escapes literal. | done | `test_markdown.py::test_every_inline_path_decodes_its_entities`, `test_a_table_column_is_measured_after_its_entities_decode`, `test_a_pipe_spelled_as_an_entity_does_not_split_a_table_cell`, `test_an_escaped_escape_is_decoded_once`, `test_code_keeps_its_entity_references_literal`, `test_a_link_destination_decodes_its_entities` |
| T10 | Only the references the specification recognises are decoded: the semicolon is required, the digit counts and the name length stay inside the pattern (a name the pattern cannot reach is an entity nothing can decode), an unknown name and a bare `&` stay literal, a reference to no character becomes U+FFFD, and a control character spelled as an entity is stopped by the canvas like any other. | done | `test_markdown.py::test_a_reference_the_spec_does_not_recognise_is_left_as_written`, `test_a_reference_longer_than_the_spec_allows_is_not_one`, `test_every_name_the_html5_table_holds_matches_the_pattern`, `test_a_reference_to_no_character_becomes_the_replacement_glyph`, `test_a_reference_can_name_a_character_beyond_the_basic_plane`, `test_an_entity_the_canvas_cannot_paint_is_neutralised_there` |

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
| R6 | The wait row is the last entry for as long as the request runs — reasoning, tool calls, notices, and the answer all land above it — and one animation step brings up every running row of that request, and only those, so a step's cost follows the request rather than the session. | done | `test_performance.py::test_crossing_an_animation_step_repaints_only_the_running_row`, `test_agent_entries.py::test_the_wait_row_is_pinned_under_every_row_the_reply_produces`, `test_zettcode_app.py::test_one_wait_row_spans_the_whole_request`, `test_agent_entries.py::test_a_step_brings_up_every_running_row_even_around_a_notice`, `test_agent_entries.py::test_an_animation_step_reads_only_the_rows_of_this_request` |
| R7 | A finished or restored transcript never keeps a running row open: a request that ends mid-call closes the rows it left behind, whatever the outcome, so nothing keeps saying it is working. | done | `test_zettcode_app.py::test_restoring_an_interrupted_tool_does_not_show_it_as_running`, `test_a_stopped_request_closes_the_rows_it_left_running` |
| R8 | Replaying a stored session and running it live build the same entries through the same render chain — a live transcript additionally holds the request open in it, which a replay has none of. | done | `test_replay.py::test_replay_builds_the_rows_the_live_events_built` |
| R9 | One row owns the motion: the waiting row's marker and the highlight crossing the word pulse together — a second and a half of movement, then a second at rest — while a running reasoning or tool row paints the same cells at every frame, its timer the only thing that moves. The clock and the stop key sit beside that word in quiet parentheses, in the whole seconds a notice would use and never swept, and the status bar's icon blinks on a period of its own — a second and a half, with no rest — off the same frame count, so a second moving row would compete for the eye and make every animation step rebuild rows nothing changed in. | done | `test_zettcode_app.py::test_the_waiting_wording_carries_a_travelling_highlight`, `test_the_waiting_row_marker_moves_and_rests_with_its_highlight`, `test_the_status_icon_blinks_on_a_period_of_its_own`, `test_a_reasoning_row_is_painted_flat_at_every_frame`, `test_agent_blocks.py::test_the_waiting_row_puts_its_clock_and_the_stop_key_beside_the_word`, `test_only_the_waiting_row_moves`, `test_agent_entries.py::test_a_running_reasoning_or_tool_row_is_not_rebuilt_by_an_animation_step`, `test_a_settled_wait_row_is_not_rebuilt_by_an_animation_step`, `test_a_processing_row_rebuilds_for_its_title_timer_and_frame`, `test_a_thinking_row_rebuilds_for_expansion_text_status_and_timer`, `test_a_tool_row_rebuilds_for_every_field_the_renderer_reads` |
| R10 | A request's wait row is settled rather than removed or left running: it keeps its place at the bottom and takes the elapsed time it measured with the clock reading the request ended on (`Processed for 12s · 22:53`), whatever the outcome — the outcome itself is the notice above it — and a run that never opened one still gets the line as a notice. A row that disappears instead is how a stopped request reads as one that never ran. | done | `test_agent_entries.py::test_settling_the_wait_row_writes_the_line_the_request_ended_on`, `test_zettcode_app.py::test_the_wait_row_stays_pinned_until_the_request_is_settled`, `test_each_turn_reports_how_long_it_took`, `test_app_steers_a_second_prompt_and_ctrl_c_stops_the_first`, `test_agent_blocks.py::test_a_settled_wait_row_is_a_muted_line` |
| R11 | One gutter for every row: a row that opens with a marker draws it in the gutter's first column and its content in the second, and a row without one starts in the second column too — so the user's arrow, the waiting row's sparkle, a tool's outcome, and the composer's prompt share one column, every line of content shares the next, and the caret waits in it. | done | `test_agent_blocks.py::test_every_row_draws_its_marker_in_the_gutter_and_its_content_beside_it`, `test_zettcode_app.py::test_the_composer_prompt_lines_up_with_the_message_above_it` |

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
| U8 | The release check never delays or fails a start: it runs as a background task, a failure reads as "no news" and leaves the stored answer alone, a version the reader skipped is not offered again until a newer one lands, and a dismissal that is only for now leaves the offer standing for the next start. | done | `test_update.py::test_a_check_that_fails_says_nothing_and_changes_nothing`, `test_update.py::test_a_fresh_answer_does_not_ask_the_index_again`, `test_zettcode_app.py::test_skipping_a_release_is_remembered_until_the_next_one`, `test_zettcode_app.py::test_dismissing_for_now_asks_again_on_the_next_start`, `test_zettcode_app.py::test_the_check_and_the_offer_both_answer_to_the_configuration` |
| U9 | A question from the model suspends the run until its panel answers: the reader's text is what resumes the tool call, Escape and Ctrl-C both *decline* it rather than closing the panel silently, an empty answer is refused, a one-answer question asks before replacing what was typed, several questions from one response are asked one after another instead of stacking, and a run that ends closes the panels it left behind without answering a stale one. | done | `test_ask.py::test_the_shape_comes_from_the_runtime_and_is_read_as_it_is`, `test_zettcode_app.py::test_typing_an_answer_sends_it_to_the_suspended_call`, `test_zettcode_app.py::test_enter_on_a_row_sends_that_choice`, `test_zettcode_app.py::test_replacing_a_written_answer_asks_first`, `test_zettcode_app.py::test_a_multiple_choice_question_finishes_on_its_send_row`, `test_zettcode_app.py::test_escape_declines_the_question_so_the_model_can_carry_on`, `test_zettcode_app.py::test_ctrl_c_declines_instead_of_leaving_the_call_suspended`, `test_zettcode_app.py::test_an_empty_answer_is_refused`, `test_zettcode_app.py::test_questions_from_one_response_are_asked_one_after_another`, `test_zettcode_app.py::test_a_finished_run_closes_a_question_that_was_left_open` |
| U10 | A side question runs in the same session but never joins it: the store writes every message of that request as recorded-but-not-replayed and tags it, so the next request's context and an exported trace leave it out while a resumed transcript shows it again — the reader saw that answer; its tools are the reading ones, steering is refused while one is in flight, and it neither compacts nor names the session. | done | `test_side.py::test_the_store_records_a_side_exchange_without_replaying_it`, `test_side.py::test_a_resumed_transcript_shows_the_side_exchange_but_history_does_not`, `test_side.py::test_an_exported_trace_leaves_the_side_exchange_out`, `test_side.py::test_a_side_question_only_gets_the_reading_tools`, `test_side.py::test_a_run_marked_by_the_shell_is_pruned_before_the_model_sees_it`, `test_compaction.py::test_a_side_question_is_never_compacted`, `test_zettcode_app.py::test_btw_asks_a_side_question_and_marks_it`, `test_zettcode_app.py::test_a_side_question_does_not_name_the_session`, `test_zettcode_app.py::test_a_btw_question_waits_for_the_reply_in_flight`, `test_zettcode_app.py::test_typing_during_a_side_question_keeps_the_draft` |
| U11 | A typed slash command runs the handler its name resolves to in the registry — the shell matches no name itself, so a command cannot be special-cased behind its own entry — and what happens when it arrives mid-request is the command's own `when_busy` policy: `"queue"` holds the draft and runs it once the request in flight ends, the default refuses it. | done | `test_zettcode_app.py::test_a_slash_command_runs_through_the_handler_its_name_resolves_to`, `test_a_command_declaring_itself_queued_runs_when_the_reply_ends`, `test_a_command_without_the_queue_policy_is_refused_while_busy` |

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
| C3 | Project instructions are composed by default, pointed at the workspace rather than the process directory, inserted behind the system prompt and ahead of the guidance that runs later, and re-read on every request — a misdirected or stale `AGENTS.md` silently changes what the model is told the project wants. | done | `test_agents_md.py::test_the_workspace_instructions_are_composed_by_default`, `test_the_workspace_instructions_land_behind_the_system_prompt`, `test_an_edited_instruction_file_applies_to_the_next_request` |

## Subagents

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| A1 | A subagent profile is a tool boundary: exploration is read-only, coding may edit but gets no shell, and no child gets a `task` tool of its own. | done | `test_subagents.py::test_subagent_profiles_split_the_tools_by_what_a_child_may_touch`, `test_no_subagent_profile_can_delegate_to_another` |
| A2 | A child session lands in the store with `parent_session_id` set to the calling session. | done | `test_subagents.py::test_the_task_tool_runs_an_explore_child_and_links_its_session` |

## Startup

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| S1 | A launch imports only what the first frame needs: the provider, MCP, and subagent SDKs stay behind the first frame, or every launch pays for a model call — and, until zett-agent 0.1.12 deferred them, a database, its token counter, and its HTTP client — it has not made yet. | done | `test_runtime_models.py::test_the_runtime_module_costs_nothing_until_it_starts` |
| S2 | The runtime warms off the event loop: importing the OpenAI SDK and the subagent chain blocks for ~250 ms, and running that on the loop freezes the interface — no keystroke echo, no repaint — for the whole warm-up right after the first frame. | done | `test_runtime_models.py::test_the_warm_up_never_blocks_the_event_loop` |
| S3 | The first frame is painted before the terminal is asked for its background: an OSC 11 query costs its whole 250 ms timeout on the multiplexers and editors that never answer it, and asking first is a blank screen for exactly that long. | done | `test_runner.py::test_the_first_frame_lands_before_the_terminal_is_asked_for_its_background` |
| S4 | The background query is fire-and-forget: its answer arrives as a REPLY input event and is never decoded as keystrokes, so a terminal that stays quiet cannot hold the loop — the 250 ms it used to cost sat between the placeholder and the real interface — nor type its answer into the reader's draft. | done | `test_runner.py::test_the_background_query_does_not_wait_for_an_answer`, `test_runner.py::test_the_runner_adopts_the_scheme_the_terminal_reports`, `test_tui.py::test_the_input_decoder_reads_a_terminal_reply_without_typing_it` |

## Portability

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| X1 | Every module parses on the oldest supported interpreter, and the shims cover what the standard library only grew later: a 3.12-only construct, an unshimmed `tomllib`/`ExceptionGroup`, or a `StrEnum` that stringifies as `Activity.READY` installs fine and then fails — or draws the member name — on 3.10. | done | `test_compat.py::test_every_module_parses_as_the_oldest_supported_python`, `test_the_str_enum_shim_reads_like_the_value_it_carries`, `test_the_toml_reader_parses_what_the_config_and_theme_files_hold` |

## Terminal identity

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| I1 | Process naming runs only after flag parsing and before the application starts; help never imports the native helper, Windows skips POSIX naming, and unsupported native APIs cannot block startup. | done | `test_cli.py::test_help_never_imports_the_process_naming_helper`, `test_startup_names_the_process_before_entering_the_application`, `test_process_naming_uses_zettcode_instead_of_the_interpreter`, `test_process_naming_failure_does_not_block_startup`, `test_windows_does_not_try_to_rename_the_executable` |
| I2 | A session title never replaces the brand prefix; the current session's name is pulled on every paint, unchanged titles emit no OSC, and shutdown clears it. Nonprintable characters cannot inject terminal controls. | done | `test_zettcode_app.py::test_the_terminal_title_follows_the_session`, `test_runner.py::test_the_runner_names_the_terminal_after_the_app_and_hands_it_back`, `test_shutdown_hands_the_terminal_title_back`, `test_console.py::test_terminal_title_preserves_the_marker_and_session_without_control_injection` |

## Documentation

| # | Invariant (what breaks) | Status | Test |
| --- | --- | --- | --- |
| D1 | Every English guide page has a Chinese page with the same slug; otherwise corresponding-page language switching sends readers to a missing page. | done | `test_docs.py::test_every_english_guide_page_has_a_chinese_counterpart` |
| D2 | Generating the terminal illustration never starts a model, leaks a temporary workspace path, or leaves the process in its temporary directory, even on failure; the same sample produces the same asset. | done | `test_docs.py::test_the_terminal_preview_is_offline_deterministic_and_leaves_no_workspace`, `test_a_failed_preview_restores_the_working_directory` |
| D3 | The SVG illustration escapes transcript text and emits wide glyphs once rather than turning text into executable markup or duplicating continuation cells. | done | `test_docs.py::test_the_terminal_svg_escapes_text_and_does_not_duplicate_wide_glyphs` |
| D4 | README and bilingual config, MCP, and plugin examples use supported keys and real APIs; copied examples must not silently drift into invalid config or unimportable commands. Tests load examples offline, never start servers or models, and write config files only in temporary directories. | done | `test_docs.py::test_documented_config_examples_load_with_the_real_parser`, `test_documented_mcp_examples_parse_without_starting_servers`, `test_documented_plugin_registers_and_runs_its_command` |
| D5 | One 15×10 pixel map and palette drive the terminal welcome, website logo, and documentation preview: mirrored square eyes/ears, a centered pointed heart, and transparent margins. Two pixels per cell produce five terminal rows; labels align beside the mark or stack within narrow bounds. Themes cannot recolour the mark; SVGs preserve every source pixel, use crisp block edges when scaled, and match their generators. | done | `test_zettcode_app.py::test_welcome_mark_is_wide_and_mirror_symmetric_with_a_centered_heart`, `test_welcome_mark_is_compact_and_readable_in_both_themes`, `test_welcome_half_blocks_preserve_every_brand_pixel_and_transparent_margin`, `test_welcome_labels_stack_without_overflow_on_narrow_windows`, `test_docs.py::test_published_brand_assets_match_the_shared_terminal_pixels`, `test_logo_svg_preserves_every_shared_pixel`, `test_terminal_svg_preserves_every_welcome_pixel_without_scaling_seams` |

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
