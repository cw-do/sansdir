# sansdir demo recording — drives the TUI through a representative
# real-data session on IPTS-35270 and writes ``demo.gif``.
#
# Run with:
#
#     vhs demo.tape
#
# Prerequisites at recording time
# --------------------------------
# 1. ``sansdir`` on PATH (or use the cluster wrapper at
#    ``/SNS/EQSANS/shared/script/sansdir/bin/sansdir``).
# 2. ``$DISPLAY`` set — matplotlib plot subprocesses spawn off-screen
#    in their own windows. vhs only captures the terminal, so plot
#    windows themselves are NOT visible in the gif (you'll see the
#    "plot opened" status line but not the plot canvas). That's a
#    limitation of every terminal recorder, not specific to vhs.
# 3. OnCat creds in ``~/.config/sansdir/config.toml`` so ``i`` can
#    resolve IPTS-35270.
# 4. The IPTS-35270/shared/output1/ tree containing the porsil
#    files this script names. If the layout drifts, edit the
#    Type strings below.
#
# Tuning the gif
# --------------
# Each ``Sleep`` is the total dwell time on that frame; nudge them
# down for a snappier demo, or up if a network call (the OnCat
# fetch on ``i``, the catalog fetch after the IPTS pick) is slow
# on your link. ``TypingSpeed`` controls the per-character delay
# inside ``Type "..."`` strings.

Output demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1400
Set Height 800
Set Theme "Dracula"
Set TypingSpeed 60ms

# ---------------------------------------------------------------
# 1. Launch sansdir.
# ---------------------------------------------------------------
Type "sansdir"
Enter
Sleep 2s

# ---------------------------------------------------------------
# 2. Open IPTS browser, filter to 35270, pick + confirm.
#
# ``i`` opens the OnCat browser modal; the list has focus by
# default, so press ``/`` to focus the filter input before typing.
# Enter on the filter moves focus back to the list; Enter on the
# list picks the highlighted IPTS; ``y`` accepts the cd-and-load
# confirm dialog.
# ---------------------------------------------------------------
Type "i"
Sleep 4s
Type "/"
Sleep 300ms
Type "35270"
Sleep 1s
Enter
Sleep 500ms
Enter
Sleep 500ms
Type "y"
Sleep 4s

# ---------------------------------------------------------------
# 3. Toggle the catalog 2-3 times with ``c`` (was F10; rebound
#    because most terminals capture F10 for the menu bar).
#    End on catalog visible.
# ---------------------------------------------------------------
Type "c"
Sleep 1s
Type "c"
Sleep 1s
Type "c"
Sleep 1500ms

# ---------------------------------------------------------------
# 4. Tab into the catalog, scroll a few rows, plot raw run.
#    The detector-heatmap window opens off-camera; the TUI shows
#    a status notification.
# ---------------------------------------------------------------
Tab
Sleep 500ms
Down
Down
Down
Sleep 500ms
Type "p"
Sleep 4s

# ---------------------------------------------------------------
# 5. Tab back to the file (left) pane.
# ---------------------------------------------------------------
Tab
Sleep 1s

# ---------------------------------------------------------------
# 6. Navigate into shared/output1/. The IPTS confirm in step 2
#    already ``cd``s the active pane into ``IPTS-35270/shared``,
#    so we just need to dive into ``output1``. We use the ``/``
#    filter to land on the row with one keystroke instead of
#    counting Down presses.
# ---------------------------------------------------------------
Type "/"
Sleep 300ms
Type "output1"
Sleep 600ms
Enter
Sleep 500ms
Enter
Sleep 1s
Escape

# ---------------------------------------------------------------
# 7. Tag the two Iq files via glob, plot the log-log overlay.
# ---------------------------------------------------------------
Type "+"
Sleep 300ms
Type "porsil_20C_*Iq.dat"
Enter
Sleep 1s
Type "p"
Sleep 4s

# ---------------------------------------------------------------
# 8. Drop all tags.
# ---------------------------------------------------------------
Type "u"
Sleep 1s

# ---------------------------------------------------------------
# 9. Tag the matching transmission files (the glob covers both
#    the ``raw_trans.txt`` and the processed ``trans.txt`` for
#    porsil_20C_2o5m), plot transmission.
# ---------------------------------------------------------------
Type "+"
Sleep 300ms
Type "porsil_20C_2o5m*trans.txt"
Enter
Sleep 1s
Type "p"
Sleep 4s
Type "u"
Sleep 1s

# ---------------------------------------------------------------
# 10. Move cursor to the processed NeXus, plot the detector
#     heatmap from the Mantid Workspace2D.
# ---------------------------------------------------------------
Type "/"
Sleep 300ms
Type "porsil_30C_4m_processed"
Sleep 600ms
Enter
Sleep 500ms
Type "p"
Sleep 4s
Escape

# ---------------------------------------------------------------
# 11. (Visual check — pane is still showing output1/.)
# ---------------------------------------------------------------
Sleep 1s

# ---------------------------------------------------------------
# 12. Filter to the merged files and tag all visible.
#
#     The script's spec says "first 10" but tagging by glob ``*``
#     after a ``merged`` filter is much more visually compelling
#     than 10 separate Space presses, and produces the same demo
#     value. Adjust to taste — replace the ``+`` ``*`` block with
#     repeated ``Down`` + ``Space`` if you want the literal 10.
# ---------------------------------------------------------------
Type "/"
Sleep 300ms
Type "merged"
Sleep 600ms
Enter
Sleep 500ms
Type "+"
Sleep 300ms
Type "*"
Enter
Sleep 1500ms

# ---------------------------------------------------------------
# 13. Zip the tagged files into ``demo.zip``.
#
# The TextPromptDialog opens with ``<cwd>.zip`` (here:
# ``output1.zip``) pre-filled. ``Ctrl+u`` clears the line in
# Textual's Input — when focus is in the dialog, the Input owns
# the binding, so Ctrl+u doesn't trigger the app's pane-swap.
# ---------------------------------------------------------------
Type "z"
Sleep 600ms
Ctrl+u
Sleep 200ms
Type "demo.zip"
Enter
Sleep 2s
Escape

# ---------------------------------------------------------------
# 14. Tag the new demo.zip and open the email screen.
# ---------------------------------------------------------------
Type "/"
Sleep 300ms
Type "demo.zip"
Sleep 600ms
Enter
Sleep 500ms
Space
Sleep 300ms
Type "e"
Sleep 3s
Escape
Sleep 500ms
Escape

# ---------------------------------------------------------------
# 15. Step up to shared/.
# ---------------------------------------------------------------
Backspace
Sleep 1500ms

# ---------------------------------------------------------------
# 16-17. Cursor to README, F3 view, F3 close.
# ---------------------------------------------------------------
Type "/"
Sleep 300ms
Type "README"
Sleep 600ms
Enter
Sleep 500ms
F3
Sleep 4s
F3
Sleep 500ms
Escape

# ---------------------------------------------------------------
# 18. Swap left/right pane cwds. Focus is in the file pane here,
#     so ``Ctrl+u`` reaches the app's keymap → ``pane.swap`` (NOT
#     the input clear-line we used in step 13 — different focus,
#     different binding owner).
# ---------------------------------------------------------------
Ctrl+u
Sleep 2s

# ---------------------------------------------------------------
# 19. Quit cleanly.
# ---------------------------------------------------------------
Type "q"
Sleep 500ms
