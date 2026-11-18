# ZAH progress bar pieces

Transparent PNGs, straight (non-premultiplied) alpha, no text. Made by `export_progress_bar_pieces.py`.
Every glow fades to 0 alpha before the canvas edge.

## Files

| File | Size (w x h) |
|---|---|
| progress_bar_frame.png | 1125 x 172 |
| progress_bar_fill_normal.png | 1035 x 94 |
| progress_bar_fill_warning.png | 1035 x 94 |
| progress_bar_fill_complete.png | 1035 x 94 |
| progress_bar_fill_error.png | 1035 x 94 |
| progress_bar_ring.png | 60 x 172 |
| progress_bar_tag_normal.png | 88 x 66 |
| progress_bar_tag_warning.png | 88 x 66 |
| progress_bar_tag_complete.png | 88 x 66 |
| progress_bar_tag_error.png | 88 x 66 |
| progress_bar_frame_small.png | 375 x 78 |
| progress_bar_fill_normal_small.png | 347 x 41 |
| progress_bar_fill_warning_small.png | 347 x 41 |
| progress_bar_fill_complete_small.png | 347 x 41 |
| progress_bar_fill_error_small.png | 347 x 41 |
| progress_bar_ring_small.png | 26 x 78 |
| progress_bar_tag_normal_small.png | 60 x 45 |
| progress_bar_tag_warning_small.png | 60 x 45 |
| progress_bar_tag_complete_small.png | 60 x 45 |
| progress_bar_tag_error_small.png | 60 x 45 |

## Main bar (`*.png`)

All offsets are in pixels from the frame's top-left corner, at 1:1 scale.

- Frame: 1125 x 172. Inner track outline drawn exactly at x 47..1078, y 50..138 (track 1031 x 88; inset left 47, right 47, top 50, bottom 34).
- Fill: 1035 x 94. Place at (45, 47), i.e. the track plus 2 px left/right and 3 px top/bottom of glow margin.
  - To show P%: draw the fill cropped to width = 2 + 1031 * P / 100 (use the full 1035 at 100%).
- Lead x at P% = 47 + 1031 * P / 100.
- Ring: 60 x 172. Place at (lead_x - 30, 0). Same height as the frame; its centre line is the track's centre (y 94).
- Tag: 88 x 66. Place at (lead_x - 44, -70), centred over the ring, just above the frame. Draw the percent text centred at (lead_x, -37).
  - You can also pin the small tags at a fixed spot, the way the animation does.
- Drawing order: frame, then fill, then ring, then tag, then text.

## Small bar (`*_small.png`)

All offsets are in pixels from the frame's top-left corner, at 1:1 scale.

- Frame: 375 x 78. Inner track outline drawn exactly at x 16..359, y 23..62 (track 343 x 39; inset left 16, right 16, top 23, bottom 16).
- Fill: 347 x 41. Place at (14, 22), i.e. the track plus 2 px left/right and 1 px top/bottom of glow margin.
  - To show P%: draw the fill cropped to width = 2 + 343 * P / 100 (use the full 347 at 100%).
- Lead x at P% = 16 + 343 * P / 100.
- Ring: 26 x 78. Place at (lead_x - 13, 0). Same height as the frame; its centre line is the track's centre (y 42.5).
- Tag: 60 x 45. Place at (lead_x - 30, -47), centred over the ring, just above the frame. Draw the percent text centred at (lead_x, -24).
  - You can also pin the small tags at a fixed spot, the way the animation does.
- Drawing order: frame, then fill, then ring, then tag, then text.

## Notes

- Fills are full 0-100% strips. `warning` has its arrow head at the right end, so the arrow only shows near 100%. `error` is solid until about 70% of its length and then breaks into fragments and sparks.
- The ring is the same for every state. Its job is to hide the hard crop edge of the fill.
- If the widget scales pieces, scale them all by the same factor so these offsets stay true.
