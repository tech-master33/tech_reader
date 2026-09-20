/*
 * trk_keyboards.h - TechReader native keyboard layer (public interface).
 *
 * A small Windows DLL that installs a WH_KEYBOARD_LL hook and describes
 * every keyboard event through a caller-supplied sink callback. The native
 * layer only DETECTS and DESCRIBES events; all TechReader command logic
 * (Ctrl interrupt, CapsLock+Space menu, ...) lives in the Python layer.
 *
 * Design rules:
 *  - The sink is called synchronously on the hook thread. It must be fast
 *    and must never block: Windows unbinds hooks that stall.
 *  - The hook never swallows keys: it always calls CallNextHookEx, so
 *    TechReader observes the keyboard without changing it.
 *  - Injected (synthetic) events are reported but flagged
 *    (TRK_FLAG_INJECTED) so the command layer can ignore them and avoid
 *    feedback loops.
 *  - The interface is plain C with a stable struct layout so the same
 *    header can later serve additional C++ Windows functionality without
 *    redesigning the keyboard interface.
 *
 * Single instance: one live hook per process (a second successful start
 * returns TRK_ERR_ALREADY_RUNNING and leaves the first hook running).
 */
#ifndef TRK_KEYBOARDS_H
#define TRK_KEYBOARDS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(TRK_KEYBOARD_BUILD)
#  define TRK_KEYBOARD_API __declspec(dllexport)
#else
#  define TRK_KEYBOARD_API __declspec(dllimport)
#endif

/* --- Return codes ------------------------------------------------------- */
#define TRK_OK                    0
#define TRK_ERR_INVALID_ARG      (-1)
#define TRK_ERR_ALREADY_RUNNING  (-2)
#define TRK_ERR_HOOK_FAILED      (-3)
#define TRK_ERR_TIMEOUT          (-4)
#define TRK_ERR_NOT_RUNNING      (-5)

/* --- Event types (TrkKeyboardEvent.event_type) -------------------------- */
#define TRK_KEY_DOWN              0u  /* plain key press                    */
#define TRK_KEY_UP                1u  /* plain key release                  */
#define TRK_SYS_KEY_DOWN          2u  /* WM_SYSKEYDOWN: with Alt or F10     */
#define TRK_SYS_KEY_UP            3u  /* WM_SYSKEYUP                        */

/* --- Modifier bits (TrkKeyboardEvent.modifier_state) --------------------
 * Held bits reflect the physical state via GetAsyncKeyState and are forced
 * from the event itself for the modifier key in the event, so a modifier's
 * own key-down always carries its bit.
 * Toggle bits reflect the keyboard toggle lamps via GetKeyState.           */
#define TRK_MOD_LCTRL             (1u << 0)
#define TRK_MOD_RCTRL             (1u << 1)
#define TRK_MOD_LSHIFT            (1u << 2)
#define TRK_MOD_RSHIFT            (1u << 3)
#define TRK_MOD_LALT              (1u << 4)
#define TRK_MOD_RALT              (1u << 5)
#define TRK_MOD_LWIN              (1u << 6)
#define TRK_MOD_RWIN              (1u << 7)
#define TRK_MOD_CAPS              (1u << 8)  /* Caps Lock key physically held */
#define TRK_MOD_NUM               (1u << 9)  /* Num Lock key physically held  */
#define TRK_MOD_CAPS_ON           (1u << 10) /* Caps Lock toggle is on        */
#define TRK_MOD_NUM_ON            (1u << 11) /* Num Lock toggle is on         */

/* --- Flags (TrkKeyboardEvent.flags) -------------------------------------- */
#define TRK_FLAG_EXTENDED         (1u << 0)  /* LLKHF_EXTENDED                */
#define TRK_FLAG_INJECTED         (1u << 1)  /* LLKHF_INJECTED                */
#define TRK_FLAG_LOWER_IL_INJECTED (1u << 2) /* LLKHF_LOWER_IL_INJECTED       */
#define TRK_FLAG_ALT_DOWN         (1u << 3)  /* LLKHF_ALTDOWN (context code)  */
#define TRK_FLAG_TRANSITION       (1u << 4)  /* LLKHF_UP: state transition    */

/* --- Event description ---------------------------------------------------
 * Plain C struct with natural alignment; identical layout on the Python
 * side (ctypes). time_ms is GetTickCount64() at describe time.             */
typedef struct TrkKeyboardEvent {
    uint32_t event_type;      /* TRK_KEY_*                                   */
    uint32_t vk;              /* virtual-key code (KBDLLHOOKSTRUCT.vkCode)   */
    uint32_t scan_code;       /* scan code (KBDLLHOOKSTRUCT.scanCode)        */
    uint32_t flags;           /* TRK_FLAG_*                                  */
    uint64_t time_ms;         /* ms since boot (GetTickCount64)              */
    uint32_t modifier_state;  /* TRK_MOD_* bitmask                           */
    uint32_t reserved;        /* zero; keeps the layout stable               */
} TrkKeyboardEvent;

/* --- Sink callback -------------------------------------------------------
 * Called once per keyboard event, synchronously on the hook thread.
 * Return value is currently ignored (reserved for future flow control).
 * user_context is the opaque pointer given to trk_keyboard_start().
 * The event pointer is only valid for the duration of the call: copy the
 * data out, do not retain the pointer.                                     */
typedef int (__stdcall *TrkKeyboardSink)(const TrkKeyboardEvent *event,
                                        void *user_context);

/* --- Lifecycle ----------------------------------------------------------- */

/* Install the low-level keyboard hook and start delivering events to sink.
 * Blocks until the hook thread is up (or fails); returns TRK_OK.           */
TRK_KEYBOARD_API int trk_keyboard_start(TrkKeyboardSink sink,
                                        void *user_context);

/* Remove the hook and stop the hook thread. Waits (bounded) for the thread
 * to exit. Safe to call when not running (returns TRK_ERR_NOT_RUNNING).    */
TRK_KEYBOARD_API void trk_keyboard_stop(void);

/* Nonzero while the hook is installed. */
TRK_KEYBOARD_API int trk_keyboard_is_running(void);

/* --- Testing helper ------------------------------------------------------
 * Map a KBDLLHOOKSTRUCT (as received by a low-level hook) into a
 * TrkKeyboardEvent without touching the hook machinery. Exposed so tests
 * can drive the mapping deterministically with synthetic input records.   */
TRK_KEYBOARD_API void trk_keyboard_describe(const void *llhook_struct,
                                            TrkKeyboardEvent *out_event);

#ifdef __cplusplus
}
#endif

#endif /* TRK_KEYBOARDS_H */
