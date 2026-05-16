; ContextCut PRO — Product Hunt Video Recording Script (90s)
; ========================================================
; Requires: AutoHotkey (https://www.autohotkey.com)
; Hotkey: F12 to start. 3-second delay before actions begin.
;
; Screen: 1680×1050, Chrome maximized (no bookmarks bar)
; Dashboard: http://localhost:18787 (via SSH tunnel)
;
; Prep (run once before recording):
;   ssh -L 18787:127.0.0.1:18787 steve@192.168.137.252
;   cd ~/contextcut
;   cp starterKnowledgeFiles/lawyer-* knowledge/
;   cp starterKnowledgeFiles/base-* knowledge/
;   ./start.sh
; Then open http://localhost:18787 in Chrome

#Persistent

; ── Coordinate constants (Screen mode, 1680×1050) ──
DEMO_DATA_X := 1490    ; Demo Data button (header right)
DEMO_DATA_Y := 74
BROWSE_X    := 1276    ; Browse Files button
BROWSE_Y    := 114
TABLE_X     := 500     ; Left panel table area
TABLE_Y     := 400
FILE_X      := 582     ; Starter file in modal list
FILE_Y      := 473
CLOSE_X     := 166     ; Modal close button
CLOSE_Y     := 190
TOP_X       := 365     ; Promo tab click (end of script)
TOP_Y       := 18
CHAT_X      := 987     ; Chat textarea
CHAT_Y      := 960
MODEL_X     := 1200    ; Model name input
MODEL_Y     := 930
PARAMS_X    := 1630    ; Params ⚙ button
PARAMS_Y    := 912

; ── Calibration: Ctrl+F12 to show cursor coords ──
^F12::
    CoordMode, Mouse, Screen
    MouseGetPos, mx, my
    MsgBox, Screen position: X=%mx% Y=%my%
return

; ── Main recording sequence (90 seconds) ──
F12::
    CoordMode, Mouse, Screen

    WinActivate, ahk_class Chrome_WidgetWin_1
    if !WinExist("ahk_class Chrome_WidgetWin_1")
    {
        MsgBox, Chrome window not found. Open http://localhost:18787 first.
        return
    }

    Sleep, 3000  ; countdown — switch to OBS, start recording

    ; ===== 0:00 — Seed demo data via API =====
    RunWait, %ComSpec% /c curl -s http://localhost:18787/api/demo/seed > NUL, , Hide
    Sleep, 1500

    ; ===== 0:01 — Click Demo Data =====
    Click, %DEMO_DATA_X%, %DEMO_DATA_Y%
    Sleep, 6000

    ; ===== 0:07 — Scroll table =====
    Click, %TABLE_X%, %TABLE_Y%
    Sleep, 300
    Loop, 4
    {
        Send, {WheelDown}
        Sleep, 250
    }
    Sleep, 4000

    ; ===== 0:12 — Click Browse Files =====
    Click, %BROWSE_X%, %BROWSE_Y%
    Sleep, 4000

    ; ===== 0:16 — Click a starter file in the modal =====
    Click, %FILE_X%, %FILE_Y%
    Sleep, 5000

    ; ===== 0:21 — Close modal =====
    Click, %CLOSE_X%, %CLOSE_Y%
    Sleep, 3000

    ; ===== 0:24 — Focus model input =====
    Click, %MODEL_X%, %MODEL_Y%
    Sleep, 3000

    ; ===== 0:42 — Focus chat input =====
    Click, %CHAT_X%, %CHAT_Y%
    Sleep, 300
    Click, %CHAT_X%, %CHAT_Y%
    Sleep, 700

    ; Clear placeholder
    Send, ^a
    Sleep, 200
    Send, {Delete}
    Sleep, 400

    ; ===== 0:43 — Type query =====
    SendInput, What are the key terms in this non-compete clause?
    Sleep, 5000

    ; ===== 0:48 — Send =====
    Send, {Enter}

    ; ===== 0:49 — Wait for streaming response =====
    Sleep, 20000

    ; ===== 1:09 — Click Params ⚙ =====
    Click, %PARAMS_X%, %PARAMS_Y%
    Sleep, 8000

    ; ===== 1:17 — Close params =====
    Click, %PARAMS_X%, %PARAMS_Y%
    Sleep, 6000

    ; ===== 1:23 — Demo Data final =====
    Click, %DEMO_DATA_X%, %DEMO_DATA_Y%
    Sleep, 6000

    ; ===== 1:29 — Click promo page tab + pause 15s =====
    Click, %TOP_X%, %TOP_Y%
    Sleep, 15000

    ; ===== 1:44 — Done =====
    MsgBox, Done. Stop OBS. Final frame: https://api.contextcut-pro.com/promo

return
