# 工具权限矩阵

89 个现有工具；效果声明参与执行检查，旧 read_only 标记仅用于兼容。
每项 effects 显式声明；read_actions/read_when_absent 的参数规则见 tool-permissions.json。
ALLOW/DENY 对旧名、别名、内部子动作同样生效；未知工具拒绝。

| 工具 | 分区 | 声明副作用 | 需要用户授权 |
|---|---|---|---|
| act_until | Z4 | compose | 是 |
| anchor_mem | Z5 | file_write | 是 |
| batch | Z4 | compose | 是 |
| button_down | Z3 | input | 是 |
| button_up | Z3 | input | 是 |
| capture_config | Z1 | config_write | 是 |
| capture_daemon | Z1 | file_write | 是 |
| capture_template | Z5 | file_write | 是 |
| click | Z3 | input | 是 |
| click_template | Z3 | input | 是 |
| click_text | Z3 | input | 是 |
| close_window | Z3 | window, window_close | 是 |
| control_claim | Z0 | control | 是 |
| control_status | Z0 | observe | 否 |
| dataset_explore | Z6 | compose, file_write | 是 |
| dataset_export | Z6 | file_write | 是 |
| dataset_promote | Z6 | file_write | 是 |
| dataset_query | Z6 | observe | 否 |
| dataset_status | Z6 | observe | 否 |
| dataset_triage | Z6 | file_write | 是 |
| diff_baseline | Z2 | screen_read | 是 |
| double_click | Z3 | input | 是 |
| drag | Z3 | input | 是 |
| find_element | Z2 | screen_read | 是 |
| find_text | Z2 | screen_read | 是 |
| frame_diff | Z2 | screen_read | 是 |
| frame_mark | Z2 | config_write | 是 |
| get_window_info | Z2 | screen_read | 是 |
| glyph | Z5 | file_write | 是 |
| housekeeping | Z0 | file_delete | 是 |
| hover_probe | Z3 | input | 是 |
| hud | Z2 | screen_read | 是 |
| key_down | Z3 | input, text_entry | 是 |
| key_press | Z3 | input, text_entry | 是 |
| key_up | Z3 | input | 是 |
| layout_mem | Z5 | file_write | 是 |
| list_virtual_desktops | Z2 | screen_read | 是 |
| list_windows | Z2 | screen_read | 是 |
| macro_list | Z5 | observe | 否 |
| macro_run | Z4 | compose, input, clipboard_write, process, file_write | 是 |
| macro_save | Z5 | file_write | 是 |
| match_template | Z2 | screen_read | 是 |
| maximize_window | Z3 | window | 是 |
| minimize_window | Z3 | window | 是 |
| mouse_move | Z3 | input | 是 |
| move_window | Z3 | window | 是 |
| move_window_to_virtual_desktop | Z3 | window | 是 |
| navigate | Z4 | compose | 是 |
| ocr_read | Z2 | screen_read | 是 |
| probe | Z2 | screen_read | 是 |
| read_digits | Z2 | screen_read | 是 |
| record | Z1 | screen_read, file_write, file_delete | 是 |
| resize_window | Z3 | window | 是 |
| restore_window | Z3 | window | 是 |
| run_script | Z4 | compose, input, clipboard_write, process | 是 |
| sample_stable | Z2 | screen_read | 是 |
| screen_layout | Z2 | screen_read | 是 |
| screen_state | Z2 | screen_read | 是 |
| screenshot | Z1 | screen_read | 是 |
| screenshot_window | Z1 | screen_read | 是 |
| sense | Z2 | screen_read | 是 |
| servo | Z4 | compose | 是 |
| set_baseline | Z5 | file_write | 是 |
| set_config | Z0 | config_write | 是 |
| set_window_topmost | Z3 | window | 是 |
| snap_window_bottom | Z3 | window | 是 |
| snap_window_left | Z3 | window | 是 |
| snap_window_right | Z3 | window | 是 |
| snap_window_top | Z3 | window | 是 |
| snapshot | Z1 | screen_read, file_write, file_delete | 是 |
| switch_to_window | Z3 | window | 是 |
| switch_virtual_desktop | Z3 | window | 是 |
| trace | Z4 | screen_read | 是 |
| track | Z1 | compose, input, clipboard_write, window, file_write | 是 |
| triple_click | Z3 | input | 是 |
| type | Z3 | input, text_entry, clipboard_write | 是 |
| ui_click | Z3 | input | 是 |
| ui_find | Z2 | screen_read | 是 |
| ui_invoke | Z3 | input | 是 |
| ui_set_text | Z3 | input, text_entry | 是 |
| ui_tree | Z2 | screen_read | 是 |
| verify_flow | Z4 | file_write | 是 |
| vision_list | Z5 | file_delete, config_write | 是 |
| wait_baseline_change | Z2 | screen_read | 是 |
| wait_for | Z2 | screen_read | 是 |
| wait_for_change | Z2 | screen_read | 是 |
| wait_template | Z2 | screen_read | 是 |
| watch | Z2 | screen_read | 是 |
| world_state | Z2 | screen_read | 是 |
